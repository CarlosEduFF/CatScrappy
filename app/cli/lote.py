# app/cli/lote.py

"""Helpers puros de download em lote, compartilhados por anime e mangá."""

# Sentinela devolvida por um item sem mídia disponível: o lote registra a
# falha e segue para o próximo sem perguntar se o usuário quer continuar.
PULAR = object()


def filtrar_intervalo(itens: list, inicio: float, fim: float) -> list:
    """Filtra itens (com atributo .numero) cujo número cai em [inicio, fim].

    Itens com número não numérico (ex.: "?") ficam de fora; limites
    invertidos são corrigidos automaticamente.
    """
    if inicio > fim:
        inicio, fim = fim, inicio

    def num(item):
        try:
            return float(item.numero)
        except (ValueError, TypeError):
            return None

    return [i for i in itens if num(i) is not None and inicio <= num(i) <= fim]
