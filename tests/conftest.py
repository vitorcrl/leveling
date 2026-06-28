from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_anthropic_client():
    with patch("app.adapters.narrators.claude_haiku_narrator.anthropic.AsyncAnthropic") as mock_cls:
        client = AsyncMock()
        mock_cls.return_value = client
        yield client


def make_claude_response(text: str, input_tokens: int = 100, output_tokens: int = 50):
    response = MagicMock()
    response.content = [MagicMock(text=text)]
    response.usage.input_tokens = input_tokens
    response.usage.output_tokens = output_tokens
    return response