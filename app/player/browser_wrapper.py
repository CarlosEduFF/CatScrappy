# app/player/browser_wrapper.py

import os
import subprocess
import webbrowser


class BrowserWrapper:
    """Abre uma página no Chrome (ou no navegador padrão, se não achar o Chrome).

    Usado pelos sites cujo player não funciona no VLC (ex.: Goyabu, que
    protege o vídeo contra acesso automatizado).
    """

    def __init__(self):
        self.chrome_path = self._encontrar_chrome()

    def _encontrar_chrome(self) -> str:
        caminhos = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]
        for caminho in caminhos:
            if os.path.exists(caminho):
                return caminho
        return None

    def abrir(self, url: str):
        """Abre a URL no Chrome sem travar o terminal."""
        if not url:
            print("[Erro] URL inválida fornecida ao navegador.")
            return

        if self.chrome_path:
            print("[Player] Abrindo o episódio no Chrome...")
            subprocess.Popen(
                [self.chrome_path, url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            print("[Player] Chrome não encontrado; abrindo no navegador padrão...")
            webbrowser.open(url)
