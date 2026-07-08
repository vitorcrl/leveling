"""
Testes unitários do profile_service (item 6a) — geração do perfil de IA.
Sem banco de dados, sem chamada real à API.

generate_profile_summary usa build_user_information (ver test_ai_context.py
para os testes específicos de formatação do dossiê) — aqui o foco é o
comportamento de geração/parse/persistência, não o conteúdo textual exato.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.profile_service import generate_and_store_profile, generate_profile_summary


def make_claude_response(text: str):
    response = MagicMock()
    response.content = [MagicMock(text=text)]
    return response


def make_user() -> MagicMock:
    user = MagicMock()
    user.id = "user-uuid-1"
    user.stage = 1
    user.monthly_budget = Decimal("500")
    user.risk_profile = "conservador"
    user.monthly_essential_expense = Decimal("1200")
    return user


def make_repo(debt=None, fund=None, goal=None, portfolio=None, dividends=None, events=None) -> MagicMock:
    repo = MagicMock()
    repo.get_active_debt = AsyncMock(return_value=debt)
    repo.get_active_emergency_fund = AsyncMock(return_value=fund)
    repo.get_active_goal = AsyncMock(return_value=goal)
    repo.get_portfolio = AsyncMock(return_value=portfolio or [])
    repo.get_recent_dividends = AsyncMock(return_value=dividends or [])
    repo.get_onboarding_events = AsyncMock(return_value=events or [])
    return repo


class TestGenerateProfileSummary:
    async def test_valid_json_response_is_parsed(self):
        client = AsyncMock()
        client.messages.create = AsyncMock(
            return_value=make_claude_response('{"resumo": "usuário motivado"}')
        )
        result = await generate_profile_summary(make_user(), make_repo(), client=client)
        assert result == {"resumo": "usuário motivado"}

    async def test_api_exception_returns_none(self):
        client = AsyncMock()
        client.messages.create = AsyncMock(side_effect=Exception("API down"))
        result = await generate_profile_summary(make_user(), make_repo(), client=client)
        assert result is None

    async def test_invalid_json_returns_none(self):
        client = AsyncMock()
        client.messages.create = AsyncMock(return_value=make_claude_response("não é json"))
        result = await generate_profile_summary(make_user(), make_repo(), client=client)
        assert result is None

    async def test_includes_events_in_prompt(self):
        client = AsyncMock()
        client.messages.create = AsyncMock(return_value=make_claude_response("{}"))
        event = MagicMock(step="essential_expense", response_type="skipped", raw_value=None)
        repo = make_repo(events=[event])

        await generate_profile_summary(make_user(), repo, client=client)

        user_prompt = client.messages.create.call_args.kwargs["messages"][0]["content"]
        assert "Gasto mensal essencial" in user_prompt
        assert "usuário pulou essa pergunta" in user_prompt

    async def test_includes_goal_in_prompt_when_present(self):
        client = AsyncMock()
        client.messages.create = AsyncMock(return_value=make_claude_response("{}"))
        goal = MagicMock()
        goal.name = "Netflix"
        goal.goal_value_monthly = Decimal("50")
        repo = make_repo(goal=goal)

        await generate_profile_summary(make_user(), repo, client=client)

        user_prompt = client.messages.create.call_args.kwargs["messages"][0]["content"]
        assert "Netflix" in user_prompt


class TestGenerateAndStoreProfile:
    async def test_persists_generated_summary(self):
        user = make_user()

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=user)
        mock_factory = MagicMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_repo = make_repo()
        mock_repo.update_profile_summary = AsyncMock()

        with patch("app.core.database.AsyncSessionFactory", mock_factory):
            with patch("app.services.profile_service.UserRepository", return_value=mock_repo):
                with patch(
                    "app.services.profile_service.generate_profile_summary",
                    AsyncMock(return_value={"resumo": "ok"}),
                ):
                    await generate_and_store_profile(user.id)

        mock_repo.update_profile_summary.assert_called_once_with(user.id, {"resumo": "ok"})

    async def test_user_not_found_skips_without_raising(self):
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=None)
        mock_factory = MagicMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("app.core.database.AsyncSessionFactory", mock_factory):
            await generate_and_store_profile("nonexistent-id")
        # não levantou exceção — é o comportamento esperado

    async def test_unexpected_error_does_not_propagate(self):
        mock_factory = MagicMock()
        mock_factory.return_value.__aenter__ = AsyncMock(side_effect=Exception("db down"))

        with patch("app.core.database.AsyncSessionFactory", mock_factory):
            await generate_and_store_profile("user-uuid-1")
        # não levantou exceção — nunca deve travar o fluxo que disparou
