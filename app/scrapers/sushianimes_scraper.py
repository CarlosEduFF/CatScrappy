# app/scrapers/sushianimes_scraper.py

import html as html_lib
import re
import time
import urllib.parse
from app.models.anime import Anime, Episodio
from app.scrapers.base_scraper import BaseScraper


class SushiAnimesScraper(BaseScraper):
    """Scraper do sushianimes.com.br.

    Tema próprio (não-DooPlay), mas tudo é acessível por HTTP simples:
    - busca em /search/<termo> (cards .list-movie);
    - episódios na página do anime, em links .../<slug>-<season>-season-<n>-episode;
    - a página do episódio traz um data-embed=<id>; um POST em /ajax/embed com
      esse id devolve o HTML do jwplayer, de onde sai o stream HLS (.m3u8).
    O stream toca direto no player (HLS), sem precisar do /proxy.
    """

    base_url = "https://sushianimes.com.br"

    # ------------------------------------------------------------------
    # 1. BUSCA — /search/<termo> devolve cards .list-movie
    # ------------------------------------------------------------------
    def buscar_anime(self, nome_anime: str) -> list:
        url = f"{self.base_url}/search/{urllib.parse.quote(nome_anime)}"
        print(f"[HTTP] Buscando: {url}")
        html = self._http_get(url)

        animes = []
        vistos = set()
        # Cada resultado é um <a class="list-media"> com a capa em data-src,
        # seguido de <a class="list-title"> com o título (inclui "(Dublado)").
        for card in re.finditer(
            r'<a href="([^"]+)" class="list-media">.*?'
            r'data-src="([^"]+)".*?'
            r'<a href="[^"]+" class="list-title">([^<]+)</a>',
            html,
            re.S,
        ):
            link, imagem, titulo_bruto = card.group(1), card.group(2), card.group(3)
            if link in vistos:  # a busca repete o mesmo anime em blocos diferentes
                continue
            vistos.add(link)
            titulo_bruto = html_lib.unescape(titulo_bruto).strip()
            audio_m = re.search(r"\((Dublado|Legendado)\)", titulo_bruto)
            audio = audio_m.group(1) if audio_m else ""
            titulo = re.sub(r"\s*\((?:Dublado|Legendado)\)", "", titulo_bruto).strip()
            animes.append(Anime(
                titulo=titulo,
                url_detalhes=link,
                audio=audio,
                imagem=imagem,
            ))
        print(f"[HTTP] {len(animes)} resultado(s) encontrado(s).")
        return animes

    # ------------------------------------------------------------------
    # 2. EPISÓDIOS — links .../-season-<n>-episode na página do anime
    # ------------------------------------------------------------------
    def listar_episodios(self, url_anime: str) -> list:
        print("[HTTP] Carregando lista de episódios...")
        html = self._http_get(url_anime)

        episodios = []
        for item in re.finditer(
            r'<a href="(' + re.escape(self.base_url) + r'/anime/[^"]*-season-\d+-episode)"'
            r'[^>]*aria-label="Assistir epis[^"]*?(\d+)[^"]*"',
            html,
        ):
            link, numero = item.group(1), item.group(2)
            episodios.append(Episodio(
                titulo=f"Episódio {numero}",
                url_pagina=link,
                numero=numero,
            ))

        if not episodios:
            # Filmes / OVAs sem lista: a própria página é o "episódio".
            episodios.append(Episodio(titulo="Filme completo", url_pagina=url_anime, numero="1"))

        self._ordenar_por_numero(episodios)

        print(f"[HTTP] {len(episodios)} episódio(s) encontrado(s).")
        return episodios

    # ------------------------------------------------------------------
    # 3. VÍDEO — data-embed=<id> -> POST /ajax/embed -> HLS no jwplayer
    # ------------------------------------------------------------------
    def extrair_url_video(self, url_episodio: str) -> str:
        print("[HTTP] Localizando players do episódio...")
        html = self._http_get(url_episodio)

        # Cada botão de player carrega um data-embed com o id do mirror.
        embed_ids = re.findall(r'data-embed="(\d+)"', html)
        if not embed_ids:
            print("[HTTP] Nenhum player encontrado nesta página.")
            return None

        for embed_id in dict.fromkeys(embed_ids):
            corpo = None
            for tentativa in range(3):
                try:
                    corpo = self._http_post(
                        f"{self.base_url}/ajax/embed",
                        {"id": embed_id},
                        referer=url_episodio,
                    )
                    break
                except Exception as e:
                    print(f"[HTTP] Player {embed_id}: erro no /ajax/embed ({e})")
                    time.sleep(1)
            if not corpo:
                continue

            url_video = self._extrair_stream(corpo)
            if url_video:
                print(f"[HTTP] Player {embed_id}: stream disponível.")
                return url_video
            print(f"[HTTP] Player {embed_id}: sem stream, tentando o próximo...")

        print("[HTTP] Nenhum player com vídeo disponível para este episódio.")
        return None

    @staticmethod
    def _extrair_stream(corpo: str) -> str:
        """Pega a URL do stream (HLS/mp4) no HTML do jwplayer.

        O setup do jwplayer traz a URL num file/source; procura a primeira
        URL .m3u8 (preferida) ou .mp4 no corpo. Para a URL no primeiro
        caractere que não pode fazer parte dela (aspas, espaço, ';' etc.),
        senão captura o código JS que vem logo depois (ex.: '";var ...').
        """
        m = re.search(r'https?://[^\s"\'<>\\);]+\.m3u8[^\s"\'<>\\);]*', corpo) or \
            re.search(r'https?://[^\s"\'<>\\);]+\.mp4[^\s"\'<>\\);]*', corpo)
        if not m:
            return None
        return m.group(0)
