# app/cli/menus.py

import sys
import time
import questionary
# Importamos nossos scrapers e player (ajuste os caminhos conforme sua estrutura)
from app.scrapers.animesdrive_scraper import AnimesDriveScraper
from app.scrapers.topanimes_scraper import TopAnimesScraper
from app.scrapers.goyabu_scraper import GoyabuScraper
from app.player.vlc_wrapper import VLCWrapper
from app.player.browser_wrapper import BrowserWrapper
from app.player.downloader import Downloader

# Sites disponíveis: rótulo do menu -> classe do scraper
SITES = {
    "AnimesDrive (assiste no VLC)": AnimesDriveScraper,
    "TopAnimes (assiste no VLC)": TopAnimesScraper,
    "Goyabu (assiste no Chrome)": GoyabuScraper,
}

class AnimeInterface:
    def __init__(self):
        # O scraper é definido pelo menu de escolha de site
        self.scraper = None
        self.player = VLCWrapper()
        self.navegador = BrowserWrapper()
        self.downloader = Downloader()

    def menu_escolher_site(self):
        """Pergunta em qual site o usuário quer buscar os animes."""
        opcoes = list(SITES.keys()) + ["❌ Sair"]
        escolha = questionary.select(
            "Em qual site deseja buscar?",
            choices=opcoes
        ).ask()

        if escolha is None or escolha == "❌ Sair":
            print("\nSaindo do programa. Até logo!")
            sys.exit(0)

        self.scraper = SITES[escolha]()

    def exibir_cabecalho(self):
        """Limpa a tela e exibe o título do programa."""
        # Envia um comando para limpar o terminal (funciona em Windows, Linux e Mac)
        print("\033[H\033[J", end="") 
        print("=" * 50)
        print("          ANIME CLI STREAMER v1.0          ")
        print("=" * 50 + "\n")

    def menu_buscar_anime(self) -> str:
        """Pede ao usuário o nome do anime para pesquisa."""
        nome_busca = questionary.text(
            "Digite o nome do anime que deseja buscar (ou deixe em branco para trocar de site):"
        ).ask()

        if not nome_busca or nome_busca.strip() == "":
            return None  # Volta para a escolha de site

        return nome_busca.strip()

    def menu_selecionar_anime(self, animes_encontrados: list):
        """Exibe a lista de animes encontrados para o usuário escolher."""
        if not animes_encontrados:
            questionary.print("Nenhum anime encontrado com esse nome.", style="bold italic fg:red")
            return None

        # Cria uma lista apenas com os títulos para exibir no menu
        opcoes = [anime.titulo for anime in animes_encontrados]
        opcoes.append("⬅️ Voltar para a Busca")

        escolha = questionary.select(
            "Selecione o anime desejado:",
            choices=opcoes
        ).ask()

        if escolha == "⬅️ Voltar para a Busca":
            return None

        # Encontra o objeto 'Anime' correspondente à escolha do usuário
        anime_selecionado = next(a for a in animes_encontrados if a.titulo == escolha)
        return anime_selecionado

    def menu_selecionar_episodio(self, episodios: list):
        """Exibe a lista de episódios do anime selecionado."""
        if not episodios:
            questionary.print("Nenhum episódio encontrado para este anime.", style="bold italic fg:red")
            return None

        # Cria a lista de opções para o menu
        opcoes = [ep.titulo for ep in episodios]
        opcoes.append("⬅️ Voltar para a Seleção de Anime")

        escolha = questionary.select(
            "Selecione o episódio para assistir:",
            choices=opcoes
        ).ask()

        if escolha == "⬅️ Voltar para a Seleção de Anime":
            return None

        # Encontra o objeto 'Episodio' correspondente
        episodio_selecionado = next(e for e in episodios if e.titulo == escolha)
        return episodio_selecionado

    def iniciar(self):
        """Fluxo principal que controla a navegação entre os menus."""
        while True:
            self.exibir_cabecalho()

            # 0. Escolha do site (também acessível deixando a busca em branco)
            if self.scraper is None:
                self.menu_escolher_site()
                self.exibir_cabecalho()

            # 1. Tela de Busca
            nome_busca = self.menu_buscar_anime()
            if nome_busca is None:
                self.scraper = None  # Reabre a escolha de site
                continue

            print(f"\n[Scraper] Buscando por '{nome_busca}' no site...")
            animes = self.scraper.buscar_anime(nome_busca)
            
            # 2. Tela de Seleção do Anime
            self.exibir_cabecalho()
            anime_escolhido = self.menu_selecionar_anime(animes)
            if not anime_escolhido:
                continue # Volta para o início do laço (Busca)

            # 3. Carregamento e Tela de Episódios
            print(f"\n[Scraper] Carregando episódios de '{anime_escolhido.titulo}'...")
            episodios = self.scraper.listar_episodios(anime_escolhido.url_detalhes)
            
            while True:
                self.exibir_cabecalho()
                print(f"Anime Atual: {anime_escolhido.titulo}\n")
                ep_escolhido = self.menu_selecionar_episodio(episodios)
                
                if not ep_escolhido:
                    break # Sai deste laço interno e volta para a seleção de animes

                # 4. Reprodução: navegador (sites protegidos) ou VLC (link direto)
                if getattr(self.scraper, "reproduz_no_navegador", False):
                    self.navegador.abrir(ep_escolhido.url_pagina)
                    continue  # Volta para a lista de episódios

                # 4a. Escolha da ação (assistir ou baixar)
                acao = questionary.select(
                    f"O que deseja fazer com '{ep_escolhido.titulo}'?",
                    choices=["▶️ Assistir no VLC", "⬇️ Baixar episódio", "⬅️ Voltar"]
                ).ask()

                if acao is None or acao == "⬅️ Voltar":
                    continue

                # 4b. Extração do link direto do vídeo
                print(f"\n[Scraper] Extraindo link de vídeo para: {ep_escolhido.titulo}...")
                url_video = self.scraper.extrair_url_video(ep_escolhido.url_pagina)

                if not url_video:
                    print("[Erro] Não foi possível extrair o vídeo deste episódio.")
                    input("\nPressione Enter para continuar...")
                    continue

                if acao == "▶️ Assistir no VLC":
                    print("[Player] Abrindo o VLC... Divirta-se!")
                    self.player.reproduzir(url_video)
                else:
                    resultado = self.downloader.baixar(
                        url_video, anime_escolhido.titulo, ep_escolhido.titulo
                    )
                    if resultado:
                        # Pausa breve para ler a confirmação e volta aos episódios
                        time.sleep(1.5)
                    else:
                        input("\nPressione Enter para continuar...")