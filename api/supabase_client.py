# api/supabase_client.py
#
# Integração mínima com o Supabase (auth + tabela de favoritos), usando só
# urllib para manter o padrão do projeto (sem dependências novas).
#
# As chaves vêm de variáveis de ambiente — NUNCA hardcode:
#   SUPABASE_URL           ex.: https://xxxx.supabase.co
#   SUPABASE_PUBLIC_KEY    chave publishable (sb_publishable_...)
#   SUPABASE_SECRET_KEY    chave secreta/service-role (sb_secret_...)
#
# A chave secreta ignora o RLS; por isso toda leitura/escrita de favoritos
# filtra explicitamente por user_id (obtido validando o token do usuário),
# garantindo que cada um só enxergue os próprios favoritos.

import json
import os
import urllib.error
import urllib.parse
import urllib.request

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_PUBLIC_KEY = os.environ.get("SUPABASE_PUBLIC_KEY", "")
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY", "")


class SupabaseError(Exception):
    """Erro vindo do Supabase, com código HTTP, mensagem e error_code.

    O error_code (ex.: 'email_not_confirmed', 'invalid_credentials') permite
    distinguir causas que compartilham o mesmo status HTTP 400.
    """

    def __init__(self, status: int, mensagem: str, codigo: str = ""):
        super().__init__(mensagem)
        self.status = status
        self.mensagem = mensagem
        self.codigo = codigo


def configurado() -> bool:
    """True se as três variáveis de ambiente estão presentes."""
    return bool(SUPABASE_URL and SUPABASE_PUBLIC_KEY and SUPABASE_SECRET_KEY)


def _pedir(path: str, metodo: str, chave: str, token: str = None,
           corpo: dict = None, prefer: str = None) -> tuple:
    """Faz uma chamada ao Supabase e devolve (status, dados_json_ou_None)."""
    headers = {"apikey": chave, "Content-Type": "application/json"}
    # O Authorization carrega o token do usuário (auth) ou a própria chave.
    headers["Authorization"] = f"Bearer {token or chave}"
    if prefer:
        headers["Prefer"] = prefer

    data = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(
        SUPABASE_URL + path, data=data, headers=headers, method=metodo
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            texto = resp.read().decode("utf-8", "ignore")
            return resp.status, (json.loads(texto) if texto else None)
    except urllib.error.HTTPError as e:
        texto = e.read().decode("utf-8", "ignore")
        codigo = ""
        try:
            info = json.loads(texto)
            msg = info.get("msg") or info.get("message") or info.get("error_description") or texto
            codigo = info.get("error_code") or info.get("code") or ""
        except ValueError:
            msg = texto
        raise SupabaseError(e.code, msg or "Erro no Supabase", str(codigo))
    except Exception as e:
        raise SupabaseError(502, f"Falha ao acessar o Supabase: {e}")


# ----------------------------------------------------------------------
# AUTH — cadastro, login e validação de token
# ----------------------------------------------------------------------
def signup(email: str, senha: str) -> dict:
    """Cria uma conta. Devolve o corpo do Supabase (pode ou não trazer token,
    dependendo de a confirmação de e-mail estar ligada)."""
    _, dados = _pedir(
        "/auth/v1/signup", "POST", SUPABASE_PUBLIC_KEY,
        corpo={"email": email, "password": senha},
    )
    return dados or {}


def login(email: str, senha: str) -> dict:
    """Faz login e devolve { access_token, refresh_token, user, ... }."""
    _, dados = _pedir(
        "/auth/v1/token?grant_type=password", "POST", SUPABASE_PUBLIC_KEY,
        corpo={"email": email, "password": senha},
    )
    return dados or {}


def usuario_do_token(token: str) -> dict:
    """Valida o access_token chamando /auth/v1/user e devolve o usuário.

    Levanta SupabaseError(401) se o token for inválido/expirado.
    """
    _, dados = _pedir("/auth/v1/user", "GET", SUPABASE_PUBLIC_KEY, token=token)
    return dados or {}


# ----------------------------------------------------------------------
# FAVORITOS — leitura/escrita via service role, sempre filtrando por user_id
# ----------------------------------------------------------------------
def listar_favoritos(user_id: str) -> list:
    query = urllib.parse.urlencode({
        "user_id": f"eq.{user_id}",
        "select": "tipo,site,item_id,titulo,imagem,criado_em",
        "order": "criado_em.desc",
    })
    _, dados = _pedir(
        f"/rest/v1/favoritos?{query}", "GET", SUPABASE_SECRET_KEY,
    )
    return dados or []


def adicionar_favorito(user_id: str, fav: dict) -> dict:
    corpo = {
        "user_id": user_id,
        "tipo": fav["tipo"],
        "site": fav["site"],
        "item_id": fav["item_id"],
        "titulo": fav["titulo"],
        "imagem": fav.get("imagem", ""),
    }
    try:
        _, dados = _pedir(
            "/rest/v1/favoritos", "POST", SUPABASE_SECRET_KEY,
            corpo=corpo, prefer="return=representation",
        )
        return (dados or [{}])[0]
    except SupabaseError as e:
        # 409 = já é favorito (constraint unique); trata como sucesso idempotente.
        if e.status == 409:
            return corpo
        raise


def remover_favorito(user_id: str, tipo: str, site: str, item_id: str) -> None:
    query = urllib.parse.urlencode({
        "user_id": f"eq.{user_id}",
        "tipo": f"eq.{tipo}",
        "site": f"eq.{site}",
        "item_id": f"eq.{item_id}",
    })
    _pedir(f"/rest/v1/favoritos?{query}", "DELETE", SUPABASE_SECRET_KEY)
