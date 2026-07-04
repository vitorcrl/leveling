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
    ASK_ESSENTIAL_EXPENSE,
    ASK_GOAL,
    ASK_GOAL_VALUE,
    ASK_HAS_PORTFOLIO,
    ASK_KNOWS_FII,
    ASK_PORTFOLIO,
    ASK_PROFILE,
    ASK_SAVINGS,
    CALLBACK_COMECAR_AGORA,
    _CALLBACK_CONSERVADOR,
    _CALLBACK_DEBT_NAO,
    _CALLBACK_DEBT_SIM,
    _CALLBACK_HAS_PORTFOLIO_NAO,
    _CALLBACK_HAS_PORTFOLIO_SIM,
    _CALLBACK_KNOWS_FII_NAO,
    _CALLBACK_KNOWS_FII_SIM,
    _CALLBACK_MODERADO,
    _CALLBACK_PORTFOLIO_SKIP,
    _DATA,
    _parse_amount,
    _parse_tickers,
    ask_budget,
    ask_debt,
    ask_debt_amount,
    ask_essential_expense,
    ask_essential_expense_skip,
    ask_goal,
    ask_goal_value,
    ask_has_portfolio,
    ask_knows_fii,
    ask_portfolio,
    ask_portfolio_skip,
    ask_portfolio_skip_callback,
    ask_profile_callback,
    ask_savings,
    build_onboarding_handler,
    cancel,
    start,
)
from telegram.ext import CallbackQueryHandler, ConversationHandler


def make_update(text: str, user_id: int = 123456) -> MagicMock:
    update = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.effective_user.id = user_id
    update.callback_query = None
    return update


def make_callback_update(data: str, user_id: int = 123456) -> MagicMock:
    update = MagicMock()
    update.effective_user.id = user_id
    update.message = None
    update.callback_query.data = data
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
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

    def test_ignores_extra_text_after_number(self):
        # "Sim 1000" — usuário mandou resposta junto com o valor
        assert _parse_amount("Sim 1000") is None  # parse_amount recebe só o número já limpo


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
        assert update.message.reply_text.call_count == 2  # apresentação + pergunta de dívida
        assert ctx.user_data[_DATA] == {}

    async def test_first_message_introduces_leveling(self):
        update = make_update("/start")
        ctx = make_context()
        await start(update, ctx)
        first_call = update.message.reply_text.call_args_list[0].args[0]
        assert "Leveling" in first_call


class TestAskDebt:
    async def test_sim_stores_has_debt_true_and_returns_ask_debt_amount(self):
        update = make_callback_update(_CALLBACK_DEBT_SIM)
        ctx = make_context()
        result = await ask_debt(update, ctx)
        assert result == ASK_DEBT_AMOUNT
        assert ctx.user_data[_DATA]["has_debt"] is True

    async def test_nao_stores_has_debt_false_and_returns_ask_essential_expense(self):
        update = make_callback_update(_CALLBACK_DEBT_NAO)
        update.callback_query.message.reply_text = AsyncMock()
        ctx = make_context()
        result = await ask_debt(update, ctx)
        assert result == ASK_ESSENTIAL_EXPENSE
        assert ctx.user_data[_DATA]["has_debt"] is False

    async def test_start_sends_inline_keyboard(self):
        update = make_update("/start")
        ctx = make_context()
        await start(update, ctx)
        call_kwargs = update.message.reply_text.call_args.kwargs
        markup = call_kwargs["reply_markup"]
        button_datas = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert _CALLBACK_DEBT_SIM in button_datas
        assert _CALLBACK_DEBT_NAO in button_datas


class TestAskDebtAmount:
    async def test_valid_amount_stored_and_proceeds(self):
        update = make_update("5000")
        ctx = make_context({"has_debt": True})
        result = await ask_debt_amount(update, ctx)
        assert result == ASK_ESSENTIAL_EXPENSE
        assert ctx.user_data[_DATA]["debt_amount"] == Decimal("5000")

    async def test_invalid_amount_stays_on_same_state(self):
        update = make_update("muito dinheiro")
        ctx = make_context({"has_debt": True})
        result = await ask_debt_amount(update, ctx)
        assert result == ASK_DEBT_AMOUNT
        assert "debt_amount" not in ctx.user_data[_DATA]


