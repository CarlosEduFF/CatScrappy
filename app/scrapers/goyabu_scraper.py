# app/scrapers/goyabu_scraper.py

import asyncio
import base64
import json
import re
from playwright.async_api import async_playwright
from app.models.anime import Anime, Episodio
from app.scrapers.base_scraper import UA, BaseScraper


class GoyabuScraper(BaseScraper):
    # O player do Goyabu (Blogger) é protegido contra automação e não abre no
    # VLC; os episódios são assistidos abrindo a página no navegador.
    reproduz_no_navegador = True

    base_url = "https://goyabu.io"

    async def _abrir_navegador(self, p):
        """Cria um browser/contexto configurado para passar pela proteção anti-bot."""
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = await browser.new_context(user_agent=UA, locale="pt-BR")
        page = await ctx.new_page()
        await page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        return browser, page

    # ------------------------------------------------------------------
    # 1. BUSCA — usa a API JSON interna do site (wp-json/animeonline/search)
    # ------------------------------------------------------------------
    def buscar_anime(self, nome_anime: str) -> list:
        return asyncio.run(self._buscar_anime_async(nome_anime))

    async def _buscar_anime_async(self, nome_anime: str) -> list:
        print("[Browser] Abrindo navegador headless...")
        async with async_playwright() as p:
            browser, page = await self._abrir_navegador(p)
            try:
                print("[Browser] Acessando a página inicial...")
                await page.goto(f"{self.base_url}/inicio", timeout=60000,
                                wait_until="domcontentloaded")
                await page.wait_for_timeout(1500)

                print(f"[Browser] Buscando por '{nome_anime}'...")
                # A busca é feita por uma API JSON. O 'nonce' é lido de dentro da página.
                resultado = await page.evaluate(
                    """async (keyword) => {
                        let nonce = null;
                        for (const k of Object.keys(window)) {
                            try {
                                const v = window[k];
                                if (v && typeof v === 'object' && v.nonce) { nonce = v.nonce; break; }
                            } catch (e) {}
                        }
                        const url = '/wp-json/animeonline/search/?keyword='
                            + encodeURIComponent(keyword)
                            + (nonce ? '&nonce=' + nonce : '');
                        const r = await fetch(url, {headers: {'X-Requested-With': 'XMLHttpRequest'}});
                        if (!r.ok) return null;
                        return await r.text();
                    }""",
                    nome_anime,
                )
            finally:
                await browser.close()

        if not resultado:
            print("[Browser] Nenhuma resposta da busca.")
            return []

        try:
            dados = json.loads(resultado)
        except json.JSONDecodeError:
            print("[Browser] Resposta da busca não é um JSON válido.")
            return []

        animes = []
        # A API retorna um dict {id: {title, url, audio, year, ...}}
        for anime_id, info in dados.items():
            animes.append(Anime(
                titulo=info.get("title", "Sem título"),
                url_detalhes=info.get("url", ""),
                id=str(anime_id),
                audio=info.get("audio", ""),
                ano=str(info.get("year", "")),
            ))
        print(f"[Browser] {len(animes)} anime(s) encontrado(s).")
        return animes

    # ------------------------------------------------------------------
    # 2. EPISÓDIOS — extraídos da variável JS 'allEpisodes' embutida no HTML
    # ------------------------------------------------------------------
    def listar_episodios(self, url_anime: str) -> list:
        return asyncio.run(self._listar_episodios_async(url_anime))

    async def _listar_episodios_async(self, url_anime: str) -> list:
        print("[Browser] Carregando página do anime...")
        async with async_playwright() as p:
            browser, page = await self._abrir_navegador(p)
            try:
                await page.goto(url_anime, timeout=60000, wait_until="domcontentloaded")
                await page.wait_for_timeout(2000)
                html = await page.content()
            finally:
                await browser.close()

        # A lista de episódios vem numa variável JS: const allEpisodes = [ {...}, ... ];
        match = re.search(r"const allEpisodes\s*=\s*(\[.*?\]);", html, re.S)
        if not match:
            print("[Browser] Não foi possível localizar a lista de episódios.")
            return []

        try:
            lista = json.loads(match.group(1))
        except json.JSONDecodeError:
            print("[Browser] Lista de episódios em formato inesperado.")
            return []

        episodios = []
        for ep in lista:
            link = ep.get("link", "")
            if link.startswith("/"):
                link = self.base_url + link
            numero = str(ep.get("episodio", ""))
            nome = ep.get("episode_name", "") or f"Episódio {numero}"
            titulo = f"Episódio {numero} - {nome}" if numero else nome
            episodios.append(Episodio(titulo=titulo, url_pagina=link, numero=numero))

        print(f"[Browser] {len(episodios)} episódio(s) encontrado(s).")
        return episodios

    # ------------------------------------------------------------------
    # 3. VÍDEO — o player usa o Blogger; a URL vem cifrada (base64 + string invertida)
    # ------------------------------------------------------------------
    def extrair_url_video(self, url_episodio: str) -> str:
        return asyncio.run(self._extrair_url_video_async(url_episodio))

    async def _extrair_url_video_async(self, url_episodio: str) -> str:
        print("[Browser] Carregando página do episódio...")
        async with async_playwright() as p:
            browser, page = await self._abrir_navegador(p)
            try:
                await page.goto(url_episodio, timeout=60000, wait_until="domcontentloaded")
                await page.wait_for_timeout(2000)
                html = await page.content()
            finally:
                await browser.close()

        return self._extrair_url_blogger(html)

    def _extrair_url_blogger(self, html: str) -> str:
        """Descobre a URL do vídeo no Blogger a partir do HTML da página do episódio."""
        # Caminho A: token cifrado no botão do player (base64 -> string invertida)
        cifrado = re.search(r'data-blogger-url-encrypted="([^"]+)"', html)
        if cifrado:
            try:
                decodificado = base64.b64decode(cifrado.group(1)).decode("utf-8", "ignore")
                url = decodificado[::-1]  # engenharia reversa do strrev do PHP
                if url.startswith("http"):
                    return url
            except Exception:
                pass

        # Caminho B: URL em texto claro dentro de playersData
        players = re.search(r"var playersData\s*=\s*(\[.*?\]);", html, re.S)
        if players:
            try:
                dados = json.loads(players.group(1))
                for item in dados:
                    if item.get("select") == "blogger" and item.get("url", "").startswith("http"):
                        return item["url"]
            except json.JSONDecodeError:
                pass

        print("[Browser] Não foi possível extrair a URL do vídeo.")
        return None
