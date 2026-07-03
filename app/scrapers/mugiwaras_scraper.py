# app/scrapers/mugiwaras_scraper.py

import html as html_lib
import re
import urllib.error
import urllib.parse
import urllib.request

from app.scrapers.mangadex_scraper import Capitulo, Manga

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


class MugiwarasScraper:
    """Scraper do mugiwarasoficial.com (WordPress tema Madara, pt-br).

    A busca é o ?s= padrão do Madara (post_type=wp-manga); a lista de
    capítulos vem do endpoint POST .../ajax/chapters/. As imagens ficam num
    CDN (cdn.mugiverso.com) em page_001.webp, page_002.webp, ...: a página
    do capítulo só expõe a primeira, então o total é descoberto com
    requisições HEAD (busca binária).
    """

    base_url = "https://mugiwarasoficial.com"

    def _req(self, url: str, method: str = "GET"):
        return urllib.request.Request(url, headers={"User-Agent": UA}, method=method)

    def _http_get(self, url: str) -> str:
        with urllib.request.urlopen(self._req(url), timeout=30) as resp:
            return resp.read().decode("utf-8", "replace")

    def _http_post(self, url: str) -> str:
        with urllib.request.urlopen(self._req(url, "POST"), timeout=30) as resp:
            return resp.read().decode("utf-8", "replace")

    def _existe(self, url: str) -> bool:
        try:
            with urllib.request.urlopen(self._req(url, "HEAD"), timeout=15) as resp:
                return resp.status == 200
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            return False

    # ------------------------------------------------------------------
    # 1. BUSCA de mangás
    # ------------------------------------------------------------------
    def buscar_manga(self, titulo: str) -> list:
        url = (f"{self.base_url}/?s={urllib.parse.quote_plus(titulo)}"
               f"&post_type=wp-manga")
        print(f"[Mugiwaras] Buscando: {url}")
        html = self._http_get(url)

        mangas = []
        # Cada resultado é um bloco "row c-tabs-item__content" com capa e título
        for bloco in html.split('c-tabs-item__content')[1:]:
            titulo_m = re.search(
                r'<div class="post-title">\s*<h3[^>]*>\s*<a href="([^"]+)">([^<]+)</a>',
                bloco,
            )
            if not titulo_m:
                continue
            img_m = re.search(r'<img[^>]+(?:data-src|src)="([^"]+)"', bloco)
            mangas.append(Manga(
                id=titulo_m.group(1),  # a própria URL do mangá
                titulo=html_lib.unescape(titulo_m.group(2).strip()),
                imagem=img_m.group(1) if img_m else "",
                sinopse="",  # o Madara não traz sinopse na busca
            ))
        print(f"[Mugiwaras] {len(mangas)} resultado(s) encontrado(s).")
        return mangas

    # ------------------------------------------------------------------
    # 2. CAPÍTULOS (o site é só pt-br; o parâmetro idioma é ignorado)
    # ------------------------------------------------------------------
    def listar_capitulos(self, manga_url: str, idioma: str = None) -> list:
        print("[Mugiwaras] Carregando capítulos...")
        base = manga_url.rstrip("/")
        corpo = self._http_post(f"{base}/ajax/chapters/")

        capitulos = []
        for m in re.finditer(
            r'<li class="wp-manga-chapter[^"]*">\s*<a href="([^"]+)">\s*([^<]+)',
            corpo,
        ):
            link, texto = m.group(1), html_lib.unescape(m.group(2).strip())
            num_m = re.search(r"(\d+(?:\.\d+)?)", texto) or re.search(
                r"(\d+(?:-\d+)?)/?$", link.rstrip("/")
            )
            capitulos.append(Capitulo(
                id=link,  # a própria URL do capítulo
                numero=num_m.group(1) if num_m else "?",
                titulo="",
                paginas=0,  # o Madara não expõe a contagem na lista
                idioma="pt-br",
            ))

        # O ajax devolve do mais novo para o mais antigo; ordena crescente
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
    def obter_paginas(self, capitulo_url: str) -> list:
        print("[Mugiwaras] Localizando páginas do capítulo...")
        html = self._http_get(capitulo_url)

        # O nome do arquivo varia com a idade do capítulo: os novos usam
        # page_001.webp e os antigos 001.webp — prefixo, zero-padding e
        # extensão são deduzidos do exemplo encontrado no HTML.
        m = re.search(
            r"https://cdn\.mugiverso\.com/mugiwarasoficial/"
            r"(manga_[a-z0-9]+)/([a-f0-9]+)/((?:page_)?)(\d+)\.(webp|jpe?g|png)",
            html,
            re.I,
        )
        if not m:
            # Fallback: capítulos podem ter as <img> direto no HTML
            imgs = re.findall(
                r'<img[^>]+class="wp-manga-chapter-img[^"]*"[^>]*'
                r'(?:data-src|src)="\s*([^"]+?)\s*"',
                html,
            )
            print(f"[Mugiwaras] {len(imgs)} página(s) no HTML.")
            return imgs

        base = (f"https://cdn.mugiverso.com/mugiwarasoficial/"
                f"{m.group(1)}/{m.group(2)}")
        prefixo, digitos, ext = m.group(3), len(m.group(4)), m.group(5)

        # Descobre a última página com HEADs (busca binária; ~10 requisições)
        def pagina(n):
            return f"{base}/{prefixo}{n:0{digitos}d}.{ext}"

        lo, hi = 1, 32
        while self._existe(pagina(hi)) and hi < 1024:
            lo, hi = hi, hi * 2
        while lo + 1 < hi:
            meio = (lo + hi) // 2
            if self._existe(pagina(meio)):
                lo = meio
            else:
                hi = meio

        print(f"[Mugiwaras] {lo} página(s) encontrada(s).")
        return [pagina(n) for n in range(1, lo + 1)]