class TestAskEssentialExpense:
    async def test_valid_amount_stored_and_proceeds_to_budget(self):
        update = make_update("1500")
        ctx = make_context({"has_debt": False})
        result = await ask_essential_expense(update, ctx)
        assert result == ASK_BUDGET
        assert ctx.user_data[_DATA]["monthly_essential_expense"] == Decimal("1500")

    async def test_dont_know_skips_value_and_sends_calculator_link(self):
        update = make_update("não sei")
        ctx = make_context({"has_debt": False})
        result = await ask_essential_expense(update, ctx)
        assert result == ASK_BUDGET
        assert "monthly_essential_expense" not in ctx.user_data[_DATA]
        msg = update.message.reply_text.call_args_list[0].args[0]
        assert "calculadora" in msg.lower()

    async def test_dont_know_variant_nao_faco_ideia(self):
        update = make_update("não faço ideia")
        ctx = make_context({"has_debt": False})
        result = await ask_essential_expense(update, ctx)
        assert result == ASK_BUDGET
        assert "monthly_essential_expense" not in ctx.user_data[_DATA]

    async def test_invalid_text_stays_on_same_state(self):
        update = make_update("sei la quanto")
        ctx = make_context({"has_debt": False})
        result = await ask_essential_expense(update, ctx)
        assert result == ASK_ESSENTIAL_EXPENSE
        assert "monthly_essential_expense" not in ctx.user_data[_DATA]

    async def test_routes_to_debt_amount_question_when_has_debt(self):
        update = make_update("1500")
        ctx = make_context({"has_debt": True})
        await ask_essential_expense(update, ctx)
        msg = update.message.reply_text.call_args.args[0]
        assert "dívida" in msg.lower()

    async def test_routes_to_savings_question_when_no_debt(self):
        update = make_update("1500")
        ctx = make_context({"has_debt": False})
        await ask_essential_expense(update, ctx)
        msg = update.message.reply_text.call_args.args[0]
        assert "guardar" in msg.lower()


class TestAskEssentialExpenseSkip:
    async def test_skip_proceeds_without_storing_value(self):
        update = make_update("/pular")
        ctx = make_context({"has_debt": False})
        result = await ask_essential_expense_skip(update, ctx)
        assert result == ASK_BUDGET
        assert "monthly_essential_expense" not in ctx.user_data[_DATA]


class TestAskBudget:
    async def test_with_debt_goes_to_ask_goal(self):
        update = make_update("1200")
        ctx = make_context({"has_debt": True})
        result = await ask_budget(update, ctx)
        assert result == ASK_GOAL
        assert ctx.user_data[_DATA]["monthly_budget"] == Decimal("1200")

    async def test_without_debt_goes_to_ask_savings(self):
        update = make_update("500")
        ctx = make_context({"has_debt": False})
        result = await ask_budget(update, ctx)
        assert result == ASK_SAVINGS
        assert ctx.user_data[_DATA]["monthly_budget"] == Decimal("500")

    async def test_invalid_amount_stays_on_same_state(self):
        update = make_update("não sei")
        ctx = make_context()
        result = await ask_budget(update, ctx)
        assert result == ASK_BUDGET


class TestAskSavings:
    async def test_valid_amount_stored_and_proceeds(self):
        update = make_update("800")
        ctx = make_context({"has_debt": False})
        result = await ask_savings(update, ctx)
        assert result == ASK_GOAL
        assert ctx.user_data[_DATA]["savings_amount"] == Decimal("800")

    async def test_zero_text_stored_as_zero(self):
        update = make_update("0")
        ctx = make_context({"has_debt": False})
        result = await ask_savings(update, ctx)
        assert result == ASK_GOAL
        assert ctx.user_data[_DATA]["savings_amount"] == Decimal("0")

    async def test_nao_stored_as_zero(self):
        update = make_update("não")
        ctx = make_context({"has_debt": False})
        result = await ask_savings(update, ctx)
        assert result == ASK_GOAL
        assert ctx.user_data[_DATA]["savings_amount"] == Decimal("0")

    async def test_nada_stored_as_zero(self):
        update = make_update("nada")
        ctx = make_context({"has_debt": False})
        result = await ask_savings(update, ctx)
        assert result == ASK_GOAL
        assert ctx.user_data[_DATA]["savings_amount"] == Decimal("0")


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

    async def test_sends_inline_keyboard_with_profiles(self):
        update = make_update("50")
        ctx = make_context()
        await ask_goal_value(update, ctx)
        call_kwargs = update.message.reply_text.call_args.kwargs
        assert "reply_markup" in call_kwargs
        # verifica que os dois perfis estão no teclado inline
        markup = call_kwargs["reply_markup"]
        button_datas = [btn.callback_data for row in markup.inline_keyboard for btn in row]
        assert _CALLBACK_CONSERVADOR in button_datas
        assert _CALLBACK_MODERADO in button_datas


