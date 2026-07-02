# app/scrapers/animesdrive_scraper.py

import html as html_lib
import json
import re
import time
import urllib.parse
import urllib.request
from app.models.anime import Anime, Episodio

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


class AnimesDriveScraper:
    """Scraper do animesdrive.online (tema DooPlay).

    O site não tem proteção anti-bot e expõe os vídeos como .mp4 direto
    através da API interna wp-json/dooplayer/v2, então tudo funciona com
    requisições HTTP simples — sem necessidade de navegador.
    """

    def __init__(self):
        self.base_url = "https://animesdrive.online"

    def _http_get(self, url: str, referer: str = None) -> str:
        headers = {"User-Agent": UA}
        if referer:
            headers["Referer"] = referer
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", "ignore")

    # ------------------------------------------------------------------
    # 1. BUSCA — a página ?s= retorna os resultados direto no HTML
    # ------------------------------------------------------------------
    def buscar_anime(self, nome_anime: str) -> list:
        url = f"{self.base_url}/?s={urllib.parse.quote_plus(nome_anime)}"
        print(f"[HTTP] Buscando: {url}")
        html = self._http_get(url)

        animes = []
        # Cada resultado fica num bloco <div class="result-item">
        for bloco in html.split('class="result-item"')[1:]:
            titulo_m = re.search(r'<div class="title"><a href="([^"]+)">([^<]+)</a>', bloco)
            if not titulo_m:
                continue
            ano_m = re.search(r'class="year">([^<]*)<', bloco)
            animes.append(Anime(
                titulo=html_lib.unescape(titulo_m.group(2).strip()),
                url_detalhes=titulo_m.group(1),
                ano=ano_m.group(1).strip() if ano_m else "",
            ))
        print(f"[HTTP] {len(animes)} resultado(s) encontrado(s).")
        return animes

    # ------------------------------------------------------------------
    # 2. EPISÓDIOS — a lista vem no HTML da página do anime (episode-card)
    # ------------------------------------------------------------------
    def listar_episodios(self, url_anime: str) -> list:
        print("[HTTP] Carregando lista de episódios...")
        html = self._http_get(url_anime)

        episodios = []
        for card in re.finditer(
            r"data-episode-number='([^']+)'\s+data-episode-title='([^']*)'>"
            r".*?href='([^']+)'",
            html,
        ):
            numero, titulo, link = card.group(1), card.group(2), card.group(3)
            episodios.append(Episodio(
                titulo=html_lib.unescape(titulo) or f"Episódio {numero}",
                url_pagina=link,
                numero=numero,
            ))

        if not episodios:
            # Filmes (/filme/) não têm lista: a própria página é o "episódio"
            episodios.append(Episodio(titulo="Filme completo", url_pagina=url_anime, numero="1"))

        # Ordena numericamente (há especiais tipo "1022.5")
        def chave(ep):
            try:
                return float(ep.numero)
            except ValueError:
                return float("inf")
        episodios.sort(key=chave)

        print(f"[HTTP] {len(episodios)} episódio(s) encontrado(s).")
        return episodios

    # ------------------------------------------------------------------
    # 3. VÍDEO — API dooplayer retorna a URL do .mp4 direto
    # ------------------------------------------------------------------
    def extrair_url_video(self, url_episodio: str) -> str:
        print("[HTTP] Localizando players do episódio...")
        html = self._http_get(url_episodio)

        post_m = re.search(r"data-post=['\"](\d+)['\"]", html)
        if not post_m:
            # A página pode ter chegado incompleta; tenta baixar de novo
            time.sleep(1)
            html = self._http_get(url_episodio)
            post_m = re.search(r"data-post=['\"](\d+)['\"]", html)
        if not post_m:
            print("[HTTP] Nenhum player encontrado nesta página.")
            return None
        post_id = post_m.group(1)

        # Junta os players anunciados na página com 1 e 2 (padrão do site).
        # A página às vezes chega truncada/incompleta e omite players que
        # existem — a API responde 404 inofensivo para os que não existirem.
        numes = re.findall(r"data-nume=['\"](\d+)['\"]", html)
        numes = sorted(set(numes) | {"1", "2"}, key=int)
        tipo = "movie" if "/filme/" in url_episodio else "tv"

        # Tenta cada player e devolve o primeiro cujo arquivo realmente existe.
        # Só retorna URL verificada: entregar link quebrado faz o VLC abrir e
        # fechar na hora, o que é pior do que avisar o usuário.
        for nume in numes:
            api = f"{self.base_url}/wp-json/dooplayer/v2/{post_id}/{tipo}/{nume}"
            dados = None
            # A API falha esporadicamente; insiste algumas vezes com pausa
            for tentativa in range(3):
                try:
                    dados = json.loads(self._http_get(api, referer=url_episodio))
                    break
                except Exception as e:
                    print(f"[HTTP] Player {nume}: erro na API ({e})")
                    time.sleep(1)
            if not dados:
                print(f"[HTTP] Player {nume}: API não respondeu, pulando.")
                continue

            # Players "iframe" são embeds externos (Blogger etc.), não arquivos
            # de vídeo — baixá-los renderia só o HTML da página do embed.
            if dados.get("type") == "iframe":
                print(f"[HTTP] Player {nume}: é um embed (sem arquivo direto), pulando.")
                continue

            embed = dados.get("embed_url") or ""
            # O embed é .../jwplayer?source=<url do mp4>&...
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(str(embed)).query)
            url_video = qs.get("source", [None])[0] or embed
            if not url_video or not str(url_video).startswith("http"):
                print(f"[HTTP] Player {nume}: resposta sem URL de vídeo.")
                continue

            # Normaliza a URL: o site ora codifica espaços como '+', ora como
            # %2520; decodifica tudo e re-codifica no formato padrão (%20)
            url_video = urllib.parse.quote(
                urllib.parse.unquote(str(url_video)), safe=":/?&="
            )

            # Confere o arquivo (com uma repetição, a checagem também pode oscilar)
            for _ in range(2):
                if self._video_disponivel(url_video):
                    print(f"[HTTP] Player {nume}: vídeo disponível.")
                    return url_video
                time.sleep(1)
            print(f"[HTTP] Player {nume}: arquivo indisponível, tentando o próximo...")

        print("[HTTP] Nenhum player com vídeo disponível para este episódio.")
        return None

    def _video_disponivel(self, url_video: str) -> bool:
        """Confere se a URL entrega vídeo de verdade (status E content-type).

        Só o status não basta: páginas HTML de embed/erro também respondem 200.
        """
        try:
            req = urllib.request.Request(
                url_video,
                headers={"User-Agent": UA, "Range": "bytes=0-0"},
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                if resp.status not in (200, 206):
                    return False
                tipo = (resp.headers.get("Content-Type") or "").lower()
                return tipo.startswith("video/") or "octet-stream" in tipo
        except Exception:
            return False
