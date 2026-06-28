from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters.data.brapi_adapter import BrapiDataAdapter, BrapiError


def make_brapi_response(
    price: float = 97.50,
    volume: float = 10_000,
    change_percent: float = 0.5,
    dividends: list | None = None,
    status_code: int = 200,
) -> MagicMock:
    """Monta uma resposta httpx mockada com a estrutura do plano free da brapi.dev."""
    data = {
        "regularMarketPrice": price,
        "regularMarketVolume": volume,
        "regularMarketChangePercent": change_percent,
    }
    if dividends is not None:
        data["dividendsData"] = {"cashDividends": dividends}

    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = {"results": [data]}
    return response


@pytest.fixture
def adapter():
    return BrapiDataAdapter(base_url="https://brapi.dev/api", token="test-token")


@pytest.fixture
def mock_httpx():
    """Mocka o httpx.AsyncClient para não fazer chamadas reais."""
    with patch("app.adapters.data.brapi_adapter.httpx.AsyncClient") as mock_cls:
        client = AsyncMock()
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        yield client


class TestFetchBasicFields:
    async def test_returns_snapshot_with_correct_ticker(self, adapter, mock_httpx):
        mock_httpx.get = AsyncMock(return_value=make_brapi_response())
        snap = await adapter.fetch("KNCR11")
        assert snap.ticker == "KNCR11"

    async def test_ticker_is_uppercased(self, adapter, mock_httpx):
        mock_httpx.get = AsyncMock(return_value=make_brapi_response())
        snap = await adapter.fetch("kncr11")
        assert snap.ticker == "KNCR11"

    async def test_market_is_br(self, adapter, mock_httpx):
        mock_httpx.get = AsyncMock(return_value=make_brapi_response())
        snap = await adapter.fetch("KNCR11")
        assert snap.market == "BR"

    async def test_price_is_mapped(self, adapter, mock_httpx):
        mock_httpx.get = AsyncMock(return_value=make_brapi_response(price=98.70))
        snap = await adapter.fetch("KNCR11")
        assert snap.price == 98.70

    async def test_dy_is_zero_on_free_plan(self, adapter, mock_httpx):
        # plano free da brapi não retorna dividendYield — adapter zera
        mock_httpx.get = AsyncMock(return_value=make_brapi_response())
        snap = await adapter.fetch("KNCR11")
        assert snap.dy_12m == 0.0

    async def test_pvp_is_zero_on_free_plan(self, adapter, mock_httpx):
        # plano free da brapi não retorna priceToBook — adapter zera
        mock_httpx.get = AsyncMock(return_value=make_brapi_response())
        snap = await adapter.fetch("KNCR11")
        assert snap.pvp == 0.0


class TestLiquidezCalculation:
    async def test_liquidez_is_volume_times_price(self, adapter, mock_httpx):
        # 10.000 cotas × R$100 = R$1.000.000
        mock_httpx.get = AsyncMock(
            return_value=make_brapi_response(price=100.0, volume=10_000)
        )
        snap = await adapter.fetch("KNCR11")
        assert snap.liquidez == pytest.approx(1_000_000)

    async def test_liquidez_zero_when_no_volume(self, adapter, mock_httpx):
        mock_httpx.get = AsyncMock(
            return_value=make_brapi_response(price=100.0, volume=0)
        )
        snap = await adapter.fetch("KNCR11")
        assert snap.liquidez == 0.0


class TestOptionalFields:
    async def test_vacancia_is_none_on_free_plan(self, adapter, mock_httpx):
        # plano free não retorna vacancyRate
        mock_httpx.get = AsyncMock(return_value=make_brapi_response())
        snap = await adapter.fetch("HSML11")
        assert snap.vacancia is None

    async def test_ltv_is_none_on_free_plan(self, adapter, mock_httpx):
        # plano free não retorna ltvRatio
        mock_httpx.get = AsyncMock(return_value=make_brapi_response())
        snap = await adapter.fetch("MXRF11")
        assert snap.ltv is None


class TestDeltasAreZeroOnFetch:
    async def test_deltas_default_to_zero(self, adapter, mock_httpx):
        # O pipeline calcula os deltas depois de buscar o snapshot anterior no banco
        mock_httpx.get = AsyncMock(return_value=make_brapi_response())
        snap = await adapter.fetch("KNCR11")
        assert snap.delta_dy == 0.0
        assert snap.delta_vacancia == 0.0
        assert snap.delta_pvp == 0.0

    async def test_delta_price_is_filled_from_api(self, adapter, mock_httpx):
        # regularMarketChangePercent é disponível no plano free e preenchido diretamente
        mock_httpx.get = AsyncMock(return_value=make_brapi_response(change_percent=-3.5))
        snap = await adapter.fetch("KNCR11")
        assert snap.delta_price == pytest.approx(-3.5)


