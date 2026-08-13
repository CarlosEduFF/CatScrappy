# app/scrapers/mugiwaras_scraper.py

import json
import urllib.error
import urllib.parse
import urllib.request

from app.scrapers.mangadex_scraper import Capitulo, Manga

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


class MugiwarasScraper:
    """Scraper do mugiwarasoficial.com (pt-br).

    O site foi reescrito em Next.js e não é mais WordPress/Madara: em vez de
    raspar HTML, hoje consome-se a API JSON pública em app.mugiwarasoficial.com
    (namespace /v1/www, que não pede autenticação — só /v1/www/library e afins,
    de conta logada, devolvem 401).

    Endpoints usados:
      GET /v1/www/search?q=&limit=
      GET /v1/www/works/{slug}
      GET /v1/www/works/{slug}/chapters?page=&limit=
      GET /v1/www/works/{slug}/chapters/{numero}/pages

    O id de um mangá é o slug; o de um capítulo é "slug/numero" — assim
    obter_paginas() consegue montar a URL sozinho, sem consultar a busca.
    """

    base_url = "https://mugiwarasoficial.com"
    api_url = "https://app.mugiwarasoficial.com/v1/www"

    # A API devolve capítulos do mais novo para o mais antigo, paginados.
    # 200 por página é o suficiente para trazer obras longas em poucas idas.
    _CAPS_POR_PAGINA = 200

    def _get_json(self, caminho: str) -> dict:
        req = urllib.request.Request(
            f"{self.api_url}{caminho}",
            headers={
                "User-Agent": UA,
                "Accept": "application/json",
                # A API é aberta, mas o Cloudflare na frente dela é mais
                # tolerante quando a requisição parece vir do próprio site.
                "Origin": self.base_url,
                "Referer": f"{self.base_url}/",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))

    # ------------------------------------------------------------------
    # 1. BUSCA de mangás
    # ------------------------------------------------------------------
    def buscar_manga(self, titulo: str) -> list:
        # Sem ?limit a API devolve só 8 resultados.
        caminho = f"/search?q={urllib.parse.quote(titulo)}&limit=40"
        print(f"[Mugiwaras] Buscando: {self.api_url}{caminho}")
        dados = self._get_json(caminho).get("data") or []

        mangas = [
            Manga(
                id=obra.get("slug", ""),
                titulo=obra.get("title", ""),
                imagem=obra.get("coverUrl", ""),
                # A busca não traz sinopse; ela vem em /works/{slug}.
                sinopse="",
            )
            for obra in dados
            if obra.get("slug")
        ]
        print(f"[Mugiwaras] {len(mangas)} resultado(s) encontrado(s).")
        return mangas

    # ------------------------------------------------------------------
    # 2. CAPÍTULOS (o site é só pt-br; o parâmetro idioma é ignorado)
    # ------------------------------------------------------------------
    def listar_capitulos(self, manga_id: str, idioma: str = None) -> list:
        print("[Mugiwaras] Carregando capítulos...")
        slug = self._slug(manga_id)

        capitulos, pagina, total_paginas = [], 1, 1
        while pagina <= total_paginas:
            corpo = self._get_json(
                f"/works/{urllib.parse.quote(slug)}/chapters"
                f"?page={pagina}&limit={self._CAPS_POR_PAGINA}"
            )
            for cap in corpo.get("data") or []:
                numero = cap.get("number")
                if numero is None:
                    continue
                # A API manda 1190 (int) ou 1190.5 (float); mostra sem o .0.
                numero = (f"{numero:g}" if isinstance(numero, (int, float))
                          else str(numero))
                capitulos.append(Capitulo(
                    id=f"{slug}/{numero}",
                    numero=numero,
                    titulo=cap.get("title", "") or "",
                    paginas=0,  # a lista não traz a contagem de páginas
                    idioma="pt-br",
                ))
            total_paginas = (corpo.get("meta") or {}).get("totalPages", 1) or 1
            pagina += 1

        # A API devolve do mais novo para o mais antigo; ordena crescente.
        def chave(cap):
            try:
                return float(cap.numero)
            except (ValueError, TypeError):
                return float("inf")
        capitulos.sort(key=chave)

        print(f"[Mugiwaras] {len(capitulos)} capítulo(s) encontrado(s).")
        return capitulos

    # ------------------------------------------------------------------
    # 3. URLs das PÁGINAS de um capítulo
    # ------------------------------------------------------------------
    def obter_paginas(self, capitulo_id: str) -> list:
        print("[Mugiwaras] Localizando páginas do capítulo...")
        slug, numero = self._slug_e_numero(capitulo_id)

        corpo = self._get_json(
            f"/works/{urllib.parse.quote(slug)}/chapters/"
            f"{urllib.parse.quote(numero)}/pages"
        )
        paginas = (corpo.get("data") or {}).get("pages") or []
        # As URLs vêm assinadas (?sig=&exp=) com validade de ~9h — a leitura
        # e o download precisam acontecer na mesma sessão, sem guardar o link.
        urls = [p["imageUrl"] for p in paginas if p.get("imageUrl")]

        print(f"[Mugiwaras] {len(urls)} página(s) encontrada(s).")
        return urls

    # ------------------------------------------------------------------
    # Ids: aceita tanto o slug/“slug/numero” quanto uma URL do site, para
    # não quebrar favoritos e histórico salvos no formato antigo.
    # ------------------------------------------------------------------
    def _slug(self, manga_id: str) -> str:
        id_ = manga_id.strip().strip("/")
        if id_.startswith("http"):
            partes = urllib.parse.urlparse(id_).path.strip("/").split("/")
            # /manga/<slug> (novo) ou /manga/<slug>/ (antigo, tema Madara)
            return partes[1] if len(partes) > 1 else (partes[0] if partes else "")
        return id_.split("/")[0]

    def _slug_e_numero(self, capitulo_id: str) -> tuple:
        id_ = capitulo_id.strip().strip("/")
        if id_.startswith("http"):
            partes = urllib.parse.urlparse(id_).path.strip("/").split("/")
        else:
            partes = id_.split("/")
        # Descarta um prefixo "manga" vindo de URLs; sobra <slug>/<numero>.
        if partes and partes[0] == "manga":
            partes = partes[1:]
        if len(partes) < 2:
            raise ValueError(
                f"[Mugiwaras] id de capítulo inválido: {capitulo_id!r} "
                f"(esperado 'slug/numero')"
            )
        return partes[0], partes[1]
