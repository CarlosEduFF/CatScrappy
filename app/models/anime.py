from dataclasses import dataclass

@dataclass
class Episodio:
    titulo: str
    url_pagina: str
    numero: str = ""
    url_video: str = None

@dataclass
class Anime:
    titulo: str
    url_detalhes: str
    id: str = ""
    audio: str = ""
    ano: str = ""
    imagem: str = ""
    sinopse: str = ""
