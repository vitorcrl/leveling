"""
Integration tests — fazem chamadas HTTP reais para a brapi.dev.

Requerem conexão com internet e um token válido em BRAPI_TOKEN no .env.
Se o token estiver vazio, os testes são pulados automaticamente.

Run with:
    pytest tests/integration/test_brapi_integration.py -v
"""

import pytest

from app.adapters.data.brapi_adapter import BrapiDataAdapter, BrapiError
from app.core.config import get_settings
from app.domain.models_asset import AssetSnapshot
from app.domain.ports import DataPort

pytestmark = pytest.mark.integration

# Tickers reais com alta liquidez — improvável que saiam do ar entre execuções
_LIQUID_FII = "MXRF11"     # fundo de papel, alta liquidez, sem vacância
_BRICK_FII = "HSML11"      # fundo de tijolo (shopping), tem vacância
_PAPER_FII = "KNCR11"      # fundo de papel (CRI), pode ter LTV


@pytest.fixture(autouse=True)
def require_brapi_token():
    """Pula todos os testes deste módulo se BRAPI_TOKEN não estiver configurado."""
    if not get_settings().BRAPI_TOKEN:
        pytest.skip("BRAPI_TOKEN not set — skipping brapi integration tests")


@pytest.fixture
def adapter() -> BrapiDataAdapter:
    return BrapiDataAdapter()


class TestFetchReturnsValidSnapshot:
    async def test_fetch_returns_asset_snapshot(self, adapter):
        snap = await adapter.fetch(_LIQUID_FII)
        assert isinstance(snap, AssetSnapshot)

    async def test_ticker_matches_request(self, adapter):
        snap = await adapter.fetch(_LIQUID_FII)
        assert snap.ticker == _LIQUID_FII

    async def test_market_is_br(self, adapter):
        snap = await adapter.fetch(_LIQUID_FII)
        assert snap.market == "BR"

    async def test_price_is_positive(self, adapter):
        snap = await adapter.fetch(_LIQUID_FII)
        assert snap.price > 0

    async def test_dy_12m_is_non_negative(self, adapter):
        snap = await adapter.fetch(_LIQUID_FII)
        assert snap.dy_12m >= 0

    async def test_liquidez_is_positive(self, adapter):
        # MXRF11 tem liquidez diária muito acima de R$500k
        snap = await adapter.fetch(_LIQUID_FII)
        assert snap.liquidez > 0

    async def test_implements_data_port(self, adapter):
        assert isinstance(adapter, DataPort)


class TestFetchFIITypeFields:
    async def test_brick_fii_may_have_vacancia(self, adapter):
        # Fundos de tijolo têm vacancyRate — pode ser None se brapi não retornar
        snap = await adapter.fetch(_BRICK_FII)
        # Só verifica o tipo — None ou float são ambos válidos
        assert snap.vacancia is None or isinstance(snap.vacancia, float)

    async def test_paper_fii_vacancia_is_none(self, adapter):
        # Fundos de papel (CRI) não têm vacância — deve ser None
        snap = await adapter.fetch(_PAPER_FII)
        assert snap.vacancia is None

    async def test_deltas_are_zero_on_fresh_fetch(self, adapter):
        # Deltas são calculados pelo pipeline, nunca pela brapi
        snap = await adapter.fetch(_LIQUID_FII)
        assert snap.delta_dy == 0.0
        assert snap.delta_price == 0.0
        assert snap.delta_vacancia == 0.0
        assert snap.delta_pvp == 0.0


class TestFetchMultipleTickers:
    async def test_fetch_multiple_tickers_independently(self, adapter):
        # Garante que o adapter funciona em loop (como o pipeline faz)
        tickers = [_LIQUID_FII, _BRICK_FII, _PAPER_FII]
        snapshots = []
        for ticker in tickers:
            snap = await adapter.fetch(ticker)
            snapshots.append(snap)

        assert len(snapshots) == 3
        assert {s.ticker for s in snapshots} == set(tickers)

    async def test_each_snapshot_has_unique_ticker(self, adapter):
        snap1 = await adapter.fetch(_LIQUID_FII)
        snap2 = await adapter.fetch(_PAPER_FII)
        assert snap1.ticker != snap2.ticker
        assert snap1.price != snap2.price or snap1.dy_12m != snap2.dy_12m


class TestFetchErrorHandling:
    async def test_raises_brapi_error_for_invalid_ticker(self, adapter):
        with pytest.raises(BrapiError):
            await adapter.fetch("INVALIDO99")

    async def test_ticker_is_case_insensitive(self, adapter):
        # Pipeline normaliza para uppercase, mas o adapter deve aceitar lowercase
        snap = await adapter.fetch(_LIQUID_FII.lower())
        assert snap.ticker == _LIQUID_FII
