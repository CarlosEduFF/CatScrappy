# app/scrapers/mangadex_scraper.py

import json
import urllib.parse
import urllib.request

# A API do MangaDex é pública e gratuita. Pede-se um User-Agent identificável.
UA = "CatScrappy/1.0 (leitor de mangá pessoal)"
API = "https://api.mangadex.org"


class Manga:
    """Um mangá encontrado na busca."""
    def __init__(self, id, titulo, imagem="", sinopse=""):
        self.id = id
        self.titulo = titulo
        self.imagem = imagem
        self.sinopse = sinopse


class Capitulo:
    """Um capítulo de mangá."""
    def __init__(self, id, numero, titulo, paginas, idioma=""):
        self.id = id
        self.numero = numero
        self.titulo = titulo
        self.paginas = paginas
        self.idioma = idioma


class MangaDexScraper:
    """Busca e leitura de mangás via API oficial do MangaDex."""

    def __init__(self, idioma: str = "pt-br"):
        self.idioma = idioma

    def _api(self, path: str, params: dict = None) -> dict:
        url = API + path
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())

    # ------------------------------------------------------------------
    # 1. BUSCA de mangás
    # ------------------------------------------------------------------
    def buscar_manga(self, titulo: str) -> list:
        print(f"[MangaDex] Buscando: {titulo}")
        dados = self._api("/manga", {
            "title": titulo,
            "limit": 15,
            "includes[]": "cover_art",
        })

        mangas = []
        for m in dados.get("data", []):
            attr = m["attributes"]
            titulos = attr.get("title", {})
            # Prefere o título no idioma pedido, senão inglês, senão qualquer um
            nome = (titulos.get("en")
                    or titulos.get(self.idioma)
                    or (list(titulos.values())[0] if titulos else "Sem título"))

            # Capa: vem como relationship cover_art (por causa do includes[])
            imagem = ""
            for rel in m.get("relationships", []):
                if rel.get("type") == "cover_art":
                    arquivo = rel.get("attributes", {}).get("fileName")
                    if arquivo:
                        # .256.jpg é a miniatura oficial do CDN de capas
                        imagem = (f"https://uploads.mangadex.org/covers/"
                                  f"{m['id']}/{arquivo}.256.jpg")
                    break

            descricoes = attr.get("description", {}) or {}
            sinopse = (descricoes.get(self.idioma)
                       or descricoes.get("pt")
                       or descricoes.get("en")
                       or "")

            mangas.append(Manga(m["id"], nome, imagem=imagem, sinopse=sinopse))
        print(f"[MangaDex] {len(mangas)} resultado(s) encontrado(s).")
        return mangas

    # ------------------------------------------------------------------
    # 2. CAPÍTULOS no idioma escolhido
    # ------------------------------------------------------------------
    # Ordem de preferência quando idioma="todos": para cada número de
    # capítulo, fica a versão do idioma mais bem ranqueado disponível.
    PREFERENCIA = ["pt-br", "pt", "en", "es-la", "es"]

    def listar_capitulos(self, manga_id: str, idioma: str = None) -> list:
        """Capítulos legíveis (com páginas no MangaDex) no idioma pedido.

        idioma="todos" busca sem filtro de idioma e escolhe, por número de
        capítulo, a melhor tradução disponível (ver PREFERENCIA). Títulos
        licenciados costumam ter capítulos removidos ou externos (ex.:
        MangaPlus, pages=0) — esses não são legíveis pela API e ficam fora.
        """
        idioma = idioma or self.idioma
        print(f"[MangaDex] Carregando capítulos ({idioma})...")
        offset = 0
        melhores = {}  # numero -> (rank do idioma, Capitulo)

        while True:
            params = {
                "order[chapter]": "asc",
                "limit": 100,
                "offset": offset,
            }
            if idioma != "todos":
                params["translatedLanguage[]"] = idioma

            dados = self._api(f"/manga/{manga_id}/feed", params)

            for c in dados.get("data", []):
                attr = c["attributes"]
                num = attr.get("chapter") or "?"
                paginas = attr.get("pages", 0)
                # Capítulos externos/removidos não têm páginas legíveis
                if not paginas:
                    continue
                lingua = attr.get("translatedLanguage") or ""
                rank = (self.PREFERENCIA.index(lingua)
                        if lingua in self.PREFERENCIA else len(self.PREFERENCIA))
                atual = melhores.get(num)
                if atual and atual[0] <= rank:
                    continue
                melhores[num] = (rank, Capitulo(
                    id=c["id"],
                    numero=num,
                    titulo=attr.get("title") or "",
                    paginas=paginas,
                    idioma=lingua,
                ))

            total = dados.get("total", 0)
            offset += 100
            if offset >= total:
                break

        capitulos = [cap for _, cap in melhores.values()]

        # Ordena numericamente (o feed pode misturar por causa da paginação)
        def chave(cap):
            try:
                return float(cap.numero)
            except (ValueError, TypeError):
                return float("inf")
        capitulos.sort(key=chave)

        print(f"[MangaDex] {len(capitulos)} capítulo(s) em {idioma}.")
        return capitulos

    # ------------------------------------------------------------------
    # 3. URLs das PÁGINAS de um capítulo
    # ------------------------------------------------------------------
    def obter_paginas(self, capitulo_id: str) -> list:
        """Retorna a lista de URLs das imagens (páginas) do capítulo."""
        srv = self._api(f"/at-home/server/{capitulo_id}")
        base = srv["baseUrl"]
        chapter = srv["chapter"]
        hash_ = chapter["hash"]
        # 'data' = qualidade original; 'dataSaver' seria comprimido
        arquivos = chapter["data"]
        return [f"{base}/data/{hash_}/{arq}" for arq in arquivos]
