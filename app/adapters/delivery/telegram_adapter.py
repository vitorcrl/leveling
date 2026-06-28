from telegram import Bot
from telegram.error import TelegramError


class TelegramDeliveryError(Exception):
    pass


class TelegramAdapter:
    """
    Implementa DeliveryPort via python-telegram-bot.

    Recebe um Bot já configurado (injetado pelo bot runner) em vez de
    criar sua própria conexão HTTP — um único cliente Telegram no processo.

    Uso:
        bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
        adapter = TelegramAdapter(bot)
        await adapter.send("Olá!", chat_id=123456789)
    """

    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def send(self, message: str, chat_id: int | str) -> None:
        try:
            await self._bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="Markdown",
            )
        except TelegramError as exc:
            raise TelegramDeliveryError(str(exc)) from exc
