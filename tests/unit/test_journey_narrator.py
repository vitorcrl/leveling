"""
Testes unitários do ClaudeJourneyNarrator (item 6b).
Sem banco de dados, sem chamada real à API — cliente Anthropic mockado.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters.narrators.journey_narrator import ClaudeJourneyNarrator
from app.domain.models_journey import JourneyDigestContext


def make_claude_response(text: str):
    response = MagicMock()
    response.content = [MagicMock(text=text)]
    return response


def make_user(stage: int = 0, user_profile_summary: dict | None = None) -> MagicMock:
    user = MagicMock()
    user.telegram_chat_id = 123456
    user.stage = stage
    user.monthly_budget = Decimal("500")
    user.risk_profile = "conservador"
    user.user_profile_summary = user_profile_summary
    return user


def make_context(stage: int = 0, profile_summary: dict | None = None) -> JourneyDigestContext:
    return JourneyDigestContext(
        user=make_user(stage=stage, user_profile_summary=profile_summary),
        debt=None,
        fund=None,
        goal=None,
        profile_summary=profile_summary,
    )


@pytest.fixture
def mock_anthropic_client():
    with patch("app.adapters.narrators.journey_narrator.anthropic.AsyncAnthropic") as mock_cls:
        client = AsyncMock()
        mock_cls.return_value = client
        yield client


class TestNoProfileSummary:
    async def test_falls_back_to_deterministic_message_without_calling_api(
        self, mock_anthropic_client
    ):
        narrator = ClaudeJourneyNarrator(api_key="dummy")
        context = make_context(stage=0, profile_summary=None)

        result = await narrator.narrate(context)

        assert "Estágio 0" in result
        mock_anthropic_client.messages.create.assert_not_called()


class TestWithProfileSummary:
    async def test_calls_api_and_returns_personalized_text(self, mock_anthropic_client):
        mock_anthropic_client.messages.create = AsyncMock(
            return_value=make_claude_response("Mensagem personalizada!")
        )
        narrator = ClaudeJourneyNarrator(api_key="dummy")
        context = make_context(stage=0, profile_summary={"tom_sugerido": "motivacional"})

        result = await narrator.narrate(context)

        assert result == "Mensagem personalizada!"
        mock_anthropic_client.messages.create.assert_called_once()

    async def test_uses_haiku_model(self, mock_anthropic_client):
        mock_anthropic_client.messages.create = AsyncMock(
            return_value=make_claude_response("ok")
        )
        narrator = ClaudeJourneyNarrator(api_key="dummy")
        context = make_context(stage=0, profile_summary={"resumo": "x"})

        await narrator.narrate(context)

        call_kwargs = mock_anthropic_client.messages.create.call_args.kwargs
        assert "haiku" in call_kwargs["model"]

    async def test_api_failure_falls_back_to_deterministic_message(self, mock_anthropic_client):
        mock_anthropic_client.messages.create = AsyncMock(side_effect=Exception("API down"))
        narrator = ClaudeJourneyNarrator(api_key="dummy")
        context = make_context(stage=0, profile_summary={"resumo": "x"})

        result = await narrator.narrate(context)

        assert "Estágio 0" in result


class TestDeterministicMessageDelegation:
    async def test_delegates_to_stage1_message_builder(self, mock_anthropic_client):
        narrator = ClaudeJourneyNarrator(api_key="dummy")
        context = make_context(stage=1, profile_summary=None)

        result = await narrator.narrate(context)

        assert "Estágio 0.5" in result

    async def test_delegates_to_stage2_message_builder(self, mock_anthropic_client):
        narrator = ClaudeJourneyNarrator(api_key="dummy")
        context = make_context(stage=2, profile_summary=None)

        result = await narrator.narrate(context)

        assert "Estágio 1" in result

    async def test_delegates_to_stage3_message_builder(self, mock_anthropic_client):
        narrator = ClaudeJourneyNarrator(api_key="dummy")
        context = make_context(stage=3, profile_summary=None)

        result = await narrator.narrate(context)

        assert "Estágio 2" in result

    async def test_unknown_stage_returns_generic_message(self, mock_anthropic_client):
        narrator = ClaudeJourneyNarrator(api_key="dummy")
        context = make_context(stage=99, profile_summary=None)

        result = await narrator.narrate(context)

        assert isinstance(result, str)
        assert len(result) > 0
