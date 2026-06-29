"""
Entry point do bot de jornada financeira.
Invocado via: python -m app.bot.main

Usa polling (não webhook) — adequado para o MVP com até 10 usuários.
"""

import asyncio
import logging

from telegram.ext import Application

from app.bot.onboarding import build_onboarding_handler
from app.core.config import get_settings

logger = logging.getLogger(__name__)


def build_application() -> Application:
    settings = get_settings()
    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(build_onboarding_handler())
    return app


async def run() -> None:
    application = build_application()
    logger.info("Bot iniciado — aguardando mensagens...")
    await application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(run())