class TestAskProfileCallback:
    async def test_conservador_stored_and_proceeds(self):
        update = make_callback_update(_CALLBACK_CONSERVADOR)
        ctx = make_context()
        result = await ask_profile_callback(update, ctx)
        assert result == ASK_HAS_PORTFOLIO
        assert ctx.user_data[_DATA]["risk_profile"] == "conservador"

    async def test_moderado_stored_and_proceeds(self):
        update = make_callback_update(_CALLBACK_MODERADO)
        ctx = make_context()
        result = await ask_profile_callback(update, ctx)
        assert result == ASK_HAS_PORTFOLIO
        assert ctx.user_data[_DATA]["risk_profile"] == "moderado"

    async def test_edits_message_with_profile_confirmation(self):
        update = make_callback_update(_CALLBACK_CONSERVADOR)
        ctx = make_context()
        await ask_profile_callback(update, ctx)
        update.callback_query.edit_message_text.assert_called_once()
        msg = update.callback_query.edit_message_text.call_args.args[0]
        assert "Conservador" in msg

    async def test_shows_has_portfolio_buttons(self):
        update = make_callback_update(_CALLBACK_CONSERVADOR)
        ctx = make_context()
        await ask_profile_callback(update, ctx)
        call_kwargs = update.callback_query.edit_message_text.call_args.kwargs
        keyboard = call_kwargs["reply_markup"]
        callbacks = {btn.callback_data for row in keyboard.inline_keyboard for btn in row}
        assert callbacks == {_CALLBACK_HAS_PORTFOLIO_SIM, _CALLBACK_HAS_PORTFOLIO_NAO}


class TestAskHasPortfolio:
    async def test_sim_asks_for_tickers(self):
        update = make_callback_update(_CALLBACK_HAS_PORTFOLIO_SIM)
        ctx = make_context()
        result = await ask_has_portfolio(update, ctx)
        assert result == ASK_PORTFOLIO
        update.callback_query.edit_message_text.assert_called_once()

    async def test_nao_shows_knows_fii_buttons(self):
        update = make_callback_update(_CALLBACK_HAS_PORTFOLIO_NAO)
        ctx = make_context()
        result = await ask_has_portfolio(update, ctx)
        assert result == ASK_KNOWS_FII
        call_kwargs = update.callback_query.edit_message_text.call_args.kwargs
        keyboard = call_kwargs["reply_markup"]
        callbacks = {btn.callback_data for row in keyboard.inline_keyboard for btn in row}
        assert callbacks == {_CALLBACK_KNOWS_FII_SIM, _CALLBACK_KNOWS_FII_NAO}


class TestAskKnowsFii:
    async def _finish_with(self, callback_data: str) -> tuple:
        update = make_callback_update(callback_data)
        update.callback_query.message.reply_text = AsyncMock()
        ctx = make_context(_base_data())

        with patch("app.core.database.AsyncSessionFactory") as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_repo = AsyncMock()
            mock_repo.save_onboarding = AsyncMock()

            with patch("app.bot.onboarding.UserRepository", return_value=mock_repo):
                result = await ask_knows_fii(update, ctx)

        return update, result

    async def test_sim_skips_explanation_and_finishes(self):
        update, result = await self._finish_with(_CALLBACK_KNOWS_FII_SIM)
        assert result == ConversationHandler.END
        update.callback_query.edit_message_text.assert_not_called()

    async def test_nao_shows_explanation_and_finishes(self):
        update, result = await self._finish_with(_CALLBACK_KNOWS_FII_NAO)
        assert result == ConversationHandler.END
        update.callback_query.edit_message_text.assert_called_once()
        msg = update.callback_query.edit_message_text.call_args.args[0]
        assert "FII" in msg

    async def test_sets_empty_portfolio(self):
        update = make_callback_update(_CALLBACK_KNOWS_FII_SIM)
        update.callback_query.message.reply_text = AsyncMock()
        ctx = make_context(_base_data())

        with patch("app.core.database.AsyncSessionFactory") as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_repo = AsyncMock()
            mock_repo.save_onboarding = AsyncMock()

            with patch("app.bot.onboarding.UserRepository", return_value=mock_repo):
                await ask_knows_fii(update, ctx)

        call_kwargs = mock_repo.save_onboarding.call_args.kwargs
        assert call_kwargs["portfolio_tickers"] == []


# ---------------------------------------------------------------------------
# Passo final — portfolio e cálculo de stage
# ---------------------------------------------------------------------------

