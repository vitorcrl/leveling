"""
Testes unitários do ConversationHandler de onboarding.
Sem banco de dados, sem Telegram real — tudo mockado.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.bot.onboarding import (
    ASK_BUDGET,
    ASK_DEBT,
    ASK_DEBT_AMOUNT,
    ASK_GOAL,
    ASK_GOAL_VALUE,
    ASK_PORTFOLIO,
    ASK_PROFILE,
    _DATA,
    _parse_amount,
    _parse_tickers,
    ask_budget,
    ask_debt,
    ask_debt_amount,
    ask_goal,
    ask_goal_value,
    ask_portfolio,
    ask_portfolio_skip,
    ask_profile,
    cancel,
    start,
)
from telegram.ext import ConversationHandler


def make_update(text: str, user_id: int = 123456) -> MagicMock:
    update = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.effective_user.id = user_id
    return update


def make_context(data: dict | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.user_data = {_DATA: data or {}}
    return ctx


# ---------------------------------------------------------------------------
# Helpers de parse — sem I/O
# ---------------------------------------------------------------------------

class TestParseAmount:
    def test_integer(self):
        assert _parse_amount("1500") == Decimal("1500")

    def test_br_format_with_dot_separator(self):
        assert _parse_amount("1.500") == Decimal("1500")

    def test_br_format_with_comma_decimal(self):
        assert _parse_amount("1.500,50") == Decimal("1500.50")

    def test_us_format_with_dot_decimal(self):
        assert _parse_amount("1500.50") == Decimal("1500.50")

    def test_strips_r_symbol(self):
        assert _parse_amount("R$ 1.200") == Decimal("1200")

    def test_returns_none_for_zero(self):
        assert _parse_amount("0") is None

    def test_returns_none_for_text(self):
        assert _parse_amount("abc") is None

    def test_returns_none_for_negative(self):
        assert _parse_amount("-500") is None


class TestParseTickers:
    def test_single_ticker(self):
        assert _parse_tickers("MXRF11") == ["MXRF11"]

    def test_multiple_space_separated(self):
        assert _parse_tickers("MXRF11 KNCR11 HSML11") == ["MXRF11", "KNCR11", "HSML11"]

    def test_comma_separated(self):
        assert _parse_tickers("MXRF11,KNCR11") == ["MXRF11", "KNCR11"]

    def test_lowercases_normalized(self):
        assert _parse_tickers("mxrf11") == ["MXRF11"]

    def test_ignores_invalid_tokens(self):
        assert _parse_tickers("MXRF11 nao-e-ticker KNCR11") == ["MXRF11", "KNCR11"]

    def test_empty_returns_empty(self):
        assert _parse_tickers("") == []


# ---------------------------------------------------------------------------
# Handlers — fluxo feliz
# ---------------------------------------------------------------------------

class TestStart:
    async def test_sends_greeting_and_returns_ask_debt(self):
        update = make_update("/start")
        ctx = make_context()
        result = await start(update, ctx)
        assert result == ASK_DEBT
        update.message.reply_text.assert_called_once()
        assert ctx.user_data[_DATA] == {}


class TestAskDebt:
    async def test_sim_stores_has_debt_true_and_returns_ask_debt_amount(self):
        update = make_update("Sim")
        ctx = make_context()
        result = await ask_debt(update, ctx)
        assert result == ASK_DEBT_AMOUNT
        assert ctx.user_data[_DATA]["has_debt"] is True

    async def test_nao_stores_has_debt_false_and_returns_ask_budget(self):
        update = make_update("Não")
        ctx = make_context()
        result = await ask_debt(update, ctx)
        assert result == ASK_BUDGET
        assert ctx.user_data[_DATA]["has_debt"] is False

    async def test_case_insensitive(self):
        update = make_update("SIM")
        ctx = make_context()
        result = await ask_debt(update, ctx)
        assert result == ASK_DEBT_AMOUNT


class TestAskDebtAmount:
    async def test_valid_amount_stored_and_proceeds(self):
        update = make_update("5000")
        ctx = make_context({"has_debt": True})
        result = await ask_debt_amount(update, ctx)
        assert result == ASK_BUDGET
        assert ctx.user_data[_DATA]["debt_amount"] == Decimal("5000")

    async def test_invalid_amount_stays_on_same_state(self):
        update = make_update("muito dinheiro")
        ctx = make_context({"has_debt": True})
        result = await ask_debt_amount(update, ctx)
        assert result == ASK_DEBT_AMOUNT
        assert "debt_amount" not in ctx.user_data[_DATA]


class TestAskBudget:
    async def test_valid_amount_stored_and_proceeds(self):
        update = make_update("1200")
        ctx = make_context()
        result = await ask_budget(update, ctx)
        assert result == ASK_GOAL
        assert ctx.user_data[_DATA]["monthly_budget"] == Decimal("1200")

    async def test_invalid_amount_stays_on_same_state(self):
        update = make_update("não sei")
        ctx = make_context()
        result = await ask_budget(update, ctx)
        assert result == ASK_BUDGET


class TestAskGoal:
    async def test_valid_goal_stored_and_proceeds(self):
        update = make_update("Academia")
        ctx = make_context()
        result = await ask_goal(update, ctx)
        assert result == ASK_GOAL_VALUE
        assert ctx.user_data[_DATA]["goal_name"] == "Academia"

    async def test_too_short_stays_on_same_state(self):
        update = make_update("X")
        ctx = make_context()
        result = await ask_goal(update, ctx)
        assert result == ASK_GOAL


class TestAskGoalValue:
    async def test_valid_value_stored_and_proceeds(self):
        update = make_update("129,90")
        ctx = make_context()
        result = await ask_goal_value(update, ctx)
        assert result == ASK_PROFILE
        assert ctx.user_data[_DATA]["goal_value_monthly"] == Decimal("129.90")

    async def test_invalid_stays_on_same_state(self):
        update = make_update("caro")
        ctx = make_context()
        result = await ask_goal_value(update, ctx)
        assert result == ASK_GOAL_VALUE


class TestAskProfile:
    async def test_conservador_stored(self):
        update = make_update("Conservador")
        ctx = make_context()
        result = await ask_profile(update, ctx)
        assert result == ASK_PORTFOLIO
        assert ctx.user_data[_DATA]["risk_profile"] == "conservador"

    async def test_moderado_stored(self):
        update = make_update("Moderado")
        ctx = make_context()
        result = await ask_profile(update, ctx)
        assert result == ASK_PORTFOLIO
        assert ctx.user_data[_DATA]["risk_profile"] == "moderado"

    async def test_invalid_stays_on_same_state(self):
        update = make_update("arrojado")
        ctx = make_context()
        result = await ask_profile(update, ctx)
        assert result == ASK_PROFILE


# ---------------------------------------------------------------------------
# Passo final — portfolio e cálculo de stage
# ---------------------------------------------------------------------------

def _base_data() -> dict:
    return {
        "has_debt": False,
        "monthly_budget": Decimal("1000"),
        "goal_name": "Netflix",
        "goal_value_monthly": Decimal("50"),
        "risk_profile": "conservador",
    }


class TestAskPortfolio:
    async def test_valid_tickers_stored(self):
        update = make_update("MXRF11 KNCR11")
        ctx = make_context(_base_data())

        with patch("app.core.database.AsyncSessionFactory") as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_repo = AsyncMock()
            mock_repo.save_onboarding = AsyncMock()

            with patch("app.bot.onboarding.UserRepository", return_value=mock_repo):
                result = await ask_portfolio(update, ctx)

        assert result == ConversationHandler.END
        call_kwargs = mock_repo.save_onboarding.call_args.kwargs
        assert call_kwargs["portfolio_tickers"] == ["MXRF11", "KNCR11"]
        assert call_kwargs["stage"] == 2  # sem dívida + com FIIs → stage 2

    async def test_invalid_tickers_stays_on_same_state(self):
        update = make_update("não tenho nenhum")
        ctx = make_context(_base_data())
        result = await ask_portfolio(update, ctx)
        assert result == ASK_PORTFOLIO

    async def test_skip_sets_empty_portfolio(self):
        update = make_update("/pular")
        ctx = make_context(_base_data())

        with patch("app.core.database.AsyncSessionFactory") as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_repo = AsyncMock()
            mock_repo.save_onboarding = AsyncMock()

            with patch("app.bot.onboarding.UserRepository", return_value=mock_repo):
                result = await ask_portfolio_skip(update, ctx)

        assert result == ConversationHandler.END
        call_kwargs = mock_repo.save_onboarding.call_args.kwargs
        assert call_kwargs["portfolio_tickers"] == []
        assert call_kwargs["stage"] == 1  # sem dívida + sem FIIs → stage 1


class TestStageCalculation:
    """Verifica que o stage é calculado corretamente ao finalizar o onboarding."""

    async def _finish_with(self, has_debt: bool, tickers: list[str]) -> int:
        data = _base_data()
        data["has_debt"] = has_debt
        if has_debt:
            data["debt_amount"] = Decimal("3000")
        data["portfolio_tickers"] = tickers

        update = make_update("qualquer")
        ctx = make_context(data)

        captured_stage = None

        async def capture(**kwargs):
            nonlocal captured_stage
            captured_stage = kwargs["stage"]

        with patch("app.bot.onboarding.AsyncSessionFactory") as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_repo = AsyncMock()
            mock_repo.save_onboarding = AsyncMock(side_effect=capture)
            with patch("app.bot.onboarding.UserRepository", return_value=mock_repo):
                from app.bot.onboarding import _finish_onboarding
                await _finish_onboarding(update, ctx)

        return captured_stage

    async def test_has_debt_gives_stage_0(self):
        assert await self._finish_with(has_debt=True, tickers=[]) == 0

    async def test_has_debt_with_fiis_still_gives_stage_0(self):
        assert await self._finish_with(has_debt=True, tickers=["MXRF11"]) == 0

    async def test_no_debt_no_fiis_gives_stage_1(self):
        assert await self._finish_with(has_debt=False, tickers=[]) == 1

    async def test_no_debt_with_fiis_gives_stage_2(self):
        assert await self._finish_with(has_debt=False, tickers=["MXRF11"]) == 2


class TestCancel:
    async def test_cancel_clears_data_and_ends(self):
        update = make_update("/cancel")
        ctx = make_context({"some": "data"})
        result = await cancel(update, ctx)
        assert result == ConversationHandler.END
        assert _DATA not in ctx.user_data
