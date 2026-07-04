"""
Testes unitários dos command handlers pós-onboarding.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.bot.commands import (
    _CALLBACK_ATUALIZAR_DIVIDA,
    _CALLBACK_ATUALIZAR_SAVINGS,
    _parse_amount,
    ask_atualizar_tipo,
    ask_atualizar_valor,
    cmd_atualizar,
    cmd_pausar,
    cmd_retomar,
    cmd_unknown_message,
    callback_stage_check,
)
from app.bot.onboarding import CALLBACK_COMECAR_AGORA
from telegram.ext import ConversationHandler


def make_update(text: str = "", user_id: int = 42, args: list[str] | None = None) -> MagicMock:
    update = MagicMock()
    update.effective_user.id = user_id
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


def make_context(args: list[str] | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.args = args or []
    return ctx


def make_user(stage: int = 0, onboarding_complete: bool = True, paused: bool = False) -> MagicMock:
    user = MagicMock()
    user.id = "uuid-1"
    user.stage = stage
    user.onboarding_complete = onboarding_complete
    user.paused = paused
    return user


def make_debt(initial: str = "5000", current: str = "3000") -> MagicMock:
    debt = MagicMock()
    debt.id = "debt-uuid-1"
    debt.initial_amount = Decimal(initial)
    debt.current_amount = Decimal(current)
    return debt


def make_callback_update(data: str, user_id: int = 42) -> MagicMock:
    update = MagicMock()
    update.effective_user.id = user_id
    update.callback_query.data = data
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    return update


# ---------------------------------------------------------------------------
# _parse_amount
# ---------------------------------------------------------------------------

class TestParseAmount:
    def test_integer(self):
        assert _parse_amount("3500") == Decimal("3500")

    def test_zero_is_valid(self):
        assert _parse_amount("0") == Decimal("0")

    def test_br_format(self):
        assert _parse_amount("3.500,50") == Decimal("3500.50")

    def test_negative_returns_none(self):
        assert _parse_amount("-100") is None

    def test_text_returns_none(self):
        assert _parse_amount("muito") is None


# ---------------------------------------------------------------------------
# cmd_atualizar
# ---------------------------------------------------------------------------

class TestCmdAtualizar:
    """Entry point de /atualizar — pergunta dívida ou caixinha via botões."""

    def _patch(self, user):
        mock_factory = MagicMock()
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_repo = AsyncMock()
        mock_repo.get_by_chat_id = AsyncMock(return_value=user)
        return mock_factory, mock_repo

    async def test_stage0_shows_type_buttons(self):
        update = make_update()
        ctx = make_context()
        user = make_user(stage=0)
        mock_factory, mock_repo = self._patch(user)

        with patch("app.core.database.AsyncSessionFactory", mock_factory):
            with patch("app.bot.commands.UserRepository", return_value=mock_repo):
                result = await cmd_atualizar(update, ctx)

        assert result == 0  # ASK_ATUALIZAR_TIPO
        update.message.reply_text.assert_called_once()
        keyboard = update.message.reply_text.call_args.kwargs["reply_markup"]
        callbacks = {btn.callback_data for row in keyboard.inline_keyboard for btn in row}
        assert callbacks == {_CALLBACK_ATUALIZAR_DIVIDA, _CALLBACK_ATUALIZAR_SAVINGS}

    async def test_stage1_shows_type_buttons(self):
        update = make_update()
        ctx = make_context()
        user = make_user(stage=1)
        mock_factory, mock_repo = self._patch(user)

        with patch("app.core.database.AsyncSessionFactory", mock_factory):
            with patch("app.bot.commands.UserRepository", return_value=mock_repo):
                result = await cmd_atualizar(update, ctx)

        assert result == 0  # ASK_ATUALIZAR_TIPO

    async def test_stage2_blocks_with_message(self):
        update = make_update()
        ctx = make_context()
        user = make_user(stage=2)
        mock_factory, mock_repo = self._patch(user)

        with patch("app.core.database.AsyncSessionFactory", mock_factory):
            with patch("app.bot.commands.UserRepository", return_value=mock_repo):
                result = await cmd_atualizar(update, ctx)

        assert result == ConversationHandler.END
        msg = update.message.reply_text.call_args.args[0]
        assert "Estágio 2" in msg

    async def test_user_not_found_replies_with_start_hint(self):
        update = make_update()
        ctx = make_context()
        mock_factory, mock_repo = self._patch(user=None)

        with patch("app.core.database.AsyncSessionFactory", mock_factory):
            with patch("app.bot.commands.UserRepository", return_value=mock_repo):
                result = await cmd_atualizar(update, ctx)

        assert result == ConversationHandler.END
        msg = update.message.reply_text.call_args.args[0]
        assert "/start" in msg


class TestAskAtualizarTipo:
    """Callback do botão dívida/caixinha — pergunta o valor."""

    def _patch(self, user):
        mock_factory = MagicMock()
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_repo = AsyncMock()
        mock_repo.get_by_chat_id = AsyncMock(return_value=user)
        return mock_factory, mock_repo

    async def test_divida_stage0_asks_amount(self):
        update = make_callback_update(_CALLBACK_ATUALIZAR_DIVIDA)
        ctx = make_context()
        ctx.user_data = {}
        user = make_user(stage=0)
        mock_factory, mock_repo = self._patch(user)

        with patch("app.core.database.AsyncSessionFactory", mock_factory):
            with patch("app.bot.commands.UserRepository", return_value=mock_repo):
                result = await ask_atualizar_tipo(update, ctx)

        assert result == 1  # ASK_ATUALIZAR_VALOR
        assert ctx.user_data["atualizar_tipo"] == "divida"

    async def test_divida_wrong_stage_ends(self):
        update = make_callback_update(_CALLBACK_ATUALIZAR_DIVIDA)
        ctx = make_context()
        ctx.user_data = {}
        user = make_user(stage=1)
        mock_factory, mock_repo = self._patch(user)

        with patch("app.core.database.AsyncSessionFactory", mock_factory):
            with patch("app.bot.commands.UserRepository", return_value=mock_repo):
                result = await ask_atualizar_tipo(update, ctx)

        assert result == ConversationHandler.END

    async def test_savings_stage1_asks_amount(self):
        update = make_callback_update(_CALLBACK_ATUALIZAR_SAVINGS)
        ctx = make_context()
        ctx.user_data = {}
        user = make_user(stage=1)
        mock_factory, mock_repo = self._patch(user)

        with patch("app.core.database.AsyncSessionFactory", mock_factory):
            with patch("app.bot.commands.UserRepository", return_value=mock_repo):
                result = await ask_atualizar_tipo(update, ctx)

        assert result == 1  # ASK_ATUALIZAR_VALOR
        assert ctx.user_data["atualizar_tipo"] == "savings"

    async def test_savings_wrong_stage_ends(self):
        update = make_callback_update(_CALLBACK_ATUALIZAR_SAVINGS)
        ctx = make_context()
        ctx.user_data = {}
        user = make_user(stage=0)
        mock_factory, mock_repo = self._patch(user)

        with patch("app.core.database.AsyncSessionFactory", mock_factory):
            with patch("app.bot.commands.UserRepository", return_value=mock_repo):
                result = await ask_atualizar_tipo(update, ctx)

        assert result == ConversationHandler.END


class TestAskAtualizarValor:
    """Valor informado — atualiza dívida ou caixinha conforme o tipo escolhido."""

    def _patch(self, user, debt=None):
        mock_factory = MagicMock()
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_repo = AsyncMock()
        mock_repo.get_by_chat_id = AsyncMock(return_value=user)
        mock_repo.add_debt_payment = AsyncMock(return_value=debt)
        mock_repo.add_savings = AsyncMock(return_value=user)
        mock_repo.promote_stage = AsyncMock()
        return mock_factory, mock_repo

    async def test_invalid_value_stays_on_state(self):
        update = make_update("abc")
        ctx = make_context()
        ctx.user_data = {"atualizar_tipo": "divida"}
        result = await ask_atualizar_valor(update, ctx)
        assert result == 1  # ASK_ATUALIZAR_VALOR
        assert "Não entendi" in update.message.reply_text.call_args.args[0]

    async def test_divida_payment_updates_and_shows_remaining(self):
        update = make_update("200")
        ctx = make_context()
        ctx.user_data = {"atualizar_tipo": "divida"}
        user = make_user(stage=0)
        debt = make_debt(initial="5000", current="2800")
        mock_factory, mock_repo = self._patch(user, debt=debt)

        with patch("app.core.database.AsyncSessionFactory", mock_factory):
            with patch("app.bot.commands.UserRepository", return_value=mock_repo):
                result = await ask_atualizar_valor(update, ctx)

        assert result == ConversationHandler.END
        mock_repo.add_debt_payment.assert_called_once_with(user.id, Decimal("200"))
        msg = update.message.reply_text.call_args.args[0]
        assert "2.800,00" in msg
        assert "atualizar_tipo" not in ctx.user_data

    async def test_divida_fully_paid_promotes_to_stage1(self):
        update = make_update("2800")
        ctx = make_context()
        ctx.user_data = {"atualizar_tipo": "divida"}
        user = make_user(stage=0)
        debt = make_debt(initial="5000", current="0")
        mock_factory, mock_repo = self._patch(user, debt=debt)

        with patch("app.core.database.AsyncSessionFactory", mock_factory):
            with patch("app.bot.commands.UserRepository", return_value=mock_repo):
                result = await ask_atualizar_valor(update, ctx)

        assert result == ConversationHandler.END
        mock_repo.promote_stage.assert_called_once_with(user.id, new_stage=1)
        msg = update.message.reply_text.call_args.args[0]
        assert "Estágio 1" in msg

    async def test_divida_no_active_debt_ends(self):
        update = make_update("200")
        ctx = make_context()
        ctx.user_data = {"atualizar_tipo": "divida"}
        user = make_user(stage=0)
        mock_factory, mock_repo = self._patch(user, debt=None)

        with patch("app.core.database.AsyncSessionFactory", mock_factory):
            with patch("app.bot.commands.UserRepository", return_value=mock_repo):
                result = await ask_atualizar_valor(update, ctx)

        assert result == ConversationHandler.END
        msg = update.message.reply_text.call_args.args[0]
        assert "/start" in msg

    async def test_savings_updates_and_shows_total(self):
        update = make_update("100")
        ctx = make_context()
        ctx.user_data = {"atualizar_tipo": "savings"}
        user = make_user(stage=1)
        user.savings_amount = Decimal("300")
        mock_factory, mock_repo = self._patch(user)

        with patch("app.core.database.AsyncSessionFactory", mock_factory):
            with patch("app.bot.commands.UserRepository", return_value=mock_repo):
                result = await ask_atualizar_valor(update, ctx)

        assert result == ConversationHandler.END
        mock_repo.add_savings.assert_called_once_with(user.id, Decimal("100"))
        msg = update.message.reply_text.call_args.args[0]
        assert "300,00" in msg

    async def test_user_not_found_ends(self):
        update = make_update("100")
        ctx = make_context()
        ctx.user_data = {"atualizar_tipo": "savings"}
        mock_factory, mock_repo = self._patch(user=None)

        with patch("app.core.database.AsyncSessionFactory", mock_factory):
            with patch("app.bot.commands.UserRepository", return_value=mock_repo):
                result = await ask_atualizar_valor(update, ctx)

        assert result == ConversationHandler.END
        msg = update.message.reply_text.call_args.args[0]
        assert "/start" in msg


# ---------------------------------------------------------------------------
# cmd_pausar / cmd_retomar
# ---------------------------------------------------------------------------

class TestCmdPausar:
    def _patch(self, user):
        mock_factory = MagicMock()
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_repo = AsyncMock()
        mock_repo.get_by_chat_id = AsyncMock(return_value=user)
        mock_repo.set_paused = AsyncMock()
        return mock_factory, mock_repo

    async def test_pauses_active_user(self):
        update = make_update()
        ctx = make_context()
        user = make_user(paused=False)
        mock_factory, mock_repo = self._patch(user)

        with patch("app.core.database.AsyncSessionFactory", mock_factory):
            with patch("app.bot.commands.UserRepository", return_value=mock_repo):
                await cmd_pausar(update, ctx)

        mock_repo.set_paused.assert_called_once_with(user.id, paused=True)
        msg = update.message.reply_text.call_args.args[0]
        assert "pausados" in msg.lower()

    async def test_already_paused_is_noop(self):
        update = make_update()
        ctx = make_context()
        user = make_user(paused=True)
        mock_factory, mock_repo = self._patch(user)

        with patch("app.core.database.AsyncSessionFactory", mock_factory):
            with patch("app.bot.commands.UserRepository", return_value=mock_repo):
                await cmd_pausar(update, ctx)

        mock_repo.set_paused.assert_not_called()

    async def test_user_not_found_replies_with_start_hint(self):
        update = make_update()
        ctx = make_context()
        mock_factory, mock_repo = self._patch(user=None)

        with patch("app.core.database.AsyncSessionFactory", mock_factory):
            with patch("app.bot.commands.UserRepository", return_value=mock_repo):
                await cmd_pausar(update, ctx)

        msg = update.message.reply_text.call_args.args[0]
        assert "/start" in msg


class TestCmdRetomar:
    def _patch(self, user):
        mock_factory = MagicMock()
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_repo = AsyncMock()
        mock_repo.get_by_chat_id = AsyncMock(return_value=user)
        mock_repo.set_paused = AsyncMock()
        return mock_factory, mock_repo

    async def test_resumes_paused_user(self):
        update = make_update()
        ctx = make_context()
        user = make_user(paused=True)
        mock_factory, mock_repo = self._patch(user)

        with patch("app.core.database.AsyncSessionFactory", mock_factory):
            with patch("app.bot.commands.UserRepository", return_value=mock_repo):
                await cmd_retomar(update, ctx)

        mock_repo.set_paused.assert_called_once_with(user.id, paused=False)
        msg = update.message.reply_text.call_args.args[0]
        assert "retomados" in msg.lower()

    async def test_already_active_is_noop(self):
        update = make_update()
        ctx = make_context()
        user = make_user(paused=False)
        mock_factory, mock_repo = self._patch(user)

        with patch("app.core.database.AsyncSessionFactory", mock_factory):
            with patch("app.bot.commands.UserRepository", return_value=mock_repo):
                await cmd_retomar(update, ctx)

        mock_repo.set_paused.assert_not_called()

    async def test_user_not_found_replies_with_start_hint(self):
        update = make_update()
        ctx = make_context()
        mock_factory, mock_repo = self._patch(user=None)

        with patch("app.core.database.AsyncSessionFactory", mock_factory):
            with patch("app.bot.commands.UserRepository", return_value=mock_repo):
                await cmd_retomar(update, ctx)

        msg = update.message.reply_text.call_args.args[0]
        assert "/start" in msg


# ---------------------------------------------------------------------------
# callback_stage_check
# ---------------------------------------------------------------------------

class TestCallbackStageCheck:
    def make_callback_update(self, data: str, user_id: int = 42) -> MagicMock:
        update = MagicMock()
        update.effective_user.id = user_id
        update.callback_query.data = data
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        return update

    def _patch(self, user):
        mock_factory = MagicMock()
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_repo = AsyncMock()
        mock_repo.get_by_chat_id = AsyncMock(return_value=user)
        mock_repo.promote_stage = AsyncMock()
        return mock_factory, mock_repo

    async def test_sim_promotes_to_stage2(self):
        update = self.make_callback_update("stage_check_sim")
        user = make_user(stage=1)
        mock_factory, mock_repo = self._patch(user)

        with patch("app.core.database.AsyncSessionFactory", mock_factory):
            with patch("app.bot.commands.UserRepository", return_value=mock_repo):
                await callback_stage_check(update, MagicMock())

        mock_repo.promote_stage.assert_called_once_with(user.id, new_stage=2)
        msg = update.callback_query.edit_message_text.call_args.args[0]
        assert "Estágio 2" in msg

    async def test_nao_keeps_stage1_and_replies(self):
        update = self.make_callback_update("stage_check_nao")
        user = make_user(stage=1)
        mock_factory, mock_repo = self._patch(user)

        with patch("app.core.database.AsyncSessionFactory", mock_factory):
            with patch("app.bot.commands.UserRepository", return_value=mock_repo):
                await callback_stage_check(update, MagicMock())

        mock_repo.promote_stage.assert_not_called()
        msg = update.callback_query.edit_message_text.call_args.args[0]
        assert "semana" in msg.lower()

    async def test_wrong_stage_ignores_callback(self):
        update = self.make_callback_update("stage_check_sim")
        user = make_user(stage=0)  # já deveria estar em stage 0, não 1
        mock_factory, mock_repo = self._patch(user)

        with patch("app.core.database.AsyncSessionFactory", mock_factory):
            with patch("app.bot.commands.UserRepository", return_value=mock_repo):
                await callback_stage_check(update, MagicMock())

        mock_repo.promote_stage.assert_not_called()


# ---------------------------------------------------------------------------
# cmd_unknown_message
# ---------------------------------------------------------------------------

class TestCmdUnknownMessage:
    async def test_shows_comecar_agora_inline_button(self):
        update = make_update()
        await cmd_unknown_message(update, MagicMock())

        update.message.reply_text.assert_called_once()
        call_kwargs = update.message.reply_text.call_args.kwargs
        keyboard = call_kwargs["reply_markup"]
        button = keyboard.inline_keyboard[0][0]
        assert button.callback_data == CALLBACK_COMECAR_AGORA

    async def test_message_mentions_leveling(self):
        update = make_update()
        await cmd_unknown_message(update, MagicMock())

        msg = update.message.reply_text.call_args.args[0]
        assert "Leveling" in msg
