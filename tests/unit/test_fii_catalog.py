"""
Testes unitários do catálogo de FIIs.
"""

import pytest

from app.domain.fii_catalog import FII, suggest_fiis


class TestSuggestFiis:
    def test_returns_n_results(self):
        result = suggest_fiis("conservador", n=3)
        assert len(result) == 3

    def test_returns_fii_instances(self):
        result = suggest_fiis("moderado", n=2)
        assert all(isinstance(f, FII) for f in result)

    def test_conservador_gets_no_arrojado_only_fiis(self):
        # Repete várias vezes para cobrir aleatoriedade
        for _ in range(20):
            result = suggest_fiis("conservador", n=5)
            tickers = {f.ticker for f in result}
            # FIIs exclusivos de arrojado não devem aparecer para conservador
            arrojado_only = {"RBRF11", "BCFF11", "KFOF11", "PVBI11", "KNRI11", "XPML11", "VISC11", "IRDM11"}
            assert tickers.isdisjoint(arrojado_only), f"Conservador recebeu FII arrojado: {tickers & arrojado_only}"

    def test_all_profiles_return_results(self):
        for profile in ("conservador", "moderado", "arrojado"):
            result = suggest_fiis(profile, n=3)
            assert len(result) == 3, f"Perfil {profile!r} retornou {len(result)} resultados"

    def test_unknown_profile_falls_back_to_full_list(self):
        result = suggest_fiis("desconhecido", n=3)
        assert len(result) == 3

    def test_n_larger_than_eligible_clamped(self):
        # Pede mais do que existe — não deve lançar exceção
        result = suggest_fiis("conservador", n=100)
        assert len(result) > 0

    def test_fii_has_tipo_label(self):
        result = suggest_fiis("moderado", n=5)
        for fii in result:
            assert fii.tipo_label in ("Papel (CRI/CRA)", "Tijolo", "Fundo de Fundos")

    def test_no_duplicates_in_single_call(self):
        result = suggest_fiis("arrojado", n=5)
        tickers = [f.ticker for f in result]
        assert len(tickers) == len(set(tickers))
