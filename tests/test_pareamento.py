"""Pareamento da TV por código/QR: regras do módulo e rotas."""

import unittest
from unittest import mock

from fastapi.testclient import TestClient

from api import main, pareamento, supabase_client


class Relogio:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class ModuloTest(unittest.TestCase):
    def setUp(self):
        self.relogio = Relogio()
        self.p = pareamento.Pareamentos(agora=self.relogio)

    def test_codigo_curto_sem_caracteres_ambiguos(self):
        for _ in range(200):
            codigo = self.p.iniciar("TV")["codigo"]
            self.assertEqual(len(codigo), 6)
            self.assertTrue(set(codigo) <= set(pareamento.ALFABETO))
            self.assertFalse(set(codigo) & set("01OIL"))

    def test_segredo_longo_e_diferente_do_codigo(self):
        r = self.p.iniciar("TV da sala")
        self.assertGreaterEqual(len(r["segredo"]), 40)
        self.assertNotEqual(r["segredo"], r["codigo"])
        self.assertEqual((r["expira_em"], r["intervalo"]), (600, 3))

    def test_normaliza_o_codigo_digitado(self):
        r = self.p.iniciar("TV")
        digitado = " " + r["codigo"][:3].lower() + "-" + r["codigo"][3:].lower() + " "
        self.assertIsNotNone(self.p.info(digitado))

    def test_fluxo_completo_e_entrega_unica(self):
        r = self.p.iniciar("TV")
        self.assertEqual(self.p.consultar(r["segredo"])["status"], "pendente")
        self.assertTrue(self.p.aprovar(r["codigo"], {"access_token": "A", "refresh_token": "R", "usuario": {"id": "u"}}))
        entrega = self.p.consultar(r["segredo"])
        self.assertEqual(entrega["status"], "aprovado")
        self.assertEqual((entrega["access_token"], entrega["refresh_token"]), ("A", "R"))
        # a sessão sai UMA vez: quem consultar de novo (ou souber o código) não a recebe
        self.assertEqual(self.p.consultar(r["segredo"])["status"], "expirado")
        self.assertIsNone(self.p.info(r["codigo"]))

    def test_so_um_celular_aprova(self):
        r = self.p.iniciar("TV")
        self.assertTrue(self.p.aprovar(r["codigo"], {"access_token": "A"}))
        self.assertFalse(self.p.aprovar(r["codigo"], {"access_token": "OUTRO"}))
        self.assertEqual(self.p.consultar(r["segredo"])["access_token"], "A")

    def test_expira_em_10_minutos(self):
        r = self.p.iniciar("TV")
        self.relogio.t += 599
        self.assertEqual(self.p.consultar(r["segredo"])["status"], "pendente")
        self.relogio.t += 2
        self.assertEqual(self.p.consultar(r["segredo"])["status"], "expirado")
        self.assertIsNone(self.p.info(r["codigo"]))
        self.assertFalse(self.p.aprovar(r["codigo"], {"access_token": "A"}))
        self.assertEqual(self.p.total(), 0, "expirados são limpos da memória")

    def test_segredo_errado_nao_revela_nada(self):
        self.p.iniciar("TV")
        self.assertEqual(self.p.consultar("x" * 43), {"status": "expirado"})
        self.assertEqual(self.p.consultar(""), {"status": "expirado"})
        self.assertEqual(self.p.consultar(None), {"status": "expirado"})

    def test_nome_do_dispositivo_e_aparado(self):
        self.assertEqual(self.p.info(self.p.iniciar("  " + "x" * 80)["codigo"])["nome"], "x" * 40)
        self.assertEqual(self.p.info(self.p.iniciar("")["codigo"])["nome"], "TV")

    def test_limite_de_pendentes_protege_a_memoria(self):
        for _ in range(pareamento.MAX_PENDENTES):
            self.p.iniciar("TV")
        with self.assertRaises(pareamento.LimiteExcedido):
            self.p.iniciar("TV")
        self.relogio.t += 700  # expiraram: volta a aceitar
        self.p.iniciar("TV")


