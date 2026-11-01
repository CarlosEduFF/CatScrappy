# api/pareamento.py — entrar na TV sem digitar senha: pareamento por código (e QR).
#
# Fluxo (o mesmo de "ativar dispositivo" de Netflix/YouTube):
#   1. a TV pede um pareamento e recebe um CÓDIGO curto (mostrado em tela e no QR) e um
#      SEGREDO longo (só a TV conhece; é com ele que ela pergunta se já foi aprovada);
#   2. no celular, já logado, a pessoa escaneia o QR (ou digita o código) e confirma;
#   3. o servidor cria uma sessão NOVA para a conta e a deixa à espera da TV;
#   4. a TV consulta com o segredo, recebe a sessão UMA vez e o pareamento some.
#
# Fica em memória de propósito: o que passa por aqui são tokens de sessão, e guardá-los num
# banco seria um risco a mais. Vive 10 minutos; se o servidor reiniciar nesse meio tempo
# (o Render free hiberna), a TV só mostra um código novo.

import secrets
import threading
import time

# Sem 0/O, 1/I/L: o código é lido de uma tela de TV e digitado no celular.
ALFABETO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
TAMANHO_CODIGO = 6
VALIDADE_S = 600
INTERVALO_S = 3
MAX_PENDENTES = 500


def normalizar_codigo(codigo: str) -> str:
    """Aceita 'k7q-m2x', ' K7QM2X ' etc.: o que importa são as letras e números."""
    return "".join(c for c in (codigo or "").upper() if c.isalnum())


class LimiteExcedido(Exception):
    """Muitas tentativas em pouco tempo."""


class Limitador:
    """Conta eventos por chave numa janela deslizante (anti-adivinhação e anti-abuso)."""

    def __init__(self, maximo: int, janela_s: float, agora=time.time):
        self.maximo, self.janela_s, self._agora = maximo, janela_s, agora
        self._eventos: dict = {}
        self._trava = threading.Lock()

    def registrar(self, chave: str) -> None:
        """Registra um evento; levanta LimiteExcedido se passou do máximo."""
        agora = self._agora()
        with self._trava:
            recentes = [t for t in self._eventos.get(chave, []) if agora - t < self.janela_s]
            if len(recentes) >= self.maximo:
                self._eventos[chave] = recentes
                raise LimiteExcedido()
            recentes.append(agora)
            self._eventos[chave] = recentes
            if len(self._eventos) > 5000:  # não cresce sem limite
                for k in [k for k, v in self._eventos.items() if not v or agora - v[-1] >= self.janela_s]:
                    del self._eventos[k]


    def excedido(self, chave: str) -> bool:
        """True se a chave já gastou todas as tentativas (sem registrar uma nova)."""
        agora = self._agora()
        with self._trava:
            return len([t for t in self._eventos.get(chave, []) if agora - t < self.janela_s]) >= self.maximo


class Pareamentos:
    def __init__(self, agora=time.time):
        self._agora = agora
        self._por_codigo: dict = {}
        self._por_segredo: dict = {}
        self._trava = threading.Lock()

    def _limpar(self) -> None:
        agora = self._agora()
        for codigo in [c for c, p in self._por_codigo.items() if p["expira"] <= agora]:
            self._por_segredo.pop(self._por_codigo.pop(codigo)["segredo"], None)

    def iniciar(self, nome: str = "") -> dict:
        with self._trava:
            self._limpar()
            if len(self._por_codigo) >= MAX_PENDENTES:
                raise LimiteExcedido()
            codigo = ""
            while not codigo or codigo in self._por_codigo:
                codigo = "".join(secrets.choice(ALFABETO) for _ in range(TAMANHO_CODIGO))
            segredo = secrets.token_urlsafe(32)
            agora = self._agora()
            item = {
                "codigo": codigo,
                "segredo": segredo,
                "nome": (nome or "").strip()[:40] or "TV",
                "criado": agora,
                "expira": agora + VALIDADE_S,
                "sessao": None,
            }
            self._por_codigo[codigo] = item
            self._por_segredo[segredo] = item
            return {"codigo": codigo, "segredo": segredo, "expira_em": VALIDADE_S, "intervalo": INTERVALO_S}

    def info(self, codigo: str):
        """Dados que o celular mostra antes de a pessoa confirmar. None se não existe/expirou."""
        with self._trava:
            self._limpar()
            item = self._por_codigo.get(normalizar_codigo(codigo))
            if not item or item["sessao"] is not None:
                return None
            return {"nome": item["nome"], "expira_em": max(0, int(item["expira"] - self._agora()))}

    def aprovar(self, codigo: str, sessao: dict) -> bool:
        """Entrega a sessão à TV que mostrou este código. False se o código não vale mais."""
        with self._trava:
            self._limpar()
            item = self._por_codigo.get(normalizar_codigo(codigo))
            if not item or item["sessao"] is not None:
                return False
            item["sessao"] = sessao
            return True

    def consultar(self, segredo: str) -> dict:
        """pendente | aprovado (com a sessão, entregue UMA vez) | expirado."""
        with self._trava:
            self._limpar()
            item = self._por_segredo.get(segredo or "")
            if not item:
                return {"status": "expirado"}
            if item["sessao"] is None:
                return {"status": "pendente", "expira_em": max(0, int(item["expira"] - self._agora()))}
            self._por_codigo.pop(item["codigo"], None)
            self._por_segredo.pop(item["segredo"], None)
            return {"status": "aprovado", **item["sessao"]}

    def total(self) -> int:
        with self._trava:
            self._limpar()
            return len(self._por_codigo)
