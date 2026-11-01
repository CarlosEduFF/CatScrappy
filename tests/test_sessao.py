"""Só falha de AUTENTICAÇÃO vira 401. Falha do Supabase/rede vira 503 (o app tenta de novo)."""

import unittest
from unittest import mock

from fastapi.testclient import TestClient

from api import main, supabase_client

H = {"Authorization": "Bearer token"}


def erro(status, codigo=""):
    return supabase_client.SupabaseError(status, "falhou", codigo)


class AutenticacaoTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        for p in (
            mock.patch.object(supabase_client, "configurado", return_value=True),
            mock.patch.object(supabase_client, "listar_favoritos", return_value=[{"site": "x", "item_id": "1"}]),
        ):
            p.start()
            self.addCleanup(p.stop)

    def com_usuario(self, **kw):
        p = mock.patch.object(supabase_client, "usuario_do_token", **kw)
        p.start()
        self.addCleanup(p.stop)

    def test_token_valido_lista_os_favoritos(self):
        self.com_usuario(return_value={"id": "u1", "email": "a@x.com"})
        r = self.client.get("/favoritos", headers=H)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["favoritos"]), 1)

    def test_token_vencido_ou_invalido_e_401(self):
        # o Supabase responde 403 bad_jwt para token vencido, e 401/400 para sessão revogada
        for status in (400, 401, 403):
            with self.subTest(status=status):
                self.com_usuario(side_effect=erro(status, "bad_jwt"))
                r = self.client.get("/favoritos", headers=H)
                self.assertEqual(r.status_code, 401)
                self.assertIn("Sessão expirada", r.json()["detail"])

    def test_supabase_fora_do_ar_NAO_e_401(self):
        # antes: virava 401 "Sessão expirada" e o app gastava o refresh à toa
        for status in (429, 500, 502, 503, 504):
            with self.subTest(status=status):
                self.com_usuario(side_effect=erro(status))
                r = self.client.get("/favoritos", headers=H)
                self.assertEqual(r.status_code, 503)
                self.assertIn("indisponível", r.json()["detail"])

    def test_sem_header_ou_malformado_continua_401(self):
        self.assertEqual(self.client.get("/favoritos").status_code, 401)
        self.assertEqual(self.client.get("/favoritos", headers={"Authorization": "Basic x"}).status_code, 401)

    def test_usuario_sem_id_e_401(self):
        self.com_usuario(return_value={"email": "a@x.com"})
        self.assertEqual(self.client.get("/favoritos", headers=H).status_code, 401)

    def test_vale_para_o_historico_tambem(self):
        self.com_usuario(side_effect=erro(502))
        with mock.patch.object(supabase_client, "listar_historico", return_value=[]):
            r = self.client.get("/historico", params={"tipo": "anime", "site": "x", "item_id": "1"}, headers=H)
        self.assertEqual(r.status_code, 503)


class RenovarTest(unittest.TestCase):
    """/auth/refresh: só refresh inválido/encerrado derruba a sessão do app (401)."""

    def setUp(self):
        self.client = TestClient(main.app)
        p = mock.patch.object(supabase_client, "configurado", return_value=True)
        p.start()
        self.addCleanup(p.stop)

    def renovar(self, **kw):
        with mock.patch.object(supabase_client, "renovar_sessao", **kw):
            return self.client.post("/auth/refresh", json={"refresh_token": "R1"})

    def test_ok_devolve_o_par_novo_e_o_usuario(self):
        r = self.renovar(return_value={"access_token": "A2", "refresh_token": "R2", "user": {"id": "u1"}})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"access_token": "A2", "refresh_token": "R2", "usuario": {"id": "u1"}})

    def test_refresh_invalido_ou_encerrado_e_401(self):
        for status in (400, 401, 403):
            with self.subTest(status=status):
                self.assertEqual(self.renovar(side_effect=erro(status, "refresh_token_not_found")).status_code, 401)

    def test_falha_transitoria_NAO_derruba_a_sessao(self):
        # 429/5xx passam como estão: o app só trata 401 como "sessão acabou"
        for status in (429, 500, 502, 503):
            with self.subTest(status=status):
                self.assertEqual(self.renovar(side_effect=erro(status)).status_code, status)

    def test_sem_refresh_token_e_400(self):
        self.assertEqual(self.client.post("/auth/refresh", json={}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
