 # CatScrappy

CLI em Python para assistir e baixar animes (e ler mangás) direto do terminal.
Faz scraping de sites de anime, abre os episódios no VLC ou baixa em `downloads/`,
e lê mangás via API oficial do MangaDex (imagens ou PDF em `mangas/`).

## Recursos

- **Busca em múltiplos sites**: AnimeFire, AnimesOnline, SushiAnimes, AnimesDrive
  e TopAnimes (assistem no VLC), Goyabu (abre no Chrome, pois o player é protegido
  contra automação).
- **Assistir no VLC** por streaming, sem baixar.
- **Download** de episódio único, temporada inteira ou intervalo (ex.: 1 a 12),
  com barra de progresso e retomada do lote após falhas.
- **Mangás via MangaDex**: busca, leitura por capítulo e download em lote,
  como pasta de imagens ou PDF.

## Requisitos

- Python 3.10+
- [VLC](https://www.videolan.org/) instalado (para assistir por streaming)
- Google Chrome (apenas para o Goyabu)

## Instalação

```bash
pip install -r requirements.txt
playwright install chromium   # navegador headless usado pelo Goyabu
```

## Uso

```bash
python main.py
```

Navegue pelos menus: escolha anime ou mangá, o site, busque pelo nome e
selecione o episódio/capítulo. Use `python main.py --debug` para ver o
traceback completo em caso de erro.

## Estrutura

```
app/
├── cli/        # menus interativos (questionary) e helpers de lote
├── models/     # dataclasses Anime e Episodio
├── player/     # VLC, navegador, downloader e leitor de mangá
└── scrapers/   # um scraper por site + classe base compartilhada
tests/          # testes unitários das partes puras (parsing, filtros)
```

## Testes

```bash
python -m unittest discover tests
```

## Aviso

Projeto pessoal para fins de estudo. Os sites suportados mudam com frequência
(players, hosts e proteções), então um scraper pode parar de funcionar sem aviso.
