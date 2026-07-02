# app/scrapers/mangadex_scraper.py

import json
import urllib.parse
import urllib.request

# A API do MangaDex é pública e gratuita. Pede-se um User-Agent identificável.
UA = "CatScrappy/1.0 (leitor de mangá pessoal)"
API = "https://api.mangadex.org"


class Manga:
    """Um mangá encontrado na busca."""
    def __init__(self, id, titulo):
        self.id = id
        self.titulo = titulo


class Capitulo:
    """Um capítulo de mangá."""
    def __init__(self, id, numero, titulo, paginas):
        self.id = id
        self.numero = numero
        self.titulo = titulo
        self.paginas = paginas


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
        dados = self._api("/manga", {"title": titulo, "limit": 15})

        mangas = []
        for m in dados.get("data", []):
            titulos = m["attributes"].get("title", {})
            # Prefere o título no idioma pedido, senão inglês, senão qualquer um
            nome = (titulos.get("en")
                    or titulos.get(self.idioma)
                    or (list(titulos.values())[0] if titulos else "Sem título"))
            mangas.append(Manga(m["id"], nome))
        print(f"[MangaDex] {len(mangas)} resultado(s) encontrado(s).")
        return mangas

    # ------------------------------------------------------------------
    # 2. CAPÍTULOS no idioma escolhido
    # ------------------------------------------------------------------
    def listar_capitulos(self, manga_id: str) -> list:
        print("[MangaDex] Carregando capítulos...")
        capitulos = []
        offset = 0
        vistos = set()  # evita capítulos duplicados (várias scanlations)

        while True:
            dados = self._api(f"/manga/{manga_id}/feed", {
                "translatedLanguage[]": self.idioma,
                "order[chapter]": "asc",
                "limit": 100,
                "offset": offset,
            })

            for c in dados.get("data", []):
                attr = c["attributes"]
                num = attr.get("chapter") or "?"
                paginas = attr.get("pages", 0)
                # Pula capítulos sem páginas ou repetidos (mesmo número)
                if not paginas or num in vistos:
                    continue
                vistos.add(num)
                capitulos.append(Capitulo(
                    id=c["id"],
                    numero=num,
                    titulo=attr.get("title") or "",
                    paginas=paginas,
                ))

            total = dados.get("total", 0)
            offset += 100
            if offset >= total:
                break

        # Ordena numericamente (o feed pode misturar por causa da paginação)
        def chave(cap):
            try:
                return float(cap.numero)
            except (ValueError, TypeError):
                return float("inf")
        capitulos.sort(key=chave)

        print(f"[MangaDex] {len(capitulos)} capítulo(s) em {self.idioma}.")
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
