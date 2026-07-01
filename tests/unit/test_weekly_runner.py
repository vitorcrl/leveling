"""
Testes unitários do scheduler semanal.
Sem banco de dados, sem Telegram real.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from datetime import datetime, timedelta, timezone

from app.scheduler.weekly_runner import (
    _build_stage0_message,
    _build_stage1_message,
    _build_stage2_message,
    _fmt,
    _should_send_stage_check,
    send_weekly_digest,
)


def make_user(stage: int = 0, budget: str = "500", stage_check_sent_at=None) -> MagicMock:
    user = MagicMock()
    user.id = "user-uuid-1"
    user.telegram_chat_id = 123456
    user.stage = stage
    user.monthly_budget = Decimal(budget)
    user.risk_profile = "conservador"
    user.stage_check_sent_at = stage_check_sent_at
    return user


def make_debt(initial: str = "5000", current: str = "3000") -> MagicMock:
    debt = MagicMock()
    debt.initial_amount = Decimal(initial)
    debt.current_amount = Decimal(current)
    return debt


def make_goal(name: str = "Netflix", monthly: str = "50") -> MagicMock:
    goal = MagicMock()
    goal.name = name
    goal.goal_value_monthly = Decimal(monthly)
    return goal


# ---------------------------------------------------------------------------
# _fmt helper
# ---------------------------------------------------------------------------

class TestFmt:
    def test_formats_integer(self):
        assert _fmt(Decimal("1000")) == "R$ 1.000,00"

    def test_formats_decimal(self):
        assert _fmt(Decimal("129.90")) == "R$ 129,90"

    def test_none_returns_dash(self):
        assert _fmt(None) == "—"


# ---------------------------------------------------------------------------
# Construtores de mensagem por stage
# ---------------------------------------------------------------------------

class TestBuildStage0Message:
    def test_contains_stage_label(self):
        msg = _build_stage0_message(make_user(0), make_debt(), make_goal())
        assert "Estágio 0" in msg

    def test_shows_debt_amounts(self):
        msg = _build_stage0_message(make_user(0), make_debt("5000", "3000"), None)
        assert "5.000" in msg
        assert "3.000" in msg

    def test_shows_paid_percentage(self):
        msg = _build_stage0_message(make_user(0), make_debt("5000", "3000"), None)
        assert "40,0%" in msg  # 2000/5000 = 40%

    def test_shows_goal_name(self):
        msg = _build_stage0_message(make_user(0), make_debt(), make_goal("Academia"))
        assert "Academia" in msg

    def test_no_debt_shows_update_prompt(self):
        msg = _build_stage0_message(make_user(0), None, None)
        assert "Atualize" in msg


class TestBuildStage1Message:
    def test_contains_stage_label(self):
        msg = _build_stage1_message(make_user(1), make_goal())
        assert "Estágio 1" in msg

    def test_shows_months_to_target(self):
        # R$500/mês → 2 meses para R$1.000
        msg = _build_stage1_message(make_user(1, budget="500"), None)
        assert "2" in msg

    def test_zero_budget_no_crash(self):
        user = make_user(1)
        user.monthly_budget = Decimal("0")
        msg = _build_stage1_message(user, None)
        assert "Estágio 1" in msg

    def test_shows_goal(self):
        msg = _build_stage1_message(make_user(1), make_goal("Viagem"))
        assert "Viagem" in msg


class TestBuildStage2Message:
    def test_contains_stage_label(self):
        msg = _build_stage2_message(make_user(2), make_goal())
        assert "Estágio 2" in msg

    def test_shows_profile(self):
        msg = _build_stage2_message(make_user(2), None)
        assert "conservador" in msg

    def test_shows_goal(self):
        msg = _build_stage2_message(make_user(2), make_goal("Monster"))
        assert "Monster" in msg


# ---------------------------------------------------------------------------
# send_weekly_digest — fluxo completo mockado
# ---------------------------------------------------------------------------

class TestSendWeeklyDigest:
    def _make_delivery(self) -> MagicMock:
        delivery = MagicMock()
        delivery.send = AsyncMock()
        return delivery

    async def test_sends_to_all_active_users(self):
        users = [make_user(0), make_user(1), make_user(2)]
        users[1].telegram_chat_id = 111
        users[2].telegram_chat_id = 222

        with patch("app.core.database.AsyncSessionFactory") as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_repo = AsyncMock()
            mock_repo.get_all_active = AsyncMock(return_value=users)
            mock_repo.get_active_debt = AsyncMock(return_value=make_debt())
            mock_repo.get_active_goal = AsyncMock(return_value=make_goal())

            with patch("app.scheduler.weekly_runner.UserRepository", return_value=mock_repo):
                delivery = self._make_delivery()
                result = await send_weekly_digest(delivery)

        assert result["sent"] == 3
        assert result["errors"] == 0
        assert delivery.send.call_count == 3

    async def test_counts_errors_without_raising(self):
        users = [make_user(0), make_user(1)]
        users[1].telegram_chat_id = 999

        with patch("app.core.database.AsyncSessionFactory") as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_repo = AsyncMock()
            mock_repo.get_all_active = AsyncMock(return_value=users)
            mock_repo.get_active_debt = AsyncMock(return_value=None)
            mock_repo.get_active_goal = AsyncMock(return_value=None)

            delivery = self._make_delivery()
            delivery.send = AsyncMock(side_effect=[None, Exception("Telegram error")])

            with patch("app.scheduler.weekly_runner.UserRepository", return_value=mock_repo):
                result = await send_weekly_digest(delivery)

        assert result["sent"] == 1
        assert result["errors"] == 1

    async def test_no_users_returns_zeros(self):
        with patch("app.core.database.AsyncSessionFactory") as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_repo = AsyncMock()
            mock_repo.get_all_active = AsyncMock(return_value=[])

            with patch("app.scheduler.weekly_runner.UserRepository", return_value=mock_repo):
                delivery = self._make_delivery()
                result = await send_weekly_digest(delivery)

        assert result == {"sent": 0, "skipped": 0, "errors": 0}
        delivery.send.assert_not_called()

    async def test_stage0_message_sent_to_correct_chat_id(self):
        user = make_user(0)
        user.telegram_chat_id = 42

        with patch("app.core.database.AsyncSessionFactory") as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_repo = AsyncMock()
            mock_repo.get_all_active = AsyncMock(return_value=[user])
            mock_repo.get_active_debt = AsyncMock(return_value=make_debt())
            mock_repo.get_active_goal = AsyncMock(return_value=make_goal())

            with patch("app.scheduler.weekly_runner.UserRepository", return_value=mock_repo):
                delivery = self._make_delivery()
                await send_weekly_digest(delivery)

        delivery.send.assert_called_once()
        call_kwargs = delivery.send.call_args
        assert call_kwargs.kwargs["chat_id"] == 42
        assert "Estágio 0" in call_kwargs.args[0]

    async def test_unknown_stage_increments_skipped_not_sent(self):
        user = make_user(99)  # stage inválido

        with patch("app.core.database.AsyncSessionFactory") as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_repo = AsyncMock()
            mock_repo.get_all_active = AsyncMock(return_value=[user])
            mock_repo.get_active_debt = AsyncMock(return_value=None)
            mock_repo.get_active_goal = AsyncMock(return_value=None)

            with patch("app.scheduler.weekly_runner.UserRepository", return_value=mock_repo):
                delivery = self._make_delivery()
                result = await send_weekly_digest(delivery)

        assert result["sent"] == 0
        assert result["skipped"] == 1
        assert result["errors"] == 0
        delivery.send.assert_not_called()


class TestPaidNeverNegative:
    def test_current_greater_than_initial_clamps_to_zero(self):
        user = make_user(0)
        debt = make_debt(initial="1000", current="1500")  # dívida "cresceu"
        msg = _build_stage0_message(user, debt, None)
        assert "R$ 0,00" in msg  # paid clampado a 0
        assert "-" not in msg    # sem valor negativo na mensagem

    def test_paid_shown_correctly_when_positive(self):
        user = make_user(0)
        debt = make_debt(initial="5000", current="3000")
        msg = _build_stage0_message(user, debt, None)
        assert "2.000" in msg  # paid = 2000


# ---------------------------------------------------------------------------
# _should_send_stage_check
# ---------------------------------------------------------------------------

class TestShouldSendStageCheck:
    def test_none_means_never_sent(self):
        user = make_user(stage=1, stage_check_sent_at=None)
        assert _should_send_stage_check(user) is True

    def test_sent_recently_means_no(self):
        recent = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=2)
        user = make_user(stage=1, stage_check_sent_at=recent)
        assert _should_send_stage_check(user) is False

    def test_sent_over_a_week_ago_means_yes(self):
        old = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=8)
        user = make_user(stage=1, stage_check_sent_at=old)
        assert _should_send_stage_check(user) is True

    def test_sent_exactly_6_days_ago_means_yes(self):
        six_days_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=6)
        user = make_user(stage=1, stage_check_sent_at=six_days_ago)
        assert _should_send_stage_check(user) is True


# ---------------------------------------------------------------------------
# send_weekly_digest com bot (pergunta stage 1→2)
# ---------------------------------------------------------------------------

class TestStage1CheckInDigest:
    def _patch_session(self, users, debt=None, goal=None):
        mock_factory = MagicMock()
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_repo = AsyncMock()
        mock_repo.get_all_active = AsyncMock(return_value=users)
        mock_repo.get_active_debt = AsyncMock(return_value=debt)
        mock_repo.get_active_goal = AsyncMock(return_value=goal)
        mock_repo.mark_stage_check_sent = AsyncMock()
        return mock_factory, mock_repo

    async def test_stage1_user_receives_check_when_bot_provided(self):
        user = make_user(stage=1, stage_check_sent_at=None)
        mock_factory, mock_repo = self._patch_session([user])

        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock()
        delivery = MagicMock()
        delivery.send = AsyncMock()

        with patch("app.core.database.AsyncSessionFactory", mock_factory):
            with patch("app.scheduler.weekly_runner.UserRepository", return_value=mock_repo):
                await send_weekly_digest(delivery, bot=mock_bot)

        mock_bot.send_message.assert_called_once()
        call_kwargs = mock_bot.send_message.call_args.kwargs
        assert call_kwargs["chat_id"] == user.telegram_chat_id
        assert "1.000" in call_kwargs["text"]
        mock_repo.mark_stage_check_sent.assert_called_once_with(user.id)

    async def test_stage1_user_no_check_when_sent_recently(self):
        recent = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=2)
        user = make_user(stage=1, stage_check_sent_at=recent)
        mock_factory, mock_repo = self._patch_session([user])

        mock_bot = AsyncMock()
        delivery = MagicMock()
        delivery.send = AsyncMock()

        with patch("app.core.database.AsyncSessionFactory", mock_factory):
            with patch("app.scheduler.weekly_runner.UserRepository", return_value=mock_repo):
                await send_weekly_digest(delivery, bot=mock_bot)

        mock_bot.send_message.assert_not_called()
        mock_repo.mark_stage_check_sent.assert_not_called()

    async def test_no_bot_no_check_sent(self):
        user = make_user(stage=1, stage_check_sent_at=None)
        mock_factory, mock_repo = self._patch_session([user])

        delivery = MagicMock()
        delivery.send = AsyncMock()

        with patch("app.core.database.AsyncSessionFactory", mock_factory):
            with patch("app.scheduler.weekly_runner.UserRepository", return_value=mock_repo):
                await send_weekly_digest(delivery, bot=None)

        mock_repo.mark_stage_check_sent.assert_not_called()
