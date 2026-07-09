# app/scrapers/mangalivre_scraper.py

import html as html_lib
import re
import urllib.parse
import urllib.request

from app.scrapers.mangadex_scraper import Capitulo, Manga

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


class MangaLivreScraper:
    """Scraper do mangalivre.blog (WordPress com tema próprio, pt-br).

    Tudo é acessível por HTTP simples, sem AJAX nem Cloudflare:
    - busca em /pesquisar/<termo> (cards .manga-card);
    - a página do mangá já traz a lista completa de capítulos no HTML
      (li.chapter-item -> a.chapter-link + span.chapter-number);
    - a página do capítulo traz as imagens (img.chapter-image) já na ordem
      de leitura, servidas do próprio /wp-content/uploads.
    """

    base_url = "https://mangalivre.blog"

    def _http_get(self, url: str) -> str:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", "ignore")

    # ------------------------------------------------------------------
    # 1. BUSCA de mangás
    # ------------------------------------------------------------------
    def buscar_manga(self, titulo: str) -> list:
        # A busca espera os espaços como hífen (ex.: "jujutsu-kaisen");
        # %20 devolve 404. Colapsa espaços e normaliza para hífens.
        # Usa a busca nativa do WordPress (?s=), que é fuzzy — casa por
        # substring, não pelo slug exato. Devolve cards .manga-card sem
        # redirecionar mesmo em match exato.
        url = f"{self.base_url}/?s={urllib.parse.quote_plus(titulo.strip())}"
        print(f"[MangaLivre] Buscando: {url}")
        html = self._http_get(url)

        mangas = []
        for card in re.finditer(
            r'<div class="manga-card">\s*<a href="([^"]+)"[^>]*>.*?'
            r'<img[^>]+src="([^"]+)".*?'
            r'<h3 class="manga-card-title">([^<]+)</h3>',
            html,
            re.S,
        ):
            link, imagem, titulo_c = card.group(1), card.group(2), card.group(3)
            mangas.append(Manga(
                id=link,  # a própria URL do mangá
                titulo=html_lib.unescape(titulo_c.strip()),
                imagem=imagem,
                sinopse="",  # a busca não traz sinopse
            ))
        print(f"[MangaLivre] {len(mangas)} resultado(s) encontrado(s).")
        return mangas

    # ------------------------------------------------------------------
    # 2. CAPÍTULOS (o site é só pt-br; o parâmetro idioma é ignorado)
    # ------------------------------------------------------------------
    def listar_capitulos(self, manga_url: str, idioma: str = None) -> list:
        print("[MangaLivre] Carregando capítulos...")
        html = self._http_get(manga_url)

        capitulos = []
        vistos = set()
        for item in re.finditer(
            r'<li class="chapter-item">.*?'
            r'<a href="([^"]+)" class="chapter-link">\s*'
            r'<span class="chapter-number">\s*([^<]+?)\s*</span>',
            html,
            re.S,
        ):
            link = item.group(1)
            if link in vistos:  # o item repete o link no botão "Ler"
                continue
            vistos.add(link)
            texto = html_lib.unescape(item.group(2).strip())
            num_m = re.search(r"(\d+(?:\.\d+)?)", texto)
            capitulos.append(Capitulo(
                id=link,  # a própria URL do capítulo
                numero=num_m.group(1) if num_m else "?",
                titulo="",
                paginas=0,  # a lista não expõe a contagem
                idioma="pt-br",
            ))

        # A página lista do mais novo para o mais antigo; ordena crescente.
        def chave(cap):
            try:
                return float(cap.numero)
            except (ValueError, TypeError):
                return float("inf")
        capitulos.sort(key=chave)

        print(f"[MangaLivre] {len(capitulos)} capítulo(s) encontrado(s).")
        return capitulos

    # ------------------------------------------------------------------
    # 3. URLs das PÁGINAS de um capítulo
    # ------------------------------------------------------------------
    def obter_paginas(self, capitulo_url: str) -> list:
        print("[MangaLivre] Localizando páginas do capítulo...")
        html = self._http_get(capitulo_url)

        # As páginas ficam em <img class="chapter-image"> dentro do bloco
        # .chapter-images, já na ordem de leitura.
        paginas = re.findall(
            r'<img[^>]+src="([^"]+)"[^>]*class="chapter-image"',
            html,
        )
        if not paginas:
            # Fallback: alguns capítulos usam data-src (lazy) ou ordem de
            # atributos diferente; pega imagens de /wp-content/uploads.
            paginas = re.findall(
                r'(?:data-src|src)="(https://mangalivre\.blog/wp-content/'
                r'uploads/\d+/\d+/[^"]+\.(?:webp|jpe?g|png))"',
                html,
            )

        print(f"[MangaLivre] {len(paginas)} página(s) encontrada(s).")
        return paginas
