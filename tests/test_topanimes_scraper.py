# tests/test_topanimes_scraper.py

import unittest
from app.scrapers.topanimes_scraper import TopAnimesScraper


class ExtrairArquivoHtmlTest(unittest.TestCase):
    """Parse do arquivo de vídeo no HTML de players Playerjs/jwplayer."""

    def setUp(self):
        self.scraper = TopAnimesScraper()

    def test_lista_de_qualidades_escolhe_a_maior(self):
        # Formato do Playerjs (csst.online): lista por qualidade
        corpo = ('file:"[360p]https://cdn/ep_360p.mp4/,'
                 '[720p]https://cdn/ep_720p.mp4/,'
                 '[1080p]https://cdn/ep.mp4/"')
        self.assertEqual(
            self.scraper._extrair_arquivo_html(corpo, "1"),
            "https://cdn/ep.mp4/",
        )

    def test_qualidades_fora_de_ordem(self):
        corpo = 'file:"[1080p]https://cdn/full.mp4,[480p]https://cdn/sd.mp4"'
        self.assertEqual(
            self.scraper._extrair_arquivo_html(corpo, "1"),
            "https://cdn/full.mp4",
        )

    def test_arquivo_direto_jwplayer(self):
        corpo = 'sources: [{"file": "https://cdn/video.mp4", "type":"mp4"}]'
        self.assertEqual(
            self.scraper._extrair_arquivo_html(corpo, "1"),
            "https://cdn/video.mp4",
        )

    def test_player_desativado_com_arquivo_vazio(self):
        # Caso real: embed do topanimes com o player desativado pelo site
        corpo = 'sources: [{"file": "", "type":"mp4", "label":"1080p"}]'
        self.assertIsNone(self.scraper._extrair_arquivo_html(corpo, "1"))

    def test_html_sem_player(self):
        corpo = "<html><body>Pagina de aviso qualquer</body></html>"
        self.assertIsNone(self.scraper._extrair_arquivo_html(corpo, "1"))

    def test_file_sem_url_valida(self):
        corpo = 'file:"videoplayback"'
        self.assertIsNone(self.scraper._extrair_arquivo_html(corpo, "1"))


if __name__ == "__main__":
    unittest.main()
