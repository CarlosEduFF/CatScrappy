# app/player/manga_reader.py

import os
import re
import time
import urllib.request

UA = "CatScrappy/1.0 (leitor de mangá pessoal)"


class MangaReader:
    """Baixa páginas de capítulos e monta pasta de imagens e/ou PDF."""

    def __init__(self, pasta_base: str = "mangas"):
        self.pasta_base = pasta_base

    def _nome_seguro(self, texto: str) -> str:
        return re.sub(r'[<>:"/\\|?*]', "", texto).strip()

    def _baixar_paginas(self, urls: list, pasta: str) -> list:
        """Baixa todas as páginas para 'pasta'. Retorna os caminhos, em ordem."""
        os.makedirs(pasta, exist_ok=True)
        total = len(urls)
        caminhos = []

        for i, url in enumerate(urls, 1):
            # Mantém a extensão original (jpg/png) e numera com zero à esquerda
            ext = os.path.splitext(url.split("?")[0])[1] or ".jpg"
            destino = os.path.join(pasta, f"{i:03d}{ext}")
            caminhos.append(destino)

            if not os.path.exists(destino):
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    dados = resp.read()
                with open(destino, "wb") as f:
                    f.write(dados)

            pct = i * 100 // total
            barra = "█" * (pct // 4) + "░" * (25 - pct // 4)
            print(f"\r[Manga] Baixando páginas [{barra}] {i}/{total}",
                  end="", flush=True)

        print()  # quebra de linha após a barra
        return caminhos

    def baixar_capitulo(self, urls: list, nome_manga: str, cap_numero: str,
                        gerar_pdf: bool) -> str:
        """Baixa um capítulo. Se gerar_pdf, monta um PDF; senão deixa a pasta.

        Retorna o caminho do PDF ou da pasta de imagens (ou None se falhar).
        """
        if not urls:
            print("[Manga] Capítulo sem páginas.")
            return None

        nome_manga = self._nome_seguro(nome_manga)
        rotulo = self._nome_seguro(f"Capitulo {cap_numero}")
        pasta = os.path.join(self.pasta_base, nome_manga, rotulo)

        print(f"\n[Manga] {nome_manga} - {rotulo} ({len(urls)} páginas)")
        try:
            caminhos = self._baixar_paginas(urls, pasta)
        except KeyboardInterrupt:
            print("\n[Manga] Download cancelado.")
            return None
        except Exception as e:
            print(f"\n[Manga] Falha ao baixar: {e}")
            return None

        if not gerar_pdf:
            print(f"[Manga] Páginas salvas em: {pasta}")
            return pasta

        # Gera o PDF a partir das imagens
        pdf = os.path.join(self.pasta_base, nome_manga, f"{rotulo}.pdf")
        if self._montar_pdf(caminhos, pdf):
            print(f"[Manga] PDF gerado: {pdf}")
            return pdf
        # Se o PDF falhar, ao menos a pasta de imagens fica disponível
        print(f"[Manga] Não foi possível gerar o PDF; imagens em: {pasta}")
        return pasta

    def _montar_pdf(self, caminhos: list, destino: str) -> bool:
        try:
            from PIL import Image
        except ImportError:
            print("\n[Manga] Para gerar PDF é preciso o Pillow (pip install Pillow).")
            return False

        try:
            imagens = []
            for c in caminhos:
                img = Image.open(c)
                # PDF não suporta transparência/paletas: converte para RGB
                if img.mode != "RGB":
                    img = img.convert("RGB")
                imagens.append(img)

            if not imagens:
                return False

            imagens[0].save(destino, "PDF", save_all=True,
                            append_images=imagens[1:])
            return True
        except Exception as e:
            print(f"\n[Manga] Erro ao montar PDF: {e}")
            return False

    def abrir(self, caminho: str):
        """Abre o PDF ou a pasta de imagens no aplicativo padrão do Windows."""
        if not caminho or not os.path.exists(caminho):
            return
        try:
            os.startfile(caminho)  # Windows: abre no visualizador/leitor padrão
        except AttributeError:
            # Fallback para outros sistemas
            import subprocess
            subprocess.Popen(["xdg-open", caminho])
