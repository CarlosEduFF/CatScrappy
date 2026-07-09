# app/scrapers/animesonline_scraper.py

from app.scrapers.animesdrive_scraper import AnimesDriveScraper


class AnimesOnlineScraper(AnimesDriveScraper):
    """Scraper do animesonline.cloud.

    O site usa o mesmo tema (DooPlay/StarStruck) do AnimesDrive: busca no
    ?s=, episódios em .episode-card (data-episode-number/-title) e vídeo via
    wp-json/dooplayer/v2 -> jwplayer?source=<mp4>. Por isso herda toda a
    lógica do AnimesDriveScraper — só muda a base_url.

    Diferente do AnimesDrive (que caiu atrás da Cloudflare), este responde a
    requisições HTTP simples e serve o .mp4 sem exigir Referer.
    """

    base_url = "https://animesonline.cloud"
