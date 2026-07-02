# app/player/vlc_wrapper.py

import subprocess
import os
import sys
import shutil
import time

class VLCWrapper:
    def __init__(self):
        self.vlc_path = self._encontrar_vlc()

    def _encontrar_vlc(self) -> str:
        """Tenta localizar o executável do VLC no sistema operacional atual."""
        
        # 1. Tenta encontrar se o VLC estiver no PATH do sistema (comum em Linux/Mac)
        vlc_no_path = shutil.which("vlc")
        if vlc_no_path:
            return vlc_no_path

        # 2. Caminhos padrão caso não esteja no PATH (foco em Windows e Mac)
        sistema = sys.platform
        
        if sistema == "win32":
            caminhos_windows = [
                r"C:\Program Files\VideoLAN\VLC\vlc.exe",
                r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe"
            ]
            for caminho in caminhos_windows:
                if os.path.exists(caminho):
                    return caminho
                    
        elif sistema == "darwin":  # macOS
            caminho_mac = "/Applications/VLC.app/Contents/MacOS/VLC"
            if os.path.exists(caminho_mac):
                return caminho_mac

        # Se não encontrar em lugar nenhum, retorna None
        return None

    def reproduzir(self, url_video: str):
        """Abre o VLC passando a URL do streaming de forma assíncrona para não travar o terminal."""
        if not url_video:
            print("[Erro] URL de vídeo inválida fornecida ao Player.")
            return

        if not self.vlc_path:
            print("\n" + "!" * 50)
            print("[ERRO] O reprodutor VLC não foi encontrado no seu computador.")
            print("Por favor, instale o VLC ou adicione-o ao seu PATH.")
            print("!" * 50)
            input("\nPressione Enter para voltar ao menu...")
            return

        print(f"\n[Player] Iniciando a transmissão...")
        print(f"[Player] URL: {url_video}")
        
        # Parâmetros recomendados para streaming de animes/m3u8 no VLC:
        # --play-and-exit: Fecha o VLC automaticamente quando o episódio terminar
        # --quiet: Reduz os logs desnecessários do VLC no terminal
        argumentos = [
            self.vlc_path, 
            url_video, 
            "--play-and-exit", 
            "--quiet"
        ]

        try:
            # Usamos Popen em vez de run() para que o Python abra o VLC
            # em segundo plano e NÃO congele o seu terminal de menus.
            # Assim o usuário pode fechar o VLC e o menu continua ativo.
            inicio = time.time()
            processo = subprocess.Popen(
                argumentos,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

            # Aguarda o usuário terminar de assistir (o processo do VLC fechar)
            processo.wait()

            # Se o VLC fechou em poucos segundos, ele não conseguiu reproduzir
            duracao = time.time() - inicio
            if duracao < 5:
                print("\n[Aviso] O VLC fechou imediatamente — provavelmente não "
                      "conseguiu abrir o vídeo.")
                print(f"[Aviso] Teste a URL manualmente no VLC (Ctrl+N): {url_video}")
                input("\nPressione Enter para continuar...")

        except Exception as e:
            print(f"[Erro] Falha ao abrir o VLC: {e}")
            input("\nPressione Enter para continuar...")