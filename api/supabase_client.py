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
def signup(email: str, senha: str, nome: str = "") -> dict:
    """Cria uma conta. Devolve o corpo do Supabase (pode ou não trazer token,
    dependendo de a confirmação de e-mail estar ligada).

    O nome (quando informado) vai para o user_metadata via `data`.
    """
    corpo = {"email": email, "password": senha}
    if nome:
        corpo["data"] = {"nome": nome}
    _, dados = _pedir(
        "/auth/v1/signup", "POST", SUPABASE_PUBLIC_KEY, corpo=corpo,
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


def atualizar_perfil(token: str, nome: str = None, avatar_url: str = None) -> dict:
    """Atualiza nome e/ou avatar no user_metadata do usuário logado."""
    metadata = {}
    if nome is not None:
        metadata["nome"] = nome
    if avatar_url is not None:
        metadata["avatar_url"] = avatar_url
    _, dados = _pedir(
        "/auth/v1/user", "PUT", SUPABASE_PUBLIC_KEY, token=token,
        corpo={"data": metadata},
    )
    return dados or {}


# Bucket público onde as fotos de perfil ficam. Criar no painel do Supabase.
BUCKET_AVATARES = "avatares"


def upload_avatar(user_id: str, dados_imagem: bytes, content_type: str) -> str:
    """Envia a imagem ao Storage e devolve a URL pública.

    Usa a service-role key (ignora as policies do bucket). O caminho é fixo
    por usuário (<user_id>.<ext>) com upsert, então trocar a foto substitui a
    anterior — sem acumular arquivos órfãos.
    """
    ext = {"image/png": "png", "image/webp": "webp"}.get(content_type, "jpg")
    caminho = f"{user_id}.{ext}"
    url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET_AVATARES}/{caminho}"
    headers = {
        "apikey": SUPABASE_SECRET_KEY,
        "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
        "Content-Type": content_type,
        "x-upsert": "true",  # sobrescreve a foto anterior do mesmo usuário
    }
    req = urllib.request.Request(url, data=dados_imagem, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30):
            pass
    except urllib.error.HTTPError as e:
        texto = e.read().decode("utf-8", "ignore")
        raise SupabaseError(e.code, texto or "Falha ao enviar a imagem.")
    except Exception as e:
        raise SupabaseError(502, f"Falha ao enviar a imagem: {e}")

    # URL pública (bucket público). O ?t= força o app a recarregar após trocar.
    return (f"{SUPABASE_URL}/storage/v1/object/public/"
            f"{BUCKET_AVATARES}/{caminho}")


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


# ----------------------------------------------------------------------
# HISTÓRICO — episódios/capítulos já vistos, por série (mesmo padrão acima)
# ----------------------------------------------------------------------
def listar_historico(user_id: str, tipo: str, site: str, item_id: str) -> list:
    """Todos os episódios/capítulos vistos de uma série/mangá específico."""
    query = urllib.parse.urlencode({
        "user_id": f"eq.{user_id}",
        "tipo": f"eq.{tipo}",
        "site": f"eq.{site}",
        "item_id": f"eq.{item_id}",
        "select": "episodio_id,numero,titulo,visto_em",
        "order": "visto_em.desc",
    })
    _, dados = _pedir(f"/rest/v1/historico?{query}", "GET", SUPABASE_SECRET_KEY)
    return dados or []


def marcar_visto(user_id: str, item: dict) -> dict:
    corpo = {
        "user_id": user_id,
        "tipo": item["tipo"],
        "site": item["site"],
        "item_id": item["item_id"],
        "episodio_id": item["episodio_id"],
        "numero": item.get("numero", ""),
        "titulo": item.get("titulo", ""),
    }
    try:
        _, dados = _pedir(
            "/rest/v1/historico", "POST", SUPABASE_SECRET_KEY,
            corpo=corpo, prefer="return=representation",
        )
        return (dados or [{}])[0]
    except SupabaseError as e:
        # 409 = já estava marcado (constraint unique); sucesso idempotente.
        if e.status == 409:
            return corpo
        raise


def desmarcar_visto(user_id: str, tipo: str, site: str,
                    item_id: str, episodio_id: str) -> None:
    query = urllib.parse.urlencode({
        "user_id": f"eq.{user_id}",
        "tipo": f"eq.{tipo}",
        "site": f"eq.{site}",
        "item_id": f"eq.{item_id}",
        "episodio_id": f"eq.{episodio_id}",
    })
    _pedir(f"/rest/v1/historico?{query}", "DELETE", SUPABASE_SECRET_KEY)
