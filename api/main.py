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

from fastapi import Body, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

from api import supabase_client

from app.scrapers.animefire_scraper import AnimeFireScraper
from app.scrapers.animesdrive_scraper import AnimesDriveScraper
from app.scrapers.animesonline_scraper import AnimesOnlineScraper
from app.scrapers.base_scraper import UA
from app.scrapers.sushianimes_scraper import SushiAnimesScraper
from app.scrapers.mangadex_scraper import MangaDexScraper
from app.scrapers import mangaplus_scraper
from app.scrapers.mangalivre_scraper import MangaLivreScraper
from app.scrapers.mugiwaras_scraper import MugiwarasScraper
from app.scrapers.topanimes_scraper import TopAnimesScraper

# Só os scrapers HTTP-puros: o Goyabu depende de Playwright (pesado e frágil
# no free tier) e o player dele nem toca fora do navegador.
SCRAPERS = {
    "topanimes": TopAnimesScraper,
    "animesdrive": AnimesDriveScraper,
    "animefire": AnimeFireScraper,
    "animesonline": AnimesOnlineScraper,
    "sushianimes": SushiAnimesScraper,
}

app = FastAPI(title="CatScrappy API", version="0.1.0")

# O app mobile roda de origens variadas; libera CORS (a API não é sensível).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE"],
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
    except (HTTPException, supabase_client.SupabaseError):
        # Erros já tipados (Supabase, ou HTTPException levantada dentro da
        # função) são tratados pelo chamador — não vira um 502 genérico.
        raise
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
        # Alguns hosts (lightspeedst do animefire) exigem o Referer do site;
        # o scraper informa qual usar para o /proxy repassá-lo.
        referer = getattr(scraper, "referer_do_video", None)
        if referer:
            url_player += f"&referer={urllib.parse.quote(referer, safe='')}"

    return {"url_video": video, "url_player": url_player, "is_hls": is_hls}


# ----------------------------------------------------------------------
# MANGÁ — busca, capítulos e páginas.
# MangaDex tem API pública e estável; Mugiwaras (Madara/WordPress) é
# HTTP-puro e serve as páginas de um CDN aberto. Ambos sem proxy.
# ----------------------------------------------------------------------
MANGA_SITES = {
    "mangadex": MangaDexScraper(idioma="pt-br"),
    "mugiwaras": MugiwarasScraper(),
    "mangalivre": MangaLivreScraper(),
}


def _get_manga_scraper(site: str):
    scraper = MANGA_SITES.get(site)
    if not scraper:
        raise HTTPException(
            status_code=404,
            detail=f"Site '{site}' desconhecido. Use: {', '.join(MANGA_SITES)}",
        )
    return scraper


@app.get("/manga/generos")
async def manga_generos(
    site: str = Query("mangadex", description="mangadex | mugiwaras"),
):
    """Gêneros que o site aceita filtrar (vazio se não suportar)."""
    scraper = _get_manga_scraper(site)
    generos = scraper.listar_generos() if hasattr(scraper, "listar_generos") else []
    return {"generos": generos}


@app.get("/manga/buscar")
async def manga_buscar(
    nome: str = Query("", description="Termo de busca (opcional se houver gênero)"),
    genero: str = Query("", description="Nome do gênero para filtrar (opcional)"),
    site: str = Query("mangadex", description="mangadex | mugiwaras"),
):
    if not nome and not genero:
        raise HTTPException(status_code=400, detail="Informe um termo ou um gênero.")
    scraper = _get_manga_scraper(site)
    # Só o MangaDex aceita gênero por enquanto; os demais ignoram o parâmetro.
    if genero and hasattr(scraper, "listar_generos"):
        mangas = await _run(scraper.buscar_manga, nome, genero)
    else:
        mangas = await _run(scraper.buscar_manga, nome)
    return {
        "resultados": [
            {"id": m.id, "titulo": m.titulo, "imagem": m.imagem, "sinopse": m.sinopse}
            for m in mangas
        ]
    }