class TestProventoExtraction:
    async def test_provento_returned_when_declared_today(self, adapter, mock_httpx):
        today = date.today().isoformat()
        dividends = [{"declarationDate": today, "rate": 0.0950}]
        mock_httpx.get = AsyncMock(
            return_value=make_brapi_response(dividends=dividends)
        )
        snap = await adapter.fetch("MXRF11")
        assert snap.provento_anunciado == pytest.approx(0.0950)

    async def test_provento_none_when_declared_in_past(self, adapter, mock_httpx):
        dividends = [{"declarationDate": "2026-01-15", "rate": 0.0950}]
        mock_httpx.get = AsyncMock(
            return_value=make_brapi_response(dividends=dividends)
        )
        snap = await adapter.fetch("MXRF11")
        assert snap.provento_anunciado is None

    async def test_provento_none_when_no_dividends(self, adapter, mock_httpx):
        mock_httpx.get = AsyncMock(return_value=make_brapi_response(dividends=[]))
        snap = await adapter.fetch("MXRF11")
        assert snap.provento_anunciado is None

    async def test_picks_most_recent_dividend(self, adapter, mock_httpx):
        # Garante que ordena por data antes de pegar o primeiro
        today = date.today().isoformat()
        dividends = [
            {"declarationDate": "2026-01-01", "rate": 0.08},
            {"declarationDate": today, "rate": 0.095},
        ]
        mock_httpx.get = AsyncMock(
            return_value=make_brapi_response(dividends=dividends)
        )
        snap = await adapter.fetch("MXRF11")
        assert snap.provento_anunciado == pytest.approx(0.095)


class TestErrorHandling:
    async def test_raises_brapi_error_on_non_200(self, adapter, mock_httpx):
        mock_httpx.get = AsyncMock(
            return_value=make_brapi_response(status_code=404)
        )
        with pytest.raises(BrapiError):
            await adapter.fetch("INVALID11")

    async def test_raises_brapi_error_when_no_results(self, adapter, mock_httpx):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"results": []}
        mock_httpx.get = AsyncMock(return_value=response)
        with pytest.raises(BrapiError):
            await adapter.fetch("KNCR11")

    async def test_raises_brapi_error_when_price_missing(self, adapter, mock_httpx):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"results": [{"dividendYield": 10.0}]}
        mock_httpx.get = AsyncMock(return_value=response)
        with pytest.raises(BrapiError):
            await adapter.fetch("KNCR11")

    async def test_implements_data_port(self):
        from app.domain.ports import DataPort
        assert isinstance(BrapiDataAdapter(), DataPort)


class TestToFloatEdgeCases:
    async def test_non_numeric_volume_results_in_zero_liquidez(self, adapter, mock_httpx):
        # _to_float retorna None para strings não numéricas — volume vira 0
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"results": [{
            "regularMarketPrice": 100.0,
            "regularMarketVolume": "N/A",
            "regularMarketChangePercent": 0.0,
        }]}
        mock_httpx.get = AsyncMock(return_value=response)
        snap = await adapter.fetch("KNCR11")
        assert snap.liquidez == 0.0


class TestProventoEdgeCases:
    async def test_provento_none_when_dividend_has_no_date_fields(self, adapter, mock_httpx):
        # Cobre linha 168 — latest sem declarationDate nem paymentDate
        dividends = [{"rate": 0.095}]  # sem nenhum campo de data
        mock_httpx.get = AsyncMock(
            return_value=make_brapi_response(dividends=dividends)
        )
        snap = await adapter.fetch("MXRF11")
        assert snap.provento_anunciado is None

    async def test_provento_none_when_date_is_malformed(self, adapter, mock_httpx):
        # Cobre linhas 172-174 — data existe mas não é ISO válida
        today = date.today().isoformat()
        dividends = [{"declarationDate": "not-a-date", "rate": 0.095}]
        mock_httpx.get = AsyncMock(
            return_value=make_brapi_response(dividends=dividends)
        )
        snap = await adapter.fetch("MXRF11")
        assert snap.provento_anunciado is None

    async def test_dividend_with_invalid_sort_date_goes_last(self, adapter, mock_httpx):
        # Cobre o path de date.min no _parse_date interno — entrada sem data válida
        # vai pro final da ordenação, não quebra o sort
        today = date.today().isoformat()
        dividends = [
            {"declarationDate": "invalido", "rate": 0.05},
            {"declarationDate": today, "rate": 0.095},
        ]
        mock_httpx.get = AsyncMock(
            return_value=make_brapi_response(dividends=dividends)
        )
        snap = await adapter.fetch("MXRF11")
        # O válido (hoje) deve ganhar — não o inválido (date.min vai pro final)
        assert snap.provento_anunciado == pytest.approx(0.095)
