from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram.error import TelegramError

from app.adapters.delivery.telegram_adapter import TelegramAdapter, TelegramDeliveryError


def make_bot() -> MagicMock:
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock())
    return bot


@pytest.fixture
def bot():
    return make_bot()


@pytest.fixture
def adapter(bot):
    return TelegramAdapter(bot)


class TestTelegramAdapterSend:
    async def test_calls_send_message_with_chat_id(self, adapter, bot):
        await adapter.send("Olá, mundo!", chat_id=123456789)
        bot.send_message.assert_called_once()
        call_kwargs = bot.send_message.call_args.kwargs
        assert call_kwargs["chat_id"] == 123456789

    async def test_sends_correct_text(self, adapter, bot):
        await adapter.send("Mensagem de teste", chat_id=42)
        call_kwargs = bot.send_message.call_args.kwargs
        assert call_kwargs["text"] == "Mensagem de teste"

    async def test_uses_markdown_parse_mode(self, adapter, bot):
        await adapter.send("*negrito*", chat_id=42)
        call_kwargs = bot.send_message.call_args.kwargs
        assert call_kwargs["parse_mode"] == "Markdown"

    async def test_raises_delivery_error_on_telegram_error(self, adapter, bot):
        bot.send_message = AsyncMock(side_effect=TelegramError("chat not found"))
        with pytest.raises(TelegramDeliveryError):
            await adapter.send("Mensagem", chat_id=999)

    async def test_delivery_error_message_contains_original(self, adapter, bot):
        bot.send_message = AsyncMock(side_effect=TelegramError("Forbidden: bot was blocked"))
        with pytest.raises(TelegramDeliveryError, match="Forbidden"):
            await adapter.send("Mensagem", chat_id=999)

    async def test_chat_id_can_be_string(self, adapter, bot):
        await adapter.send("Olá!", chat_id="@meucanal")
        call_kwargs = bot.send_message.call_args.kwargs
        assert call_kwargs["chat_id"] == "@meucanal"

    async def test_implements_delivery_port(self):
        from app.domain.ports import DeliveryPort
        assert isinstance(TelegramAdapter(make_bot()), DeliveryPort)
