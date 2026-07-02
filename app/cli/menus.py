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
        """Exibe a lista de episódios. Retorna uma tupla (acao, dados):

        - ("episodio", Episodio)  -> um episódio único escolhido
        - ("baixar_todos", None)  -> baixar a temporada inteira
        - ("baixar_intervalo", None) -> baixar um trecho (pergunta depois)
        - ("voltar", None)        -> voltar para a seleção de anime
        """
        if not episodios:
            questionary.print("Nenhum episódio encontrado para este anime.", style="bold italic fg:red")
            return ("voltar", None)

        BAIXAR_TODOS = "⬇️ Baixar TODOS os episódios"
        BAIXAR_INTERVALO = "⬇️ Baixar um intervalo (ex.: 1 a 12)"
        VOLTAR = "⬅️ Voltar para a Seleção de Anime"

        # Opções de lote só fazem sentido em sites com download (link direto)
        opcoes = []
        if not getattr(self.scraper, "reproduz_no_navegador", False):
            opcoes += [BAIXAR_TODOS, BAIXAR_INTERVALO]
        opcoes += [ep.titulo for ep in episodios]
        opcoes.append(VOLTAR)

        escolha = questionary.select(
            "Selecione um episódio ou uma opção de download:",
            choices=opcoes
        ).ask()

        if escolha is None or escolha == VOLTAR:
            return ("voltar", None)
        if escolha == BAIXAR_TODOS:
            return ("baixar_todos", None)
        if escolha == BAIXAR_INTERVALO:
            return ("baixar_intervalo", None)

        episodio_selecionado = next(e for e in episodios if e.titulo == escolha)
        return ("episodio", episodio_selecionado)

    def menu_escolher_intervalo(self, episodios: list) -> list:
        """Pergunta o número inicial e final e retorna a fatia de episódios."""
        def pedir(texto, padrao):
            resp = questionary.text(texto, default=str(padrao)).ask()
            if resp is None:
                return None
            try:
                return float(resp.strip().replace(",", "."))
            except ValueError:
                return None

        primeiro = episodios[0].numero or "1"
        ultimo = episodios[-1].numero or str(len(episodios))

        inicio = pedir(f"A partir de qual episódio? (primeiro: {primeiro})", primeiro)
        fim = pedir(f"Até qual episódio? (último: {ultimo})", ultimo)
        if inicio is None or fim is None:
            print("[Erro] Números inválidos.")
            return []
        if inicio > fim:
            inicio, fim = fim, inicio

        def num(ep):
            try:
                return float(ep.numero)
            except (ValueError, TypeError):
                return None

        selecionados = [ep for ep in episodios
                        if num(ep) is not None and inicio <= num(ep) <= fim]
        print(f"\n[Lote] {len(selecionados)} episódio(s) no intervalo {inicio:g}–{fim:g}.")
        return selecionados

    def baixar_lote(self, episodios: list, nome_anime: str):
        """Baixa uma lista de episódios em sequência, com resumo ao final."""
        if not episodios:
            input("\nNenhum episódio para baixar. Pressione Enter para continuar...")
            return

        total = len(episodios)
        sucesso, falhas = 0, []
        print(f"\n[Lote] Iniciando download de {total} episódio(s).")
        print("[Lote] Ctrl+C cancela o episódio atual e pergunta se continua.\n")

        for i, ep in enumerate(episodios, 1):
            self.exibir_cabecalho()
            print(f"[Lote] Episódio {i}/{total}: {ep.titulo}\n")
            print("[Scraper] Extraindo link de vídeo...")
            url_video = self.scraper.extrair_url_video(ep.url_pagina)

            if not url_video:
                print("[Lote] Sem vídeo disponível, pulando.")
                falhas.append(ep.titulo)
                continue

            # O downloader captura o Ctrl+C e retorna None (episódio cancelado).
            resultado = self.downloader.baixar(url_video, nome_anime, ep.titulo)
            if resultado:
                sucesso += 1
                continue

            falhas.append(ep.titulo)
            # Download não concluído: pode ter sido erro ou cancelamento manual.
            # Se ainda houver episódios, pergunta se continua o lote.
            if i < total:
                continuar = questionary.confirm(
                    "Episódio não baixado. Continuar com os próximos?",
                    default=True,
                ).ask()
                if not continuar:
                    print("[Lote] Download em lote interrompido pelo usuário.")
                    break

        # Resumo final
        self.exibir_cabecalho()
        print(f"[Lote] Concluído: {sucesso}/{total} baixado(s) com sucesso.")
        if falhas:
            print(f"[Lote] {len(falhas)} não baixado(s):")
            for titulo in falhas:
                print(f"   - {titulo}")
        input("\nPressione Enter para voltar aos episódios...")

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
                acao, ep_escolhido = self.menu_selecionar_episodio(episodios)

                if acao == "voltar":
                    break  # Volta para a seleção de animes

                # 4. Downloads em lote
                if acao == "baixar_todos":
                    self.baixar_lote(episodios, anime_escolhido.titulo)
                    continue
                if acao == "baixar_intervalo":
                    selecionados = self.menu_escolher_intervalo(episodios)
                    self.baixar_lote(selecionados, anime_escolhido.titulo)
                    continue

                # 5. Episódio único: navegador (sites protegidos) ou VLC/download
                if getattr(self.scraper, "reproduz_no_navegador", False):
                    self.navegador.abrir(ep_escolhido.url_pagina)
                    continue  # Volta para a lista de episódios

                # 5a. Escolha da ação (assistir ou baixar)
                acao_ep = questionary.select(
                    f"O que deseja fazer com '{ep_escolhido.titulo}'?",
                    choices=["▶️ Assistir no VLC", "⬇️ Baixar episódio", "⬅️ Voltar"]
                ).ask()

                if acao_ep is None or acao_ep == "⬅️ Voltar":
                    continue

                # 5b. Extração do link direto do vídeo
                print(f"\n[Scraper] Extraindo link de vídeo para: {ep_escolhido.titulo}...")
                url_video = self.scraper.extrair_url_video(ep_escolhido.url_pagina)

                if not url_video:
                    print("[Erro] Não foi possível extrair o vídeo deste episódio.")
                    input("\nPressione Enter para continuar...")
                    continue

                if acao_ep == "▶️ Assistir no VLC":
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