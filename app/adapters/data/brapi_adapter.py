# Adapter que implementa DataPort consumindo a API pública brapi.dev.
# brapi.dev é um agregador gratuito de dados do mercado brasileiro —
# retorna cotação, P/VP, DY, vacância, LTV e proventos de FIIs em JSON.
#
# Documentação: https://brapi.dev/docs
# Endpoint principal: GET /api/quote/{ticker}?token=...&fundamental=true
#
# Este adapter é injetado no AssetPipeline pelo journey_runner.py.
# Para trocar a fonte de dados (ex: Status Invest, funds.net), basta criar
# outro adapter que implemente o mesmo método fetch() — o pipeline não muda.

import logging
from datetime import date, datetime, timezone

import httpx

from app.core.config import get_settings
from app.domain.models_asset import AssetSnapshot

logger = logging.getLogger(__name__)

# Timeout generoso porque brapi.dev pode ser lento em horário de pico
_HTTP_TIMEOUT = 15.0


# BrapiError declarado antes de qualquer uso para evitar confusão na leitura
class BrapiError(Exception):
    """Erro ao buscar dados na brapi.dev — capturado pelo pipeline por ticker."""
    pass


class BrapiDataAdapter:
    """
    Implementação de DataPort para FIIs brasileiros via brapi.dev.

    Uso:
        adapter = BrapiDataAdapter()
        snapshot = await adapter.fetch("KNCR11")
    """

    def __init__(self, base_url: str | None = None, token: str | None = None) -> None:
        # Lê settings sob demanda (não em import time) para não quebrar testes
        # que rodam sem .env. get_settings() usa lru_cache, então é barato.
        _settings = get_settings()
        self._base_url = base_url or _settings.BRAPI_BASE_URL
        self._token = token or _settings.BRAPI_TOKEN

    async def fetch(self, ticker: str) -> AssetSnapshot:
        """
        Busca os indicadores do ticker na brapi.dev e retorna um AssetSnapshot.
        Lança BrapiError se a API retornar erro ou o ticker não existir.
        Os deltas (delta_dy, delta_price etc.) ficam em 0.0 — o pipeline
        os calcula depois consultando o snapshot da semana anterior no banco.
        """
        url = f"{self._base_url}/quote/{ticker}"
        params = {
            "token": self._token,
        }

        logger.debug("Fetching %s from brapi.dev", ticker)

        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.get(url, params=params)

        if response.status_code != 200:
            raise BrapiError(
                f"brapi.dev returned HTTP {response.status_code} for ticker {ticker}"
            )

        payload = response.json()

        # brapi.dev envolve o resultado em {"results": [...]}
        results = payload.get("results")
        if not results:
            raise BrapiError(f"No data returned for ticker {ticker}")

        data = results[0]

        # --- Cotação ---
        price = _require_float(data, "regularMarketPrice", ticker)

        # P/VP, DY, vacância e LTV exigem plano pago na brapi — ficam zerados/None
        # no plano free. As regras já tratam pvp=0.0 e dy_12m=0.0 como "sem dado".
        dy_12m = 0.0
        pvp = 0.0
        vacancia = None
        ltv = None

        # Liquidez = volume do dia × preço — disponível no plano free
        volume = _to_float(data.get("regularMarketVolume")) or 0.0
        liquidez = volume * price

        # Variação percentual do dia — disponível no plano free
        delta_price = _to_float(data.get("regularMarketChangePercent")) or 0.0

        # Provento anunciado: pega o mais recente se foi anunciado hoje
        provento_anunciado = _extract_latest_provento(data, ticker)

        logger.info(
            "Fetched %s: price=%.2f delta=%.2f%% liquidez=%.0f",
            ticker, price, delta_price, liquidez,
        )

        return AssetSnapshot(
            ticker=ticker.upper(),
            market="BR",
            date=date.today(),
            price=price,
            dy_12m=dy_12m,
            pvp=pvp,
            vacancia=vacancia,
            ltv=ltv,
            liquidez=liquidez,
            delta_price=delta_price,
            provento_anunciado=provento_anunciado,
        )


def _require_float(data: dict, key: str, ticker: str) -> float:
    """Extrai campo obrigatório do payload. Lança BrapiError se ausente."""
    value = data.get(key)
    if value is None:
        raise BrapiError(f"Missing required field '{key}' for ticker {ticker}")
    return float(value)


def _to_float(value: object) -> float | None:
    """Converte valor para float, retornando None se vazio ou não numérico."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_latest_provento(data: dict, ticker: str) -> float | None:
    """
    Retorna o valor do provento mais recente se ele foi anunciado hoje.
    brapi.dev retorna dividends como lista de {"paymentDate": "...", "rate": ...}.
    Se o anúncio mais recente não for de hoje, retorna None — não queremos
    renotificar proventos antigos que o banco já registrou.
    """
    dividends = data.get("dividendsData", {}).get("cashDividends", [])
    if not dividends:
        return None

    # Ordena explicitamente por data decrescente — a brapi não garante a ordem
    def _parse_date(d: dict) -> date:
        raw = d.get("declarationDate") or d.get("paymentDate") or ""
        try:
            return datetime.fromisoformat(raw).date()
        except ValueError:
            return date.min  # coloca no final se não parsear

    sorted_dividends = sorted(dividends, key=_parse_date, reverse=True)
    latest = sorted_dividends[0]

    declared_date_raw = latest.get("declarationDate") or latest.get("paymentDate")
    if not declared_date_raw:
        return None

    try:
        declared_date = datetime.fromisoformat(declared_date_raw).date()
    except ValueError:
        logger.warning("Could not parse dividend date '%s' for %s", declared_date_raw, ticker)
        return None

    # Só considera provento "novo" se foi declarado hoje
    if declared_date != date.today():
        return None

    return _to_float(latest.get("rate"))
