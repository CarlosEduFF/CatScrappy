# app/scrapers/mangaplus_scraper.py

"""Manga Plus (Shueisha) — parte que roda na API.

IMPORTANTE: a *listagem* (busca, capítulos, páginas) do Manga Plus é feita
NO CELULAR (mobile/src/mangaplus.js), porque a API oficial bane IPs de
datacenter (e até residenciais) muito rápido — o Render seria bloqueado.
Ver [[catscrappy-sites-manga]].

O que sobra para o servidor é UMA coisa que o celular não consegue fazer
sozinho dentro do fluxo de download/leitura (que só sabe consumir URLs de
imagem diretas): DESCRIPTOGRAFAR as páginas. Cada página do Manga Plus é
servida cifrada com um XOR de chave repetida; a chave (hex) vem junto na
resposta da API. Este módulo baixa a imagem cifrada e devolve os bytes já
decifrados — servidos pela rota /manga/mangaplus-img (ver api/main.py).

Assim o celular monta, em obterPaginas, URLs que apontam para essa rota com
?url=<imagem cifrada>&key=<hex>, e o resto do app (download → PDF, leitor)
continua tratando tudo como "URL de imagem direta".
"""

import urllib.request

# UA do app oficial: a API só responde JSON limpo com este UA; um UA de
# browser leva a resposta "Account Banned".
UA = "okhttp/4.9.0"


def _xor_descriptografar(dados: bytes, chave_hex: str) -> bytes:
    """Aplica XOR byte a byte com a chave (hex) repetida.

    O Manga Plus cifra cada imagem com uma chave curta repetida ao longo de
    todo o arquivo. Descriptografar é o mesmo XOR de volta.
    """
    chave = bytes.fromhex(chave_hex)
    n = len(chave)
    if not n:
        return dados
    saida = bytearray(len(dados))
    for i, b in enumerate(dados):
        saida[i] = b ^ chave[i % n]
    return bytes(saida)


def baixar_pagina_decifrada(url: str, chave_hex: str) -> tuple:
    """Baixa uma página cifrada e devolve (bytes_decifrados, content_type).

    Se chave_hex vier vazia, a imagem não é cifrada (algumas páginas de
    aviso/legais não são) e é repassada como está.
    """
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        bruto = resp.read()
        # O CDN serve JPEG; mantemos o tipo informado, com fallback.
        content_type = resp.headers.get("Content-Type") or "image/jpeg"

    if chave_hex:
        bruto = _xor_descriptografar(bruto, chave_hex)
    return bruto, content_type
