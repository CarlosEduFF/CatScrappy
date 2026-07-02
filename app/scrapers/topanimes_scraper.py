# app/scrapers/topanimes_scraper.py

import html as html_lib
import json
import re
import time
import urllib.parse
from app.models.anime import Episodio
from app.scrapers.base_scraper import DooPlayScraper


class TopAnimesScraper(DooPlayScraper):
    """Scraper do topanimes.net (tema DooPlay).

    O site expõe tudo via HTTP simples. O player usa um embed "sk-api" que,
    chamado com &mode=api2, devolve JSON com streams HLS (.m3u8) por
    qualidade. O VLC reproduz HLS nativamente; o download é feito via yt-dlp.
    A busca vem pronta da DooPlayScraper.
    """

    base_url = "https://topanimes.net"

    # ------------------------------------------------------------------
    # 2. EPISÓDIOS — lista no HTML (ul.episodios, aspas simples)
    # ------------------------------------------------------------------
    def listar_episodios(self, url_anime: str) -> list:
        print("[HTTP] Carregando lista de episódios...")
        html = self._http_get(url_anime)

        episodios = []
        for item in re.finditer(
            r"class='epnumber'>([^<]+)</div>\s*"
            r"<a title='([^']*)' href='([^']+)'",
            html,
        ):
            numero, titulo, link = item.group(1), item.group(2), item.group(3)
            titulo = html_lib.unescape(titulo).replace(" Online", "").strip()
            episodios.append(Episodio(
                titulo=titulo or f"Episódio {numero}",
                url_pagina=link,
                numero=numero,
            ))

        if not episodios:
            # Filmes não têm lista: a própria página é o "episódio"
            episodios.append(Episodio(titulo="Filme completo", url_pagina=url_anime, numero="1"))

        self._ordenar_por_numero(episodios)

        print(f"[HTTP] {len(episodios)} episódio(s) encontrado(s).")
        return episodios

    # ------------------------------------------------------------------
    # 3. VÍDEO — admin-ajax -> embed sk-api -> &mode=api2 -> m3u8
    # ------------------------------------------------------------------
    def extrair_url_video(self, url_episodio: str) -> str:
        print("[HTTP] Localizando players do episódio...")
        html = self._http_get(url_episodio)

        post_m = re.search(r"data-post=['\"](\d+)['\"]", html)
        if not post_m:
            print("[HTTP] Nenhum player encontrado nesta página.")
            return None
        post_id = post_m.group(1)

        numes = re.findall(r"data-nume=['\"](\d+)['\"]", html)
        numes = sorted(set(numes) | {"1"}, key=int)
        tipo_m = re.search(r"data-type=['\"](\w+)['\"]", html)
        tipo = tipo_m.group(1) if tipo_m else "tv"

        for nume in numes:
            dados = None
            for tentativa in range(3):
                try:
                    raw = self._http_post(
                        f"{self.base_url}/wp-admin/admin-ajax.php",
                        {"action": "doo_player_ajax", "post": post_id,
                         "nume": nume, "type": tipo},
                        referer=url_episodio,
                    )
                    dados = json.loads(raw)
                    break
                except Exception as e:
                    print(f"[HTTP] Player {nume}: erro na API ({e})")
                    time.sleep(1)
            if not dados:
                continue

            embed = str(dados.get("embed_url") or "")
            if not embed.startswith("http"):
                print(f"[HTTP] Player {nume}: resposta sem URL de vídeo.")
                continue

            url_video = self._resolver_embed(embed, nume)
            if url_video:
                return url_video

        print("[HTTP] Nenhum player com vídeo disponível para este episódio.")
        return None

    def _resolver_embed(self, embed: str, nume: str) -> str:
        """Converte a URL do embed na URL real do stream."""
        # Página "aviso" do próprio site: o embed real vem no parâmetro ?url=
        if "/aviso/" in embed:
            destino = urllib.parse.parse_qs(
                urllib.parse.urlparse(embed).query).get("url", [None])[0]
            if destino and destino.startswith("http"):
                embed = destino

        # Player "sk-api": a mesma URL com &mode=api2 devolve JSON com os streams
        if "sk-api" in embed or "alibabacdn" in embed:
            sep = "&" if "?" in embed else "?"
            try:
                corpo = self._http_get(embed + sep + "mode=api2",
                                       referer=self.base_url + "/")
            except Exception as e:
                print(f"[HTTP] Player {nume}: falha no embed ({e}).")
                return None

            try:
                dados = json.loads(corpo)
            except ValueError:
                # Alguns títulos respondem uma página jwplayer em vez do JSON;
                # se o arquivo estiver vazio, o site desativou este player.
                return self._extrair_arquivo_html(corpo, nume)

            midias = dados.get("midias") or []
            if dados.get("status") != "success" or not midias:
                print(f"[HTTP] Player {nume}: embed sem mídias.")
                return None

            # Qualidades do site: SD=1080p, LD=720p, FD=360p (melhor primeiro)
            peso = {"SD": 3, "LD": 2, "FD": 1}
            midias.sort(key=lambda m: peso.get(str(m.get("qualidade", "")).upper(), 0),
                        reverse=True)
            url = midias[0].get("url")
            if url:
                print(f"[HTTP] Player {nume}: stream {midias[0].get('qualidade')} disponível.")
                return url
            return None

        # Player jwplayer com arquivo direto (mesmo padrão do AnimesDrive)
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(embed).query)
        fonte = qs.get("source", [None])[0]
        if fonte and fonte.startswith("http"):
            print(f"[HTTP] Player {nume}: arquivo direto disponível.")
            return urllib.parse.quote(urllib.parse.unquote(fonte), safe=":/?&=")

        # Último recurso: baixa o embed e procura o arquivo no próprio HTML
        # (ex.: csst.online, que usa o player "Playerjs")
        try:
            corpo = self._http_get(embed, referer=self.base_url + "/")
        except Exception as e:
            print(f"[HTTP] Player {nume}: falha no embed ({e}).")
            return None
        return self._extrair_arquivo_html(corpo, nume)

    def _extrair_arquivo_html(self, corpo: str, nume: str) -> str:
        """Procura o arquivo de vídeo no HTML de um player (Playerjs/jwplayer).

        Aceita tanto file:"http..." quanto a lista por qualidade do Playerjs,
        no formato file:"[360p]url,[720p]url,[1080p]url".
        """
        fontes_m = re.search(r'file"?\s*:\s*"([^"]+)"', corpo)
        if not fontes_m:
            print(f"[HTTP] Player {nume}: é um embed sem stream conhecido, pulando.")
            return None
        fontes = fontes_m.group(1)

        qualidades = [(int(m.group(1)), m.group(2)) for m in
                      re.finditer(r'\[(\d+)p?\](https?://[^,"\s]+)', fontes)]
        if qualidades:
            qualidade, url = max(qualidades)
            print(f"[HTTP] Player {nume}: stream {qualidade}p disponível.")
            return url

        if fontes.startswith("http"):
            print(f"[HTTP] Player {nume}: arquivo direto disponível.")
            return fontes

        print(f"[HTTP] Player {nume}: é um embed sem stream conhecido, pulando.")
        return None
