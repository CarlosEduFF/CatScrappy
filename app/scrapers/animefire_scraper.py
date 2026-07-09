# app/scrapers/animefire_scraper.py

import html as html_lib
import json
import re
import time
import urllib.parse
from app.models.anime import Anime, Episodio
from app.scrapers.base_scraper import BaseScraper


class AnimeFireScraper(BaseScraper):
    """Scraper do animefire.io.

    O site expõe tudo via HTTP simples, sem proteção anti-bot. Os vídeos
    ficam num endpoint JSON interno (/video/<slug>/<n>) que devolve URLs de
    .mp4 direto por qualidade. Os arquivos são servidos pelo lightspeedst.net,
    que exige o Referer do site — por isso extrair_url_video devolve a URL já
    com o referer embutido (ver referer_do_video), para o /proxy repassá-lo.
    """

    base_url = "https://animefire.io"

    # O host de vídeo (lightspeedst.net) recusa (401) requisições sem este
    # Referer; o /proxy da API precisa reenviá-lo ao buscar o arquivo.
    referer_do_video = "https://animefire.io/"

    # ------------------------------------------------------------------
    # 1. BUSCA — /pesquisar/<termo> devolve cards no HTML
    # ------------------------------------------------------------------
    def buscar_anime(self, nome_anime: str) -> list:
        # O /pesquisar/ espera os espaços como hífen (ex.: "boruto-naruto");
        # %20 ou '+' devolvem 404. Colapsa espaços e normaliza para hífens.
        termo = re.sub(r"\s+", "-", nome_anime.strip())
        url = f"{self.base_url}/pesquisar/{urllib.parse.quote(termo)}"
        print(f"[HTTP] Buscando: {url}")
        html = self._http_get(url)

        animes = []
        # Cada resultado é um .divCardUltimosEps com o título limpo no atributo
        # 'title', seguido do link do anime e da capa em data-src (lazy-load).
        for card in re.finditer(
            r'divCardUltimosEps" title="([^"]*)">.*?'
            r'<a href="([^"]+)">.*?data-src="([^"]+)"',
            html,
            re.S,
        ):
            titulo_bruto, link, imagem = card.group(1), card.group(2), card.group(3)
            titulo_bruto = html_lib.unescape(titulo_bruto)
            # O título vem como "Nome (Dublado) - Episódio X" ou "... - Filme";
            # separa o áudio e descarta o sufixo do tipo/episódio.
            audio_m = re.search(r"\((Dublado|Legendado)\)", titulo_bruto)
            audio = audio_m.group(1) if audio_m else ""
            titulo = re.sub(r"\s*\((?:Dublado|Legendado)\)", "", titulo_bruto)
            titulo = titulo.split(" - ")[0].strip()
            animes.append(Anime(
                titulo=titulo,
                url_detalhes=link,
                audio=audio,
                imagem=imagem,
            ))
        print(f"[HTTP] {len(animes)} resultado(s) encontrado(s).")
        return animes

    # ------------------------------------------------------------------
    # 2. EPISÓDIOS — lista no HTML da página do anime (a.lEp)
    # ------------------------------------------------------------------
    def listar_episodios(self, url_anime: str) -> list:
        print("[HTTP] Carregando lista de episódios...")
        html = self._http_get(url_anime)

        episodios = []
        for item in re.finditer(
            r'<a class="lEp[^"]*" href="([^"]+)">([^<]+)</a>',
            html,
        ):
            link, titulo = item.group(1), html_lib.unescape(item.group(2)).strip()
            # O número do episódio é o último segmento da URL (.../<slug>/<n>).
            numero_m = re.search(r"/(\d+)/?$", link)
            numero = numero_m.group(1) if numero_m else ""
            episodios.append(Episodio(
                titulo=titulo or f"Episódio {numero}",
                url_pagina=link,
                numero=numero,
            ))

        if not episodios:
            # Filmes não têm lista: a própria página é o "episódio".
            episodios.append(Episodio(titulo="Filme completo", url_pagina=url_anime, numero="1"))

        self._ordenar_por_numero(episodios)

        print(f"[HTTP] {len(episodios)} episódio(s) encontrado(s).")
        return episodios

    # ------------------------------------------------------------------
    # 3. VÍDEO — data-video-src aponta pra /video/<slug>/<n> (JSON de .mp4)
    # ------------------------------------------------------------------
    def extrair_url_video(self, url_episodio: str) -> str:
        print("[HTTP] Localizando o vídeo do episódio...")
        html = self._http_get(url_episodio)

        api_m = re.search(r'data-video-src="([^"]+)"', html)
        if not api_m:
            print("[HTTP] Nenhum player encontrado nesta página.")
            return None
        api_url = html_lib.unescape(api_m.group(1))
        if api_url.startswith("/"):
            api_url = self.base_url + api_url

        # A API oscila às vezes; insiste algumas vezes com pausa.
        dados = None
        for tentativa in range(3):
            try:
                raw = self._http_get(api_url, referer=url_episodio)
                dados = json.loads(raw)
                break
            except Exception as e:
                print(f"[HTTP] Erro na API de vídeo ({e})")
                time.sleep(1)
        if not dados:
            print("[HTTP] A API de vídeo não respondeu.")
            return None

        # A API responde {"data": [{"src": "...mp4", "label": "360p"}, ...]},
        # com as qualidades em ordem crescente (a melhor é a última).
        fontes = [f for f in dados.get("data", []) if f.get("src", "").startswith("http")]
        if not fontes:
            print("[HTTP] Resposta sem URL de vídeo.")
            return None

        fontes.sort(key=lambda f: self._peso_qualidade(f.get("label", "")))
        melhor = fontes[-1]
        print(f"[HTTP] Vídeo {melhor.get('label', '?')} disponível.")
        return melhor["src"]

    @staticmethod
    def _peso_qualidade(label: str) -> int:
        """Extrai o número da qualidade (ex.: '1080p' -> 1080) para ordenar."""
        m = re.search(r"(\d+)", str(label))
        return int(m.group(1)) if m else 0
