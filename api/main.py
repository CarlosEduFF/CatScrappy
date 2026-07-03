# api/main.py

"""Backend HTTP mínimo para o app mobile (validação no Render).

Reaproveita a camada de scraping HTTP-pura (TopAnimes, AnimesDrive). O
objetivo desta primeira versão é validar se, de dentro de um datacenter,
os sites de anime respondem — o maior risco do projeto. Devolve a URL do
vídeo; quem toca/baixa é o celular.

Rodar local:   uvicorn api.main:app --reload
Rodar Render:  uvicorn api.main:app --host 0.0.0.0 --port $PORT
"""

import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.scrapers.animesdrive_scraper import AnimesDriveScraper
from app.scrapers.base_scraper import UA
from app.scrapers.mangadex_scraper import MangaDexScraper
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
    request: Request,
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

    is_hls = ".m3u8" in video.split("?")[0]
    # HLS toca direto (200 sem cabeçalho especial). Já os arquivos MP4 diretos
    # (incvideo etc.) validam o User-Agent e recusam o player mobile, então
    # passam pelo /proxy, que reenvia os bytes com o UA de browser.
    if is_hls:
        url_player = video
    else:
        base = str(request.base_url).rstrip("/")
        url_player = f"{base}/proxy?url={urllib.parse.quote(video, safe='')}"

    return {"url_video": video, "url_player": url_player, "is_hls": is_hls}


# ----------------------------------------------------------------------
# MANGÁ (MangaDex) — busca, capítulos e páginas.
# O MangaDex tem API pública e estável, sem anti-bot nem bloqueio de IP.
# ----------------------------------------------------------------------
_manga = MangaDexScraper(idioma="pt-br")


@app.get("/manga/buscar")
async def manga_buscar(nome: str = Query(..., min_length=1)):
    mangas = await _run(_manga.buscar_manga, nome)
    return {"resultados": [{"id": m.id, "titulo": m.titulo} for m in mangas]}


@app.get("/manga/capitulos")
async def manga_capitulos(
    manga_id: str = Query(...),
    idioma: str = Query("pt-br", description="pt-br | en | es-la | ... | todos"),
):
    caps = await _run(_manga.listar_capitulos, manga_id, idioma)
    return {
        "capitulos": [
            {
                "id": c.id,
                "numero": c.numero,
                "titulo": c.titulo,
                "paginas": c.paginas,
                "idioma": c.idioma,
            }
            for c in caps
        ]
    }


@app.get("/manga/paginas")
async def manga_paginas(capitulo_id: str = Query(...)):
    """URLs das imagens de um capítulo.

    As imagens vêm do CDN do MangaDex e são públicas (sem Referer), então o
    app pode baixá-las diretamente, sem passar pelo proxy.
    """
    urls = await _run(_manga.obter_paginas, capitulo_id)
    return {"paginas": urls}


@app.get("/proxy")
def proxy(request: Request, url: str = Query(..., description="URL do vídeo a repassar")):
    """Repassa (stream) o vídeo com User-Agent de browser.

    Os hosts de MP4 (incvideo etc.) recusam requisições sem um UA de
    navegador conhecido. Este proxy fica no meio: envia o UA correto e o
    header Range recebido do player, e devolve os bytes conforme chegam —
    sem baixar o arquivo inteiro no servidor. Assim o player mobile pode
    dar seek e stream normalmente.
    """
    # Sem Referer de propósito: os hosts de MP4 (incvideo) devolvem 403 quando
    # recebem um Referer, mas aceitam a requisição sem ele.
    headers = {"User-Agent": UA}
    range_header = request.headers.get("range")
    if range_header:
        headers["Range"] = range_header

    try:
        upstream = urllib.request.urlopen(
            urllib.request.Request(url, headers=headers), timeout=30
        )
    except urllib.error.HTTPError as e:
        raise HTTPException(status_code=e.code, detail=f"Origem retornou {e.code}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Falha ao acessar o vídeo: {e}")

    # Repassa os cabeçalhos relevantes para o player (tipo, tamanho, ranges).
    passar = {}
    for h in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges"):
        valor = upstream.headers.get(h)
        if valor:
            passar[h] = valor
    # 206 se a origem devolveu um trecho (Range), senão 200.
    status = upstream.status if upstream.status in (200, 206) else 200

    def gerar():
        try:
            while True:
                bloco = upstream.read(256 * 1024)
                if not bloco:
                    break
                yield bloco
        finally:
            upstream.close()

    return StreamingResponse(gerar(), status_code=status, headers=passar)
