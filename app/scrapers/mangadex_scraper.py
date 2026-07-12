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
    """Um capítulo de mangá.

    externo_url != "" indica um capítulo licenciado (ex.: MangaPlus) cujas
    imagens não são hospedadas no MangaDex — não é legível no app, só abre
    no navegador. Nesses casos paginas == 0.
    """
    def __init__(self, id, numero, titulo, paginas, idioma="", externo_url=""):
        self.id = id
        self.numero = numero
        self.titulo = titulo
        self.paginas = paginas
        self.idioma = idioma
        self.externo_url = externo_url


class MangaDexScraper:
    """Busca e leitura de mangás via API oficial do MangaDex."""

    # Gêneros (nome exibido -> tag id da API). A API filtra por includedTags[].
    GENEROS = {
        "Ação": "391b0423-d847-456f-aff0-8b0cfc03066b",
        "Aventura": "87cc87cd-a395-47af-b27a-93258283bbc6",
        "Comédia": "4d32cc48-9f00-4cca-9b5a-a839f0764984",
        "Drama": "b9af3a63-f058-46de-a9a0-e0c13906197a",
        "Fantasia": "cdc58593-87dd-415e-bbc0-2ec27bf404cc",
        "Terror": "cdad7e68-1419-41dd-bdce-27753074a640",
        "Histórico": "33771934-028e-4cb3-8744-691e866a923e",
        "Isekai": "ace04997-f6bd-436e-b261-779182193d3d",
        "Mecha": "50880a9d-5440-4732-9afb-8f457127e836",
        "Mistério": "ee968100-4191-4968-93d3-f82d72be7e46",
        "Psicológico": "3b60b75c-a2d7-4860-ab56-05f391bb889c",
        "Romance": "423e2eae-a7a2-4a8b-ac03-a8351462d71d",
        "Sci-Fi": "256c8bd9-4904-4360-bf4f-508a76d67183",
        "Slice of Life": "e5301a23-ebd9-49dd-a0cb-2add944c7fe9",
        "Esportes": "69964a64-2f90-4d33-beeb-f3ed2875eb4c",
        "Suspense": "07251805-a27e-4d59-b488-f0bfbec15168",
        "Tragédia": "f8f62932-27da-4fe4-8ee1-6779a8c5edba",
    }

    def __init__(self, idioma: str = "pt-br"):
        self.idioma = idioma

    def listar_generos(self) -> list:
        """Nomes dos gêneros disponíveis para filtrar."""
        return list(self.GENEROS)

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
    def buscar_manga(self, titulo: str, genero: str = None) -> list:
        print(f"[MangaDex] Buscando: {titulo!r} genero={genero!r}")
        params = {
            "limit": 15,
            "includes[]": "cover_art",
        }
        if titulo:
            params["title"] = titulo
        # Filtro por gênero: adiciona a tag e ordena pelos mais bem avaliados
        # (sem termo de busca, o "relevance" padrão não faz sentido).
        tag = self.GENEROS.get(genero)
        if tag:
            params["includedTags[]"] = tag
            if not titulo:
                params["order[rating]"] = "desc"

        dados = self._api("/manga", params)
        mangas = [self._parse_manga(m) for m in dados.get("data", [])]
        print(f"[MangaDex] {len(mangas)} resultado(s) encontrado(s).")
        return mangas

    def _parse_manga(self, m: dict) -> "Manga":
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

        return Manga(m["id"], nome, imagem=imagem, sinopse=sinopse)

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
        melhores = {}   # numero -> (rank do idioma, Capitulo)  [legíveis]
        externos = {}   # numero -> Capitulo externo (MangaPlus etc.)

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
                lingua = attr.get("translatedLanguage") or ""

                # Capítulo externo/licenciado: sem páginas no MangaDex, mas com
                # link para ler no site oficial (MangaPlus). Guardamos um por
                # número para manter a numeração completa como o site.
                if not paginas:
                    url = attr.get("externalUrl") or ""
                    if url and num not in externos:
                        externos[num] = Capitulo(
                            id=c["id"],
                            numero=num,
                            titulo=attr.get("title") or "",
                            paginas=0,
                            idioma=lingua,
                            externo_url=url,
                        )
                    continue

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

        # Legíveis têm prioridade; capítulos externos só entram para números
        # que não têm nenhuma versão legível disponível.
        capitulos = [cap for _, cap in melhores.values()]
        capitulos += [cap for num, cap in externos.items() if num not in melhores]

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