@app.get("/manga/capitulos")
async def manga_capitulos(
    manga_id: str = Query(...),
    idioma: str = Query("pt-br", description="pt-br | en | es-la | ... | todos"),
    site: str = Query("mangadex", description="mangadex | mugiwaras"),
):
    scraper = _get_manga_scraper(site)
    caps = await _run(scraper.listar_capitulos, manga_id, idioma)
    return {
        "capitulos": [
            {
                "id": c.id,
                "numero": c.numero,
                "titulo": c.titulo,
                "paginas": c.paginas,
                "idioma": c.idioma,
                "externo_url": getattr(c, "externo_url", ""),
            }
            for c in caps
        ]
    }


@app.get("/manga/paginas")
async def manga_paginas(
    capitulo_id: str = Query(...),
    site: str = Query("mangadex", description="mangadex | mugiwaras"),
):
    """URLs das imagens de um capítulo.

    Tanto o CDN do MangaDex quanto o do Mugiwaras servem as imagens sem
    Referer, então o app pode baixá-las diretamente, sem passar pelo proxy.
    """
    scraper = _get_manga_scraper(site)
    urls = await _run(scraper.obter_paginas, capitulo_id)
    return {"paginas": urls}


@app.get("/manga/mangaplus-img")
async def mangaplus_img(
    url: str = Query(..., description="URL da imagem cifrada no CDN do Manga Plus"),
    key: str = Query("", description="Chave XOR (hex) para decifrar; vazia = imagem crua"),
):
    """Baixa e DECIFRA uma página do Manga Plus, servindo o JPEG pronto.

    O Manga Plus é raspado no celular (mobile/src/mangaplus.js), mas suas
    páginas vêm cifradas com XOR e o fluxo de download/leitura do app só sabe
    consumir URLs de imagem diretas. Então o obterPaginas do celular aponta
    para cá: esta rota decifra e devolve a imagem, e o app trata como uma URL
    normal. Ver app/scrapers/mangaplus_scraper.py.
    """
    try:
        conteudo, content_type = await _run(
            mangaplus_scraper.baixar_pagina_decifrada, url, key
        )
    except ValueError:
        # chave hex inválida
        raise HTTPException(status_code=400, detail="Chave de imagem inválida.")
    return Response(content=conteudo, media_type=content_type)


@app.get("/proxy")
def proxy(
    request: Request,
    url: str = Query(..., description="URL do vídeo a repassar"),
    referer: str = Query(None, description="Referer a enviar ao host (quando exigido)"),
):
    """Repassa (stream) o vídeo com User-Agent de browser.

    Os hosts de MP4 (incvideo etc.) recusam requisições sem um UA de
    navegador conhecido. Este proxy fica no meio: envia o UA correto e o
    header Range recebido do player, e devolve os bytes conforme chegam —
    sem baixar o arquivo inteiro no servidor. Assim o player mobile pode
    dar seek e stream normalmente.
    """
    # Por padrão não envia Referer: os hosts de MP4 (incvideo) devolvem 403
    # quando recebem um. Já outros (lightspeedst do animefire) fazem o
    # oposto e exigem o Referer — nesses o scraper o informa via ?referer=.
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer
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


# ----------------------------------------------------------------------
# CONTAS E FAVORITOS — via Supabase (auth + tabela favoritos).
# A chave secreta fica só no servidor (variável de ambiente); o app nunca
# a vê. Cada rota de favorito valida o token do usuário e opera só sobre os
# favoritos dele. Ver api/supabase_client.py.
# ----------------------------------------------------------------------
def _exige_supabase():
    if not supabase_client.configurado():
        raise HTTPException(
            status_code=503,
            detail="Contas indisponíveis: Supabase não configurado no servidor.",
        )