class LimitadorTest(unittest.TestCase):
    def test_janela_deslizante(self):
        rel = Relogio()
        lim = pareamento.Limitador(3, 60, agora=rel)
        for _ in range(3):
            lim.registrar("a")
        with self.assertRaises(pareamento.LimiteExcedido):
            lim.registrar("a")
        lim.registrar("b")  # outra chave não é afetada
        rel.t += 61
        lim.registrar("a")  # a janela andou

    def test_excedido_nao_consome_tentativa(self):
        lim = pareamento.Limitador(2, 60, agora=Relogio())
        self.assertFalse(lim.excedido("a"))
        lim.registrar("a")
        lim.registrar("a")
        self.assertTrue(lim.excedido("a"))
        self.assertTrue(lim.excedido("a"))


USUARIO = {"id": "u1", "email": "ana@exemplo.com"}
H = {"Authorization": "Bearer token"}


class RotasTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        # estado limpo a cada teste (os limitadores e a memória são do módulo)
        main._pareamentos = pareamento.Pareamentos()
        main._limite_inicio = pareamento.Limitador(10, 600)
        main._limite_consulta = pareamento.Limitador(900, 600)
        main._limite_codigo = pareamento.Limitador(10, 600)
        self.sessoes_criadas = []
        patches = [
            mock.patch.object(supabase_client, "configurado", return_value=True),
            mock.patch.object(supabase_client, "usuario_do_token", return_value=USUARIO),
            mock.patch.object(
                supabase_client, "criar_sessao_para",
                side_effect=lambda email: self.sessoes_criadas.append(email) or
                {"access_token": "TV-A", "refresh_token": "TV-R", "user": {"id": "u1", "email": email}},
            ),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def iniciar(self, nome="TV da sala"):
        return self.client.post("/auth/dispositivo", json={"nome": nome}).json()

    def test_fluxo_ponta_a_ponta(self):
        tv = self.iniciar()
        self.assertEqual(self.client.post("/auth/dispositivo/consultar", json={"segredo": tv["segredo"]}).json()["status"], "pendente")

        info = self.client.get(f"/auth/dispositivo/{tv['codigo']}", headers=H)
        self.assertEqual(info.status_code, 200)
        self.assertEqual(info.json()["nome"], "TV da sala")

        r = self.client.post("/auth/dispositivo/aprovar", json={"codigo": tv["codigo"]}, headers=H)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.sessoes_criadas, ["ana@exemplo.com"])

        entrega = self.client.post("/auth/dispositivo/consultar", json={"segredo": tv["segredo"]}).json()
        self.assertEqual(entrega["status"], "aprovado")
        self.assertEqual((entrega["access_token"], entrega["refresh_token"]), ("TV-A", "TV-R"))
        self.assertEqual(entrega["usuario"]["email"], "ana@exemplo.com")
        self.assertEqual(self.client.post("/auth/dispositivo/consultar", json={"segredo": tv["segredo"]}).json()["status"], "expirado")

    def test_aprovar_exige_login_mas_iniciar_nao(self):
        tv = self.iniciar()  # a TV ainda não tem conta: é público
        self.assertEqual(self.client.post("/auth/dispositivo/aprovar", json={"codigo": tv["codigo"]}).status_code, 401)
        self.assertEqual(self.client.get(f"/auth/dispositivo/{tv['codigo']}").status_code, 401)
        self.assertEqual(self.sessoes_criadas, [])

    def test_codigo_errado_404_e_nao_cria_sessao(self):
        r = self.client.post("/auth/dispositivo/aprovar", json={"codigo": "ZZZZZZ"}, headers=H)
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.sessoes_criadas, [], "não gera sessão à toa")

    def test_codigo_pode_ser_digitado_com_hifen_e_minusculas(self):
        tv = self.iniciar()
        digitado = (tv["codigo"][:3] + "-" + tv["codigo"][3:]).lower()
        self.assertEqual(self.client.post("/auth/dispositivo/aprovar", json={"codigo": digitado}, headers=H).status_code, 200)

    def test_adivinhar_codigos_trava_depois_de_10_erros(self):
        for _ in range(10):
            self.assertEqual(self.client.get("/auth/dispositivo/AAAAAA", headers=H).status_code, 404)
        tv = self.iniciar()
        # mesmo o código CERTO fica bloqueado para quem já errou 10 vezes
        r = self.client.post("/auth/dispositivo/aprovar", json={"codigo": tv["codigo"]}, headers=H)
        self.assertEqual(r.status_code, 429)
        self.assertEqual(self.sessoes_criadas, [])

    def test_acertar_nao_gasta_tentativas(self):
        for _ in range(15):
            tv = self.iniciar() if self.client.post("/auth/dispositivo", json={}).status_code == 200 else None
            if tv:
                self.assertEqual(self.client.get(f"/auth/dispositivo/{tv['codigo']}", headers=H).status_code, 200)

    def test_pedir_muitos_codigos_do_mesmo_ip_e_barrado(self):
        codigos = [self.client.post("/auth/dispositivo", json={}).status_code for _ in range(12)]
        self.assertEqual(codigos[:10], [200] * 10)
        self.assertEqual(codigos[10:], [429, 429])

    def test_so_o_primeiro_celular_aprova(self):
        tv = self.iniciar()
        self.assertEqual(self.client.post("/auth/dispositivo/aprovar", json={"codigo": tv["codigo"]}, headers=H).status_code, 200)
        r = self.client.post("/auth/dispositivo/aprovar", json={"codigo": tv["codigo"]}, headers=H)
        self.assertEqual(r.status_code, 404)

    def test_falha_do_supabase_vira_erro_claro_e_o_codigo_continua_valido(self):
        tv = self.iniciar()
        with mock.patch.object(supabase_client, "criar_sessao_para", side_effect=supabase_client.SupabaseError(502, "Supabase fora")):
            r = self.client.post("/auth/dispositivo/aprovar", json={"codigo": tv["codigo"]}, headers=H)
        self.assertEqual(r.status_code, 502)
        self.assertEqual(self.client.post("/auth/dispositivo/consultar", json={"segredo": tv["segredo"]}).json()["status"], "pendente")

    def test_conta_sem_email_nao_pareia(self):
        tv = self.iniciar()
        with mock.patch.object(supabase_client, "usuario_do_token", return_value={"id": "u2"}):
            r = self.client.post("/auth/dispositivo/aprovar", json={"codigo": tv["codigo"]}, headers=H)
        self.assertEqual(r.status_code, 400)

    def test_sem_supabase_configurado_503(self):
        with mock.patch.object(supabase_client, "configurado", return_value=False):
            self.assertEqual(self.client.post("/auth/dispositivo", json={}).status_code, 503)


