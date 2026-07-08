"""
Testes unitários do dossiê de IA (app/services/ai_context.py).

Foco em legibilidade para uma IA sem contexto do código: stage com rótulo,
ticker com tipo/nome do catálogo, callback_data traduzido, steps do
onboarding em linguagem natural — não em strings internas de implementação.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from app.services.ai_context import build_user_information


def make_user(
    stage: int = 3,
    monthly_budget: Decimal = Decimal("1000"),
    risk_profile: str = "conservador",
    monthly_essential_expense: Decimal | None = None,
) -> MagicMock:
    user = MagicMock()
    user.id = "user-1"
    user.stage = stage
    user.monthly_budget = monthly_budget
    user.risk_profile = risk_profile
    user.monthly_essential_expense = monthly_essential_expense
    return user


def make_repo(
    debt=None,
    fund=None,
    goal=None,
    portfolio=None,
    dividends=None,
    events=None,
) -> MagicMock:
    repo = MagicMock()
    repo.get_active_debt = AsyncMock(return_value=debt)
    repo.get_active_emergency_fund = AsyncMock(return_value=fund)
    repo.get_active_goal = AsyncMock(return_value=goal)
    repo.get_portfolio = AsyncMock(return_value=portfolio or [])
    repo.get_recent_dividends = AsyncMock(return_value=dividends or [])
    repo.get_onboarding_events = AsyncMock(return_value=events or [])
    return repo


def make_position(ticker: str, shares: int) -> MagicMock:
    position = MagicMock()
    position.ticker = ticker
    position.shares = shares
    return position


def make_event(step: str, response_type: str, raw_value: str | None = None) -> MagicMock:
    event = MagicMock()
    event.step = step
    event.response_type = response_type
    event.raw_value = raw_value
    return event


class TestBuildUserInformationStructure:
    async def test_all_sections_present_for_empty_user(self):
        user = make_user()
        repo = make_repo()
        text = await build_user_information(repo, user)

        assert "=== Perfil financeiro ===" in text
        assert "=== Meta ===" in text
        assert "=== Dívida ===" in text
        assert "=== Reserva de emergência ===" in text
        assert "=== Carteira de FIIs ===" in text
        assert "=== Dividendos recebidos" in text
        assert "=== Respostas do onboarding ===" in text

    async def test_empty_user_falls_back_gracefully_in_every_section(self):
        user = make_user()
        repo = make_repo()
        text = await build_user_information(repo, user)

        assert "Sem meta ativa." in text
        assert "Sem dívida ativa." in text
        assert "Sem reserva ativa" in text
        assert "Sem FIIs na carteira." in text
        assert "Nenhum dividendo informado no período." in text
        assert "Sem eventos registrados." in text


class TestStageLabel:
    async def test_stage_shows_human_label_not_raw_number(self):
        for stage, expected in [
            (0, "quitando dívida"),
            (1, "reserva de emergência"),
            (2, "construindo caixinha"),
            (3, "investindo em FIIs"),
        ]:
            user = make_user(stage=stage)
            repo = make_repo()
            text = await build_user_information(repo, user)
            assert expected in text

    async def test_unknown_stage_has_safe_fallback(self):
        user = make_user(stage=99)
        repo = make_repo()
        text = await build_user_information(repo, user)
        assert "estágio 99" in text


class TestPortfolioSection:
    async def test_catalogued_ticker_shows_tipo_and_nome(self):
        user = make_user()
        repo = make_repo(portfolio=[make_position("MXRF11", 150)])
        text = await build_user_information(repo, user)
        assert "MXRF11" in text
        assert "Maxi Renda" in text
        assert "Papel (CRI/CRA)" in text
        assert "150 cotas" in text

    async def test_uncatalogued_ticker_has_safe_fallback(self):
        user = make_user()
        repo = make_repo(portfolio=[make_position("ZZZZ99", 10)])
        text = await build_user_information(repo, user)
        assert "ZZZZ99" in text
        assert "tipo não catalogado" in text
        assert "10 cotas" in text


class TestEventsSection:
    async def test_answered_event_translates_known_callback_data(self):
        user = make_user()
        repo = make_repo(events=[make_event("has_portfolio", "answered", "onb_portfolio_sim")])
        text = await build_user_information(repo, user)
        assert "Já tinha FII na carteira?" in text
        assert "onb_portfolio_sim" not in text
        assert "sim" in text

    async def test_answered_event_keeps_unmapped_raw_value(self):
        user = make_user()
        repo = make_repo(events=[make_event("goal", "answered", "Lata de monster")])
        text = await build_user_information(repo, user)
        assert "Meta escolhida" in text
        assert "Lata de monster" in text

    async def test_skipped_event_does_not_show_none_value(self):
        user = make_user()
        repo = make_repo(events=[make_event("essential_expense", "skipped", None)])
        text = await build_user_information(repo, user)
        assert "Gasto mensal essencial" in text
        assert "usuário pulou essa pergunta" in text
        assert "None" not in text

    async def test_dont_know_event_is_labeled(self):
        user = make_user()
        repo = make_repo(events=[make_event("essential_expense", "dont_know", "não sei")])
        text = await build_user_information(repo, user)
        assert "usuário respondeu 'não sei'" in text

    async def test_unknown_step_falls_back_to_raw_step_name(self):
        user = make_user()
        repo = make_repo(events=[make_event("step_novo_desconhecido", "answered", "x")])
        text = await build_user_information(repo, user)
        assert "step_novo_desconhecido" in text


class TestDividendsSection:
    async def test_dividend_shows_ticker_amount_and_date(self):
        dividend = MagicMock()
        dividend.ticker = "HGLG11"
        dividend.amount_per_share = Decimal("1.10")
        dividend.received_date = date(2026, 7, 1)
        dividend.total_received = Decimal("22.00")

        user = make_user()
        repo = make_repo(dividends=[dividend])
        text = await build_user_information(repo, user)

        assert "HGLG11" in text
        assert "2026-07-01" in text
        assert "22,00" in text
