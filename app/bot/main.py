"""
Entry point unificado do bot de jornada financeira.
Invocado via: python -m app.bot.main

Sobe três coisas no mesmo processo asyncio:
  1. Bot Telegram com polling (onboarding + comandos)
  2. Weekly digest semanal por usuário — roda todo dia às 8h, mas cada usuário
     só recebe no seu próprio digest_weekday (ver /diadigest e weekly_runner.py)
  3. Pipeline de FIIs para usuários stage-2 (todo sábado às 10h)

Sem dependência de APScheduler ou Celery — asyncio puro com loop de 60s.
"""

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram.ext import Application, MessageHandler, filters

from app.adapters.delivery.telegram_adapter import TelegramAdapter
from app.adapters.narrators.journey_narrator import ClaudeJourneyNarrator
from app.bot.commands import build_atualizar_handler, build_command_handlers, cmd_unknown_message
from app.bot.onboarding import build_onboarding_handler
from app.core.config import get_settings
from app.scheduler.journey_runner import run_for_all_stage2_users
from app.scheduler.weekly_runner import send_weekly_digest

logger = logging.getLogger(__name__)

_WEEKLY_DIGEST_HOUR = 10     # horário de Brasília — dispara todo dia, filtro de dia é por usuário
_FII_PIPELINE_WEEKDAY = 5    # sábado
_FII_PIPELINE_HOUR = 10      # horário de Brasília

_BRT = ZoneInfo("America/Sao_Paulo")


def _should_run_at_hour(hour: int, last_run: datetime | None) -> bool:
    now = datetime.now(_BRT)
    if now.hour != hour:
        return False
    if last_run is None:
        return True
    return (now - last_run).total_seconds() > 3600


def _should_run(weekday: int, hour: int, last_run: datetime | None) -> bool:
    now = datetime.now(_BRT)
    if now.weekday() != weekday or now.hour != hour:
        return False
    if last_run is None:
        return True
    return (now - last_run).total_seconds() > 3600


async def _scheduler_loop(bot) -> None:
    delivery = TelegramAdapter(bot)
    narrator = ClaudeJourneyNarrator()
    last_weekly: datetime | None = None
    last_fii: datetime | None = None

    while True:
        await asyncio.sleep(60)
        now = datetime.now(_BRT)

        if _should_run_at_hour(_WEEKLY_DIGEST_HOUR, last_weekly):
            logger.info("scheduler: firing weekly digest (weekday=%s)", now.weekday())
            try:
                result = await send_weekly_digest(
                    delivery, bot=bot, weekday=now.weekday(), narrator=narrator
                )
                logger.info("scheduler: weekly digest done — %s", result)
                last_weekly = now
            except Exception:
                logger.exception("scheduler: weekly digest failed")

        if _should_run(_FII_PIPELINE_WEEKDAY, _FII_PIPELINE_HOUR, last_fii):
            logger.info("scheduler: firing FII pipeline")
            try:
                result = await run_for_all_stage2_users(bot=bot)
                logger.info("scheduler: FII pipeline done — %s", result)
                last_fii = now
            except Exception:
                logger.exception("scheduler: FII pipeline failed")


def build_application() -> Application:
    settings = get_settings()
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(build_onboarding_handler())
    app.add_handler(build_atualizar_handler())
    for handler in build_command_handlers():
        app.add_handler(handler)
    # deve ser o último — captura qualquer texto fora de conversa ativa
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_unknown_message))
    return app


async def run() -> None:
    application = build_application()

    async with application:
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)
        logger.info("Bot iniciado — aguardando mensagens...")

        await _scheduler_loop(application.bot)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(run())
