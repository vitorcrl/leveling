"""
Testes unitários dos command handlers pós-onboarding.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.bot.commands import (
    _parse_amount,
    cmd_atualizar,
    cmd_pausar,
    cmd_retomar,
    callback_stage_check,
)


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
    debt.initial_amount = Decimal(initial)
    debt.current_amount = Decimal(current)
    return debt


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
    def _patch(self, user, debt=None):
        mock_factory = MagicMock()
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_repo = AsyncMock()
        mock_repo.get_by_chat_id = AsyncMock(return_value=user)
        mock_repo.get_active_debt = AsyncMock(return_value=debt)
        mock_repo.update_debt_amount = AsyncMock()
        mock_repo.promote_stage = AsyncMock()
        return mock_factory, mock_repo

    async def test_no_args_replies_with_usage(self):
        update = make_update()
        ctx = make_context(args=[])
        await cmd_atualizar(update, ctx)
        update.message.reply_text.assert_called_once()
        assert "/atualizar" in update.message.reply_text.call_args.args[0]

    async def test_invalid_value_replies_with_error(self):
        update = make_update()
        ctx = make_context(args=["abc"])
        await cmd_atualizar(update, ctx)
        update.message.reply_text.assert_called_once()
        assert "Não entendi" in update.message.reply_text.call_args.args[0]

    async def test_zero_promotes_to_stage1(self):
        update = make_update()
        ctx = make_context(args=["0"])
        user = make_user(stage=0)
        debt = make_debt()
        mock_factory, mock_repo = self._patch(user, debt=debt)

        with patch("app.core.database.AsyncSessionFactory", mock_factory):
            with patch("app.bot.commands.UserRepository", return_value=mock_repo):
                await cmd_atualizar(update, ctx)

        mock_repo.promote_stage.assert_called_once_with(user.id, new_stage=1)
        msg = update.message.reply_text.call_args.args[0]
        assert "Estágio 1" in msg

    async def test_zero_without_debt_blocks_promotion(self):
        update = make_update()
        ctx = make_context(args=["0"])
        user = make_user(stage=0)
        mock_factory, mock_repo = self._patch(user, debt=None)

        with patch("app.core.database.AsyncSessionFactory", mock_factory):
            with patch("app.bot.commands.UserRepository", return_value=mock_repo):
                await cmd_atualizar(update, ctx)

        mock_repo.promote_stage.assert_not_called()
        msg = update.message.reply_text.call_args.args[0]
        assert "/start" in msg

    async def test_valid_amount_updates_debt(self):
        update = make_update()
        ctx = make_context(args=["3500"])
        user = make_user(stage=0)
        debt = make_debt(initial="5000", current="3500")
        mock_factory, mock_repo = self._patch(user, debt=debt)

        with patch("app.core.database.AsyncSessionFactory", mock_factory):
            with patch("app.bot.commands.UserRepository", return_value=mock_repo):
                await cmd_atualizar(update, ctx)

        mock_repo.update_debt_amount.assert_called_once_with(user.id, Decimal("3500"))
        msg = update.message.reply_text.call_args.args[0]
        assert "atualizado" in msg.lower()

    async def test_reply_uses_br_number_format(self):
        update = make_update()
        ctx = make_context(args=["3500"])
        user = make_user(stage=0)
        debt = make_debt(initial="5000", current="3500")
        mock_factory, mock_repo = self._patch(user, debt=debt)

        with patch("app.core.database.AsyncSessionFactory", mock_factory):
            with patch("app.bot.commands.UserRepository", return_value=mock_repo):
                await cmd_atualizar(update, ctx)

        msg = update.message.reply_text.call_args.args[0]
        assert "5.000,00" in msg
        assert "3.500,00" in msg
        assert "5,000.00" not in msg

    async def test_wrong_stage_replies_with_stage_info(self):
        update = make_update()
        ctx = make_context(args=["500"])
        user = make_user(stage=1)
        mock_factory, mock_repo = self._patch(user)

        with patch("app.core.database.AsyncSessionFactory", mock_factory):
            with patch("app.bot.commands.UserRepository", return_value=mock_repo):
                await cmd_atualizar(update, ctx)

        mock_repo.update_debt_amount.assert_not_called()
        msg = update.message.reply_text.call_args.args[0]
        assert "Estágio 0" in msg

    async def test_user_not_found_replies_with_start_hint(self):
        update = make_update()
        ctx = make_context(args=["1000"])
        mock_factory, mock_repo = self._patch(user=None)

        with patch("app.core.database.AsyncSessionFactory", mock_factory):
            with patch("app.bot.commands.UserRepository", return_value=mock_repo):
                await cmd_atualizar(update, ctx)

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