def _base_data() -> dict:
    return {
        "has_debt": False,
        "monthly_budget": Decimal("1000"),
        "savings_amount": Decimal("200"),
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
        assert call_kwargs["stage"] == 3
        assert call_kwargs["savings_amount"] == Decimal("200")

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
        assert call_kwargs["stage"] == 2

    async def test_skip_callback_sets_empty_portfolio(self):
        update = make_callback_update(_CALLBACK_PORTFOLIO_SKIP)
        update.callback_query.message.reply_text = AsyncMock()
        ctx = make_context(_base_data())

        with patch("app.core.database.AsyncSessionFactory") as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_repo = AsyncMock()
            mock_repo.save_onboarding = AsyncMock()

            with patch("app.bot.onboarding.UserRepository", return_value=mock_repo):
                result = await ask_portfolio_skip_callback(update, ctx)

        assert result == ConversationHandler.END
        update.callback_query.answer.assert_called_once()
        call_kwargs = mock_repo.save_onboarding.call_args.kwargs
        assert call_kwargs["portfolio_tickers"] == []
        assert call_kwargs["stage"] == 2


class TestStageCalculation:
    async def _finish_with(
        self,
        has_debt: bool,
        tickers: list[str],
        monthly_essential_expense: Decimal | None = None,
    ) -> tuple[int, dict]:
        data = _base_data()
        data["has_debt"] = has_debt
        if has_debt:
            data["debt_amount"] = Decimal("3000")
            data.pop("savings_amount", None)
        data["portfolio_tickers"] = tickers
        if monthly_essential_expense is not None:
            data["monthly_essential_expense"] = monthly_essential_expense

        update = make_update("qualquer")
        ctx = make_context(data)

        captured = {}

        async def capture(**kwargs):
            captured.update(kwargs)

        with patch("app.bot.onboarding.AsyncSessionFactory") as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_repo = AsyncMock()
            mock_repo.save_onboarding = AsyncMock(side_effect=capture)
            with patch("app.bot.onboarding.UserRepository", return_value=mock_repo):
                from app.bot.onboarding import _finish_onboarding
                await _finish_onboarding(update, ctx)

        return captured["stage"], captured

    async def test_has_debt_gives_stage_0(self):
        stage, _ = await self._finish_with(has_debt=True, tickers=[])
        assert stage == 0

    async def test_has_debt_with_fiis_still_gives_stage_0(self):
        stage, _ = await self._finish_with(has_debt=True, tickers=["MXRF11"])
        assert stage == 0

    async def test_has_debt_with_essential_expense_still_gives_stage_0(self):
        stage, _ = await self._finish_with(
            has_debt=True, tickers=[], monthly_essential_expense=Decimal("1000")
        )
        assert stage == 0

    async def test_no_debt_no_fiis_no_essential_expense_gives_stage_2(self):
        stage, _ = await self._finish_with(has_debt=False, tickers=[])
        assert stage == 2

    async def test_no_debt_with_fiis_gives_stage_3(self):
        stage, _ = await self._finish_with(has_debt=False, tickers=["MXRF11"])
        assert stage == 3

    async def test_no_debt_with_essential_expense_gives_stage_1(self):
        stage, kwargs = await self._finish_with(
            has_debt=False, tickers=[], monthly_essential_expense=Decimal("1200")
        )
        assert stage == 1
        assert kwargs["monthly_essential_expense"] == Decimal("1200")

    async def test_fiis_takes_priority_over_essential_expense(self):
        stage, _ = await self._finish_with(
            has_debt=False,
            tickers=["MXRF11"],
            monthly_essential_expense=Decimal("1200"),
        )
        assert stage == 3


class TestCancel:
    async def test_cancel_clears_data_and_ends(self):
        update = make_update("/cancel")
        ctx = make_context({"some": "data"})
        result = await cancel(update, ctx)
        assert result == ConversationHandler.END
        assert _DATA not in ctx.user_data


class TestBuildOnboardingHandlerEntryPoints:
    def test_comecar_agora_callback_is_an_entry_point(self):
        handler = build_onboarding_handler()
        callback_entry_points = [
            ep for ep in handler.entry_points if isinstance(ep, CallbackQueryHandler)
        ]
        assert len(callback_entry_points) == 1
        assert callback_entry_points[0].pattern.match(CALLBACK_COMECAR_AGORA)

    def test_start_command_is_still_an_entry_point(self):
        handler = build_onboarding_handler()
        command_entry_points = [
            ep for ep in handler.entry_points if hasattr(ep, "commands")
        ]
        assert any("start" in ep.commands for ep in command_entry_points)


class TestStartFromCallback:
    async def test_callback_start_answers_and_sends_debt_question(self):
        update = make_callback_update(CALLBACK_COMECAR_AGORA)
        update.callback_query.message.reply_text = AsyncMock()
        ctx = make_context()

        result = await start(update, ctx)

        assert result == ASK_DEBT
        update.callback_query.answer.assert_called_once()
        assert update.callback_query.message.reply_text.call_count == 2
        assert ctx.user_data[_DATA] == {}
