# app/scrapers/base_scraper.py

import html as html_lib
import re
import urllib.parse
import urllib.request
from app.models.anime import Anime

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# Alguns sites (Cloudflare/WAF) checam headers que um browser real sempre
# manda e que uma requisição HTTP simples costuma omitir. Não resolve
# bloqueio por reputação de IP, mas ajuda contra checagens mais leves.
HEADERS_NAVEGADOR = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


class BaseScraper:
    """Contrato comum dos scrapers de anime.

    Toda subclasse implementa buscar_anime, listar_episodios e
    extrair_url_video. Sites cujo player não entrega link direto (só dá
    para assistir no navegador) marcam reproduz_no_navegador = True.
    """

    reproduz_no_navegador = False
    base_url = ""

    # ------------------------------------------------------------------
    # Contrato
    # ------------------------------------------------------------------
    def buscar_anime(self, nome_anime: str) -> list:
        """Retorna uma lista de Anime para o termo pesquisado."""
        raise NotImplementedError

    def listar_episodios(self, url_anime: str) -> list:
        """Retorna a lista de Episodio de um anime."""
        raise NotImplementedError

    def extrair_url_video(self, url_episodio: str) -> str:
        """Retorna a URL direta do vídeo (mp4/m3u8) ou None."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Helpers HTTP compartilhados
    # ------------------------------------------------------------------
    def _http_get(self, url: str, referer: str = None) -> str:
        headers = {"User-Agent": UA, **HEADERS_NAVEGADOR}
        if referer:
            headers["Referer"] = referer
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", "ignore")

    def _http_post(self, url: str, campos: dict, referer: str = None) -> str:
        headers = {
            "User-Agent": UA,
            **HEADERS_NAVEGADOR,
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }
        if referer:
            headers["Referer"] = referer
        data = urllib.parse.urlencode(campos).encode()
        req = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", "ignore")

    @staticmethod
    def _ordenar_por_numero(episodios: list) -> list:
        """Ordena numericamente (há especiais tipo "1022.5")."""
        def chave(ep):
            try:
                return float(ep.numero)
            except ValueError:
                return float("inf")
        episodios.sort(key=chave)
        return episodios


class DooPlayScraper(BaseScraper):
    """Base para sites com o tema WordPress DooPlay.

    Nesses sites a busca (?s=) devolve os resultados direto no HTML,
    em blocos <div class="result-item">.
    """

    def buscar_anime(self, nome_anime: str) -> list:
        url = f"{self.base_url}/?s={urllib.parse.quote_plus(nome_anime)}"
        print(f"[HTTP] Buscando: {url}")
        html = self._http_get(url)

        animes = []
        for bloco in html.split('class="result-item"')[1:]:
            titulo_m = re.search(r'<div class="title"><a href="([^"]+)">([^<]+)</a>', bloco)
            if not titulo_m:
                continue
            ano_m = re.search(r'class="year">([^<]*)<', bloco)
            animes.append(Anime(
                titulo=html_lib.unescape(titulo_m.group(2).strip()),
                url_detalhes=titulo_m.group(1),
                ano=ano_m.group(1).strip() if ano_m else "",
                imagem=self._extrair_imagem(bloco),
                sinopse=self._extrair_sinopse(bloco),
            ))
        print(f"[HTTP] {len(animes)} resultado(s) encontrado(s).")
        return animes

    @staticmethod
    def _extrair_imagem(bloco: str) -> str:
        """Capa do resultado, em resolução melhor quando possível.

        O TMDB serve tamanhos por URL (/t/p/w92/ -> /t/p/w300/); o WordPress
        anexa -LARGxALT ao nome do arquivo do thumbnail, e o original fica
        sem o sufixo.
        """
        img_m = re.search(r'<img[^>]+(?:data-src|src)="([^"]+)"', bloco)
        if not img_m:
            return ""
        imagem = img_m.group(1)
        imagem = re.sub(r"(image\.tmdb\.org/t/p)/w\d+/", r"\1/w300/", imagem)
        imagem = re.sub(r"-\d+x\d+(\.\w+)$", r"\1", imagem)
        return imagem

    @staticmethod
    def _extrair_sinopse(bloco: str) -> str:
        sinopse_m = re.search(r'class="contenido"><p>(.*?)</p>', bloco, re.S)
        if not sinopse_m:
            return ""
        texto = re.sub(r"<[^>]+>", "", sinopse_m.group(1))
        return html_lib.unescape(texto).strip()
