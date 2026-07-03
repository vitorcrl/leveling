"""
Runner do pipeline de FIIs para usuários no Estágio 2.

Busca todos os usuários com stage=2 e onboarding completo e envia
o digest semanal de FIIs para cada um usando a watchlist global.

Invocado via: python -m app.scheduler.journey_runner
Ou pelo entry point unificado em app/bot/main.py (todo sábado às 10h).
"""

import asyncio
import logging
from datetime import date

from telegram import Bot

from app.adapters.data.brapi_adapter import BrapiDataAdapter
from app.adapters.delivery.telegram_adapter import TelegramAdapter
from app.adapters.narrators.claude_haiku_narrator import ClaudeHaikuNarrator
from app.adapters.narrators.template_narrator import TemplateNarrator
from app.adapters.rules.asset_rule_set import AssetRuleSet
from app.adapters.scoring.weighted_score_engine import WeightedScoreEngine
from app.core.config import get_settings
from app.domain.models_asset import AssetSnapshot
from app.domain.ports import NarratorPort
from app.pipeline.asset_pipeline import AssetPipeline
from app.repositories.asset_repository import AssetRepository
from app.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)


async def _enrich_and_save(
    snapshot: AssetSnapshot,
    repo: AssetRepository,
) -> AssetSnapshot:
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


async def _run_for_user(
    chat_id: int | str,
    pipeline: AssetPipeline,
    asset_repo: AssetRepository,
    run_date: date | None,
) -> None:
    async def enrich(snapshot: AssetSnapshot) -> AssetSnapshot:
        return await _enrich_and_save(snapshot, asset_repo)

    await pipeline.run(
        tickers=get_settings().watchlist_tickers,
        chat_id=chat_id,
        run_date=run_date,
        enrich_snapshot=enrich,
    )


async def run_for_all_stage2_users(
    run_date: date | None = None,
    bot: Bot | None = None,
) -> dict[str, int]:
    from app.core.database import AsyncSessionFactory

    settings = get_settings()
    owns_bot = bot is None

    async def _run(bot: Bot) -> dict[str, int]:
        delivery = TelegramAdapter(bot)
        narrator: NarratorPort = (
            ClaudeHaikuNarrator(api_key=settings.ANTHROPIC_API_KEY)
            if settings.USE_AI_NARRATOR
            else TemplateNarrator()
        )
        pipeline = AssetPipeline(
            data=BrapiDataAdapter(base_url=settings.BRAPI_BASE_URL, token=settings.BRAPI_TOKEN),
            rules=AssetRuleSet(settings=settings),
            scorer=WeightedScoreEngine(),
            narrator=narrator,
            delivery=delivery,
        )

        sent = errors = 0

        async with AsyncSessionFactory() as session:
            users = await UserRepository(session).get_all_active()
            stage2_users = [u for u in users if u.stage == 2]

            logger.info("journey_runner: %d stage-2 users found", len(stage2_users))

            for user in stage2_users:
                async with AsyncSessionFactory() as asset_session:
                    asset_repo = AssetRepository(asset_session)
                    try:
                        await _run_for_user(user.telegram_chat_id, pipeline, asset_repo, run_date)
                        sent += 1
                        logger.info(
                            "journey_runner: sent FII digest to chat_id=%s",
                            user.telegram_chat_id,
                        )
                    except Exception:
                        errors += 1
                        logger.exception(
                            "journey_runner: failed for chat_id=%s", user.telegram_chat_id
                        )

        return {"sent": sent, "errors": errors}

    if owns_bot:
        async with Bot(token=settings.TELEGRAM_BOT_TOKEN) as owned_bot:
            return await _run(owned_bot)
    return await _run(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(run_for_all_stage2_users())
