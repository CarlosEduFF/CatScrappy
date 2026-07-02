# api/main.py

"""Backend HTTP mínimo para o app mobile (validação no Render).

Reaproveita a camada de scraping HTTP-pura (TopAnimes, AnimesDrive). O
objetivo desta primeira versão é validar se, de dentro de um datacenter,
os sites de anime respondem — o maior risco do projeto. Devolve a URL do
vídeo; quem toca/baixa é o celular.

Rodar local:   uvicorn api.main:app --reload
Rodar Render:  uvicorn api.main:app --host 0.0.0.0 --port $PORT
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app.scrapers.animesdrive_scraper import AnimesDriveScraper
from app.scrapers.topanimes_scraper import TopAnimesScraper

# Só os scrapers HTTP-puros: o Goyabu depende de Playwright (pesado e frágil
# no free tier) e o player dele nem toca fora do navegador.
SCRAPERS = {
    "topanimes": TopAnimesScraper,
    "animesdrive": AnimesDriveScraper,
}

app = FastAPI(title="CatScrappy API", version="0.1.0")

# O app mobile roda de origens variadas; libera CORS (a API não é sensível).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _get_scraper(site: str):
    classe = SCRAPERS.get(site)
    if not classe:
        raise HTTPException(
            status_code=404,
            detail=f"Site '{site}' desconhecido. Use: {', '.join(SCRAPERS)}",
        )
    return classe()


# As chamadas de scraping são bloqueantes (urllib) e podem demorar; roda em
# thread pra não travar o event loop com poucas requisições simultâneas.
_pool = ThreadPoolExecutor(max_workers=8)


async def _run(func, *args):
    import asyncio
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(_pool, func, *args)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Falha no scraping: {e}")


@app.get("/healthz")
async def health():
    """Verifica se cada site responde de onde a API está hospedada.

    É o teste que decide a viabilidade no Render: se 'ok' for False aqui,
    o IP do datacenter provavelmente está bloqueado pelo site.
    """
    resultado = {}
    for site, classe in SCRAPERS.items():
        scraper = classe()
        try:
            # Uma busca barata: se voltar sem exceção, o site está acessível.
            await _run(scraper.buscar_anime, "a")
            resultado[site] = {"ok": True}
        except HTTPException as e:
            resultado[site] = {"ok": False, "erro": e.detail}
        except Exception as e:
            resultado[site] = {"ok": False, "erro": str(e)}
    return {"sites": resultado}


@app.get("/sites")
async def sites():
    """Lista os sites disponíveis."""
    return {"sites": list(SCRAPERS)}


@app.get("/buscar")
async def buscar(
    site: str = Query(..., description="topanimes | animesdrive"),
    nome: str = Query(..., min_length=1, description="Nome do anime"),
):
    scraper = _get_scraper(site)
    animes = await _run(scraper.buscar_anime, nome)
    return {"resultados": [asdict(a) for a in animes]}


@app.get("/episodios")
async def episodios(
    site: str = Query(...),
    url: str = Query(..., description="url_detalhes do anime"),
):
    scraper = _get_scraper(site)
    eps = await _run(scraper.listar_episodios, url)
    return {"episodios": [asdict(e) for e in eps]}


@app.get("/extrair-video")
async def extrair_video(
    site: str = Query(...),
    url: str = Query(..., description="url_pagina do episódio"),
):
    scraper = _get_scraper(site)
    video = await _run(scraper.extrair_url_video, url)
    if not video:
        raise HTTPException(
            status_code=404,
            detail="Nenhum vídeo disponível para este episódio.",
        )
    # is_hls ajuda o app a decidir o player: HLS (.m3u8) vs arquivo direto (.mp4)
    return {"url_video": video, "is_hls": ".m3u8" in video.split("?")[0]}
