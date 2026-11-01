"""Rotas de domínio das fontes: quem pode escrever e o que é aceito."""

import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from api import main, supabase_client

ADMIN = {"id": "1", "email": "Admin@Exemplo.com", "email_confirmed_at": "2026-01-01"}
COMUM = {"id": "2", "email": "outro@exemplo.com", "email_confirmed_at": "2026-01-01"}
ADMIN_SEM_CONFIRMAR = {"id": "3", "email": "admin@exemplo.com", "email_confirmed_at": None}
H = {"Authorization": "Bearer token"}


class FontesAdminTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.salvos = {}
        patches = [
            mock.patch.dict(os.environ, {"ADMIN_EMAILS": "admin@exemplo.com, x@y.com"}),
            mock.patch.object(supabase_client, "configurado", return_value=True),
            mock.patch.object(supabase_client, "listar_dominios", side_effect=lambda: dict(self.salvos)),
            mock.patch.object(
                supabase_client, "salvar_dominio",
                side_effect=lambda site, url, por: self.salvos.__setitem__(site, url) or {},
            ),
            mock.patch.object(
                supabase_client, "apagar_dominio", side_effect=lambda site: self.salvos.pop(site, None)
            ),
            mock.patch.object(supabase_client, "registrar_pendente", side_effect=lambda *a: {"host": a[0]}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def como(self, usuario):
        p = mock.patch.object(supabase_client, "usuario_do_token", return_value=usuario)
        p.start()
        self.addCleanup(p.stop)

    def test_leitura_e_publica(self):
        self.salvos["redetoons"] = "https://redetoons.one"
        r = self.client.get("/fontes/dominios")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"dominios": {"redetoons": "https://redetoons.one"}})

    def test_admin_salva_e_normaliza_para_origem(self):
        self.como(ADMIN)
        r = self.client.put("/admin/fontes/redetoons", json={"url": "https://RedeToons.one/series?x=1"}, headers=H)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.salvos["redetoons"], "https://redetoons.one")

    def test_admin_restaura(self):
        self.como(ADMIN)
        self.salvos["redetoons"] = "https://redetoons.one"
        self.assertEqual(self.client.delete("/admin/fontes/redetoons", headers=H).status_code, 200)
        self.assertNotIn("redetoons", self.salvos)

    def test_usuario_comum_nao_escreve(self):
        self.como(COMUM)
        r = self.client.put("/admin/fontes/redetoons", json={"url": "https://a.com"}, headers=H)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.salvos, {})
        self.assertEqual(self.client.get("/admin/eu", headers=H).json(), {"admin": False})

    def test_email_de_admin_nao_confirmado_nao_vale(self):
        self.como(ADMIN_SEM_CONFIRMAR)
        r = self.client.put("/admin/fontes/redetoons", json={"url": "https://a.com"}, headers=H)
        self.assertEqual(r.status_code, 403)

    def test_sem_login_e_401(self):
        self.assertEqual(self.client.put("/admin/fontes/x", json={"url": "https://a.com"}).status_code, 401)

    def test_admin_pelo_app_metadata(self):
        for meta in ({"admin": True}, {"nivel": "admin"}):
            usuario = {"id": "9", "email": "qualquer@x.com", "app_metadata": meta}
            self.assertTrue(main._eh_admin(usuario), meta)
        # seinen não é admin; "admin": "true" (texto) também não.
        for meta in ({"nivel": "seinen"}, {"admin": "true"}, {}):
            usuario = {"id": "9", "email": "qualquer@x.com", "app_metadata": meta}
            self.assertFalse(main._eh_admin(usuario), meta)

    def test_admin_eu(self):
        self.como(ADMIN)
        self.assertEqual(self.client.get("/admin/eu", headers=H).json(), {"admin": True})

    def test_recusa_enderecos_perigosos(self):
        self.como(ADMIN)
        for url in ["http://a.com", "https://127.0.0.1", "https://a.com:8080", "https://u:p@a.com",
                    "https://localhost", "https://intranet", "ftp://a.com", "", "lixo"]:
            r = self.client.put("/admin/fontes/redetoons", json={"url": url}, headers=H)
            self.assertEqual(r.status_code, 400, url)
        self.assertEqual(self.salvos, {})

    def test_recusa_id_de_fonte_invalido(self):
        self.como(ADMIN)
        r = self.client.put("/admin/fontes/Re%20de!", json={"url": "https://a.com"}, headers=H)
        self.assertEqual(r.status_code, 400)

    def test_pendente_so_admin(self):
        self.como(COMUM)
        r = self.client.post("/admin/fontes/pendentes", json={"url": "https://novo.com"}, headers=H)
        self.assertEqual(r.status_code, 403)

    def test_pendente_registra_pelo_host(self):
        self.como(ADMIN)
        r = self.client.post("/admin/fontes/pendentes", json={"url": "https://novo.com/x"}, headers=H)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["pendente"]["host"], "novo.com")


if __name__ == "__main__":
    unittest.main()
