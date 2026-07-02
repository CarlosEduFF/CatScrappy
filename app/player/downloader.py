# app/player/downloader.py

import os
import re
import time
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


class Downloader:
    """Baixa episódios (.mp4 direto) para a pasta 'downloads' do projeto."""

    def __init__(self, pasta_base: str = "downloads"):
        self.pasta_base = pasta_base

    def _nome_seguro(self, texto: str) -> str:
        """Remove caracteres proibidos em nomes de arquivo no Windows."""
        return re.sub(r'[<>:"/\\|?*]', "", texto).strip()

    def baixar(self, url_video: str, nome_anime: str, titulo_episodio: str) -> str:
        """Baixa o vídeo mostrando o progresso. Retorna o caminho do arquivo ou None."""
        pasta = os.path.join(self.pasta_base, self._nome_seguro(nome_anime))
        os.makedirs(pasta, exist_ok=True)

        arquivo = os.path.join(pasta, self._nome_seguro(titulo_episodio) + ".mp4")
        parcial = arquivo + ".part"

        if os.path.exists(arquivo):
            print(f"\n[Download] Já existe: {arquivo}")
            return arquivo

        print(f"\n[Download] Salvando em: {arquivo}")
        print("[Download] Pressione Ctrl+C para cancelar.\n")

        # Streams HLS (.m3u8) são playlists de segmentos, não um arquivo único;
        # o download deles é delegado ao yt-dlp.
        if self._eh_hls(url_video):
            return self._baixar_hls(url_video, arquivo)

        req = urllib.request.Request(url_video, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp, open(parcial, "wb") as f:
                total = int(resp.headers.get("Content-Length") or 0)
                baixado = 0
                inicio = time.time()

                while True:
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    baixado += len(chunk)
                    self._exibir_progresso(baixado, total, inicio)

            print()  # quebra de linha após a barra de progresso
            os.replace(parcial, arquivo)
            print(f"[Download] Concluído: {arquivo}")
            return arquivo

        except KeyboardInterrupt:
            print("\n[Download] Cancelado pelo usuário.")
        except Exception as e:
            print(f"\n[Download] Falhou: {e}")

        # Limpa o arquivo parcial em caso de cancelamento/erro
        if os.path.exists(parcial):
            try:
                os.remove(parcial)
            except OSError:
                pass
        return None

    def _eh_hls(self, url_video: str) -> bool:
        """Detecta stream HLS pelo início do conteúdo (playlist #EXTM3U)."""
        if ".m3u8" in url_video.split("?")[0]:
            return True
        try:
            req = urllib.request.Request(url_video, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as resp:
                tipo = (resp.headers.get("Content-Type") or "").lower()
                if "mpegurl" in tipo:
                    return True
                return resp.read(16).lstrip().startswith(b"#EXTM3U")
        except Exception:
            return False

    def _baixar_hls(self, url_video: str, arquivo: str) -> str:
        """Baixa um stream HLS com o yt-dlp, mostrando o progresso."""
        try:
            import yt_dlp
        except ImportError:
            print("[Download] Este episódio é um stream HLS e requer o yt-dlp.")
            print("[Download] Instale com: pip install yt-dlp")
            return None

        inicio = time.time()

        def progresso(d):
            if d.get("status") == "downloading":
                baixado = d.get("downloaded_bytes", 0)
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                self._exibir_progresso(baixado, total, inicio)

        opts = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,  # usa só a nossa barra de progresso
            "outtmpl": arquivo,
            "http_headers": {"User-Agent": UA},
            "progress_hooks": [progresso],
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url_video])
            print(f"\n[Download] Concluído: {arquivo}")
            return arquivo
        except KeyboardInterrupt:
            print("\n[Download] Cancelado pelo usuário.")
        except Exception as e:
            print(f"\n[Download] Falhou: {e}")

        # Remove restos do yt-dlp (.part, .ytdl, fragmentos etc.). Após um
        # cancelamento o yt-dlp deixa o handle do arquivo pendurado até o
        # garbage collector rodar — força a coleta antes de apagar.
        import gc
        import glob
        gc.collect()
        for sobra in glob.glob(arquivo + ".*"):
            for _ in range(5):
                try:
                    os.remove(sobra)
                    break
                except OSError:
                    time.sleep(0.5)
        return None

    def _exibir_progresso(self, baixado: int, total: int, inicio: float):
        mb = baixado / (1024 * 1024)
        segundos = max(time.time() - inicio, 0.001)
        velocidade = mb / segundos

        if total:
            pct = baixado * 100 / total
            total_mb = total / (1024 * 1024)
            barra = "█" * int(pct // 4) + "░" * (25 - int(pct // 4))
            print(f"\r[{barra}] {pct:5.1f}%  {mb:7.1f}/{total_mb:.1f} MB  "
                  f"{velocidade:5.1f} MB/s", end="", flush=True)
        else:
            print(f"\r[Download] {mb:.1f} MB baixados ({velocidade:.1f} MB/s)",
                  end="", flush=True)
