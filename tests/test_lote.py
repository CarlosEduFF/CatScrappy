# tests/test_lote.py

import unittest
from types import SimpleNamespace
from app.cli.lote import filtrar_intervalo


def item(numero):
    return SimpleNamespace(numero=numero)


class FiltrarIntervaloTest(unittest.TestCase):
    def test_intervalo_simples(self):
        itens = [item("1"), item("2"), item("3"), item("4")]
        self.assertEqual(
            [i.numero for i in filtrar_intervalo(itens, 2, 3)],
            ["2", "3"],
        )

    def test_limites_invertidos_sao_corrigidos(self):
        itens = [item("1"), item("2"), item("3")]
        self.assertEqual(
            [i.numero for i in filtrar_intervalo(itens, 3, 1)],
            ["1", "2", "3"],
        )

    def test_numero_nao_numerico_fica_de_fora(self):
        itens = [item("1"), item("?"), item(None), item("2")]
        self.assertEqual(
            [i.numero for i in filtrar_intervalo(itens, 1, 2)],
            ["1", "2"],
        )

    def test_episodios_especiais_fracionarios(self):
        # Sites usam números tipo "1022.5" para especiais
        itens = [item("1022"), item("1022.5"), item("1023")]
        self.assertEqual(
            [i.numero for i in filtrar_intervalo(itens, 1022, 1023)],
            ["1022", "1022.5", "1023"],
        )

    def test_intervalo_sem_itens(self):
        itens = [item("1"), item("2")]
        self.assertEqual(filtrar_intervalo(itens, 10, 20), [])


if __name__ == "__main__":
    unittest.main()
