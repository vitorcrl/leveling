"""
Runner autônomo para o pipeline de FIIs.
Roda como processo separado — sem FastAPI, sem APScheduler pesado.
Invocado via: python -m app.scheduler.fii_runner
"""

import asyncio
import logging
from datetime import date

from telegram import Bot

from app.adapters.data.brapi_adapter import BrapiDataAdapter
from app.adapters.delivery.telegram_adapter import TelegramAdapter
from app.adapters.narrators.claude_haiku_narrator import ClaudeHaikuNarrator
from app.adapters.rules.fii_rule_set import FIIRuleSet
from app.adapters.scoring.weighted_score_engine import WeightedScoreEngine
from app.core.config import get_settings
from app.domain.models_asset import AssetSnapshot
from app.pipeline.asset_pipeline import AssetPipeline
from app.repositories.fii_repository import FIIRepository

logger = logging.getLogger(__name__)


async def _enrich_and_save(
    snapshot: AssetSnapshot,
    repo: FIIRepository,
) -> AssetSnapshot:
    """
    Preenche os deltas comparando com o snapshot da semana anterior,
    depois persiste o snapshot atual no banco.
    """
    previous = await repo.get_previous_snapshot(snapshot.ticker, before=snapshot.date)
    if previous is not None:
        snapshot.delta_dy = snapshot.dy_12m - float(previous.dy_12m or 0)
        snapshot.delta_price = (
            (snapshot.price - float(previous.price)) / float(previous.price) * 100
            if previous.price
            else 0.0
        )
        if snapshot.vacancia is not None and previous.vacancia is not None:
            snapshot.delta_vacancia = snapshot.vacancia - float(previous.vacancia)
        if previous.pvp is not None:
            snapshot.delta_pvp = snapshot.pvp - float(previous.pvp)

    await repo.save_snapshot(snapshot)
    return snapshot


async def run_daily(chat_id: int | str, run_date: date | None = None) -> None:
    from app.core.database import AsyncSessionFactory

    settings = get_settings()
    tickers = settings.fii_watchlist_tickers
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)

    async with AsyncSessionFactory() as session:
        repo = FIIRepository(session)

        # ClaudeHaikuNarrator já implementa o zero-token path internamente:
        # se não há alertas, retorna mensagem padrão sem chamar a API.
        narrator = ClaudeHaikuNarrator(api_key=settings.ANTHROPIC_API_KEY)

        pipeline = AssetPipeline(
            data=BrapiDataAdapter(
                base_url=settings.BRAPI_BASE_URL,
                token=settings.BRAPI_TOKEN,
            ),
            rules=FIIRuleSet(settings=settings),
            scorer=WeightedScoreEngine(),
            narrator=narrator,
            delivery=TelegramAdapter(bot),
        )

        async def enrich(snapshot: AssetSnapshot) -> AssetSnapshot:
            return await _enrich_and_save(snapshot, repo)

        await pipeline.run(tickers=tickers, chat_id=chat_id, run_date=run_date, enrich_snapshot=enrich)


if __name__ == "__main__":
    import os
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_daily(chat_id=os.environ["TELEGRAM_CHAT_ID"]))