class SessaoParaOutroDispositivoTest(unittest.TestCase):
    """supabase_client.criar_sessao_para: link mágico (sem e-mail) trocado por uma sessão."""

    def test_troca_o_token_do_link_pela_sessao(self):
        chamadas = []

        def falso(path, metodo, chave, token=None, corpo=None, prefer=None):
            chamadas.append((path, corpo))
            if "generate_link" in path:
                return 200, {"hashed_token": "HASH"}
            return 200, {"access_token": "A", "refresh_token": "R", "user": {"id": "u"}}

        with mock.patch.object(supabase_client, "_pedir", side_effect=falso):
            s = supabase_client.criar_sessao_para("ana@exemplo.com")
        self.assertEqual(s["access_token"], "A")
        self.assertEqual(chamadas[0][1], {"type": "magiclink", "email": "ana@exemplo.com"})
        self.assertEqual(chamadas[1][1], {"type": "magiclink", "token_hash": "HASH"})

    def test_aceita_o_formato_novo_com_properties(self):
        def falso(path, *a, **k):
            return (200, {"properties": {"hashed_token": "H2"}}) if "generate_link" in path else (200, {"access_token": "A"})

        with mock.patch.object(supabase_client, "_pedir", side_effect=falso):
            self.assertEqual(supabase_client.criar_sessao_para("a@b.c")["access_token"], "A")

    def test_sem_token_no_link_levanta_erro(self):
        with mock.patch.object(supabase_client, "_pedir", return_value=(200, {})):
            with self.assertRaises(supabase_client.SupabaseError):
                supabase_client.criar_sessao_para("a@b.c")


if __name__ == "__main__":
    unittest.main()