def _usuario_atual(authorization: str) -> dict:
    """Extrai e valida o token 'Bearer <token>' do header Authorization."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Faça login para continuar.")
    token = authorization.split(" ", 1)[1].strip()
    try:
        usuario = supabase_client.usuario_do_token(token)
    except supabase_client.SupabaseError:
        raise HTTPException(status_code=401, detail="Sessão expirada. Entre novamente.")
    if not usuario.get("id"):
        raise HTTPException(status_code=401, detail="Sessão inválida.")
    return usuario


@app.post("/auth/signup")
async def auth_signup(dados: dict = Body(...)):
    _exige_supabase()
    email = (dados.get("email") or "").strip()
    senha = dados.get("senha") or dados.get("password") or ""
    nome = (dados.get("nome") or "").strip()
    if not email or not senha:
        raise HTTPException(status_code=400, detail="Informe e-mail e senha.")
    try:
        resp = await _run(supabase_client.signup, email, senha, nome)
    except supabase_client.SupabaseError as e:
        raise HTTPException(status_code=e.status, detail=e.mensagem)
    # Se a confirmação de e-mail estiver desligada, o signup já traz o token.
    precisa_confirmar = not resp.get("access_token")
    return {
        "access_token": resp.get("access_token"),
        "refresh_token": resp.get("refresh_token"),
        "usuario": resp.get("user") or resp,
        "precisa_confirmar_email": precisa_confirmar,
    }


@app.post("/auth/login")
async def auth_login(dados: dict = Body(...)):
    _exige_supabase()
    email = (dados.get("email") or "").strip()
    senha = dados.get("senha") or dados.get("password") or ""
    if not email or not senha:
        raise HTTPException(status_code=400, detail="Informe e-mail e senha.")
    try:
        resp = await _run(supabase_client.login, email, senha)
    except supabase_client.SupabaseError as e:
        # Distingue "e-mail não confirmado" de "senha errada" (ambos vêm como
        # HTTP 400) pelo error_code, para dar uma mensagem útil ao usuário.
        if e.codigo == "email_not_confirmed":
            raise HTTPException(
                status_code=403,
                detail="Confirme seu e-mail antes de entrar. Verifique sua caixa de entrada (e o spam).",
            )
        if e.codigo == "invalid_credentials" or e.status == 400:
            raise HTTPException(status_code=401, detail="E-mail ou senha incorretos.")
        raise HTTPException(status_code=e.status, detail=e.mensagem)
    return {
        "access_token": resp.get("access_token"),
        "refresh_token": resp.get("refresh_token"),
        "usuario": resp.get("user"),
    }


@app.get("/favoritos")
async def favoritos_listar(authorization: str = Header(None)):
    _exige_supabase()
    usuario = _usuario_atual(authorization)
    try:
        itens = await _run(supabase_client.listar_favoritos, usuario["id"])
    except supabase_client.SupabaseError as e:
        raise HTTPException(status_code=e.status, detail=e.mensagem)
    return {"favoritos": itens}


@app.post("/favoritos")
async def favoritos_adicionar(dados: dict = Body(...), authorization: str = Header(None)):
    _exige_supabase()
    usuario = _usuario_atual(authorization)
    for campo in ("tipo", "site", "item_id", "titulo"):
        if not dados.get(campo):
            raise HTTPException(status_code=400, detail=f"Campo '{campo}' é obrigatório.")
    try:
        fav = await _run(supabase_client.adicionar_favorito, usuario["id"], dados)
    except supabase_client.SupabaseError as e:
        raise HTTPException(status_code=e.status, detail=e.mensagem)
    return {"favorito": fav}


@app.delete("/favoritos")
async def favoritos_remover(
    tipo: str = Query(...),
    site: str = Query(...),
    item_id: str = Query(...),
    authorization: str = Header(None),
):
    _exige_supabase()
    usuario = _usuario_atual(authorization)
    try:
        await _run(
            supabase_client.remover_favorito, usuario["id"], tipo, site, item_id
        )
    except supabase_client.SupabaseError as e:
        raise HTTPException(status_code=e.status, detail=e.mensagem)
    return {"removido": True}


# ----------------------------------------------------------------------
# HISTÓRICO — episódios/capítulos já vistos, por série. Mesmo esquema de auth
# e validação dos favoritos. Ver api/schema_historico.sql para a tabela.
# ----------------------------------------------------------------------
@app.get("/historico")
async def historico_listar(
    tipo: str = Query(...),
    site: str = Query(...),
    item_id: str = Query(..., description="id/URL da série ou mangá"),
    authorization: str = Header(None),
):
    _exige_supabase()
    usuario = _usuario_atual(authorization)
    try:
        itens = await _run(
            supabase_client.listar_historico, usuario["id"], tipo, site, item_id
        )
    except supabase_client.SupabaseError as e:
        raise HTTPException(status_code=e.status, detail=e.mensagem)
    return {"historico": itens}


@app.post("/historico")
async def historico_marcar(dados: dict = Body(...), authorization: str = Header(None)):
    _exige_supabase()
    usuario = _usuario_atual(authorization)
    for campo in ("tipo", "site", "item_id", "episodio_id"):
        if not dados.get(campo):
            raise HTTPException(status_code=400, detail=f"Campo '{campo}' é obrigatório.")
    try:
        item = await _run(supabase_client.marcar_visto, usuario["id"], dados)
    except supabase_client.SupabaseError as e:
        raise HTTPException(status_code=e.status, detail=e.mensagem)
    return {"visto": item}


@app.delete("/historico")
async def historico_desmarcar(
    tipo: str = Query(...),
    site: str = Query(...),
    item_id: str = Query(...),
    episodio_id: str = Query(...),
    authorization: str = Header(None),
):
    _exige_supabase()
    usuario = _usuario_atual(authorization)
    try:
        await _run(
            supabase_client.desmarcar_visto,
            usuario["id"], tipo, site, item_id, episodio_id,
        )
    except supabase_client.SupabaseError as e:
        raise HTTPException(status_code=e.status, detail=e.mensagem)
    return {"removido": True}


# ----------------------------------------------------------------------
# PERFIL — nome e foto (avatar) do usuário. Nome vai no user_metadata;
# a foto é enviada ao bucket 'avatares' do Supabase Storage.
# ----------------------------------------------------------------------
def _token_do_header(authorization: str) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Faça login para continuar.")
    return authorization.split(" ", 1)[1].strip()


@app.put("/perfil")
async def perfil_atualizar(dados: dict = Body(...), authorization: str = Header(None)):
    _exige_supabase()
    token = _token_do_header(authorization)
    _usuario_atual(authorization)  # valida o token antes de escrever
    nome = dados.get("nome")
    try:
        usuario = await _run(supabase_client.atualizar_perfil, token, nome, None)
    except supabase_client.SupabaseError as e:
        raise HTTPException(status_code=e.status, detail=e.mensagem)
    return {"usuario": usuario}


# Limite de tamanho da foto (evita abusar do storage do plano free).
_MAX_AVATAR_BYTES = 5 * 1024 * 1024  # 5 MB
_TIPOS_AVATAR = {"image/jpeg", "image/png", "image/webp"}


@app.post("/perfil/avatar")
async def perfil_avatar(
    request: Request,
    authorization: str = Header(None),
    content_type: str = Header(None),
):
    """Recebe a imagem como corpo binário puro (não multipart).

    O tipo vem no header Content-Type e os bytes no corpo. Evita a dependência
    'python-multipart' (que o UploadFile/File exigiria), mantendo a API de pé
    mesmo em ambientes onde esse pacote não foi instalado.
    """
    _exige_supabase()
    token = _token_do_header(authorization)
    usuario = _usuario_atual(authorization)

    content_type = (content_type or "").split(";")[0].strip().lower()
    if content_type not in _TIPOS_AVATAR:
        raise HTTPException(status_code=400, detail="Envie uma imagem JPG, PNG ou WEBP.")
    conteudo = await request.body()
    if not conteudo:
        raise HTTPException(status_code=400, detail="Nenhuma imagem recebida.")
    if len(conteudo) > _MAX_AVATAR_BYTES:
        raise HTTPException(status_code=400, detail="A imagem é muito grande (máx. 5 MB).")

    try:
        # 1) sobe a imagem e obtém a URL pública
        url = await _run(
            supabase_client.upload_avatar, usuario["id"], conteudo, content_type
        )
        # 2) grava a URL no perfil do usuário
        atualizado = await _run(supabase_client.atualizar_perfil, token, None, url)
    except supabase_client.SupabaseError as e:
        raise HTTPException(status_code=e.status, detail=e.mensagem)
    return {"avatar_url": url, "usuario": atualizado}
