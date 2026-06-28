from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters.narrators.claude_haiku_narrator import (
    ClaudeHaikuNarrator,
    _flatten_profile,
    _format_alerts,
    _load_system_prompt,
)
from app.adapters.narrators.silent_narrator import SilentNarrator
from app.adapters.narrators.template_narrator import TemplateNarrator
from app.domain.models_asset import Alert, AlertSeverity, AssetSnapshot, DigestContext


# ---------------------------------------------------------------------------
# Fixtures compartilhadas
# ---------------------------------------------------------------------------


def make_snapshot(ticker: str = "TEST11") -> AssetSnapshot:
    return AssetSnapshot(
        ticker=ticker, market="BR", date=date(2026, 6, 26),
        price=100.0, dy_12m=10.0, pvp=0.95, liquidez=1_000_000,
    )


def make_context(alerts: list[Alert] | None = None, n_snapshots: int = 3) -> DigestContext:
    return DigestContext(
        date=date(2026, 6, 26),
        snapshots=[make_snapshot(f"F{i}11") for i in range(n_snapshots)],
        alerts=alerts or [],
    )


def make_alert(
    ticker: str = "KNCR11",
    rule: str = "low_dy",
    severity: AlertSeverity = AlertSeverity.warning,
    streak: int = 1,
) -> Alert:
    return Alert(
        ticker=ticker, rule=rule,
        message=f"Alerta de teste ({rule})",
        severity=severity, streak=streak,
    )


def make_claude_response(text: str):
    response = MagicMock()
    response.content = [MagicMock(text=text)]
    response.stop_reason = "end_turn"
    return response


# ---------------------------------------------------------------------------
# SilentNarrator
# ---------------------------------------------------------------------------


class TestSilentNarrator:
    async def test_returns_ok_message(self):
        ctx = make_context(alerts=[], n_snapshots=5)
        msg = await SilentNarrator().narrate(ctx)
        assert "✅" in msg
        assert "5 fundos" in msg

    async def test_formats_date_in_portuguese_style(self):
        ctx = make_context()
        msg = await SilentNarrator().narrate(ctx)
        assert "26/06/2026" in msg

    async def test_implements_narrator_port(self):
        from app.domain.ports import NarratorPort
        assert isinstance(SilentNarrator(), NarratorPort)


# ---------------------------------------------------------------------------
# TemplateNarrator
# ---------------------------------------------------------------------------


class TestTemplateNarrator:
    async def test_returns_header_with_date(self):
        ctx = make_context(alerts=[make_alert()])
        msg = await TemplateNarrator().narrate(ctx)
        assert "26/06/2026" in msg

    async def test_critical_appears_before_warning(self):
        alerts = [
            make_alert(ticker="ZEBRA11", rule="low_dy", severity=AlertSeverity.warning),
            make_alert(ticker="AAAA11", rule="price_drop", severity=AlertSeverity.critical),
        ]
        ctx = make_context(alerts=alerts)
        msg = await TemplateNarrator().narrate(ctx)
        assert msg.index("AAAA11") < msg.index("ZEBRA11")

    async def test_shows_streak_suffix_when_greater_than_one(self):
        alert = make_alert(streak=3)
        ctx = make_context(alerts=[alert])
        msg = await TemplateNarrator().narrate(ctx)
        assert "3 semanas" in msg

    async def test_no_streak_suffix_when_streak_is_one(self):
        alert = make_alert(streak=1)
        ctx = make_context(alerts=[alert])
        msg = await TemplateNarrator().narrate(ctx)
        assert "semana" not in msg

    async def test_info_alert_shown_inline(self):
        alert = make_alert(rule="provento_announced", severity=AlertSeverity.info)
        ctx = make_context(alerts=[alert])
        msg = await TemplateNarrator().narrate(ctx)
        assert "🔔" in msg

    async def test_footer_shows_correct_counts(self):
        alerts = [
            make_alert(severity=AlertSeverity.warning),
            make_alert(ticker="MXRF11", severity=AlertSeverity.critical),
            make_alert(ticker="KNCR11", rule="provento_announced", severity=AlertSeverity.info),
        ]
        ctx = make_context(alerts=alerts, n_snapshots=5)
        msg = await TemplateNarrator().narrate(ctx)
        assert "5 fundos" in msg
        assert "2 alertas" in msg
        assert "1 eventos" in msg

    async def test_implements_narrator_port(self):
        from app.domain.ports import NarratorPort
        assert isinstance(TemplateNarrator(), NarratorPort)


# ---------------------------------------------------------------------------
# ClaudeHaikuNarrator
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_anthropic():
    """Mocka o AsyncAnthropic para não fazer chamadas reais à API."""
    with patch("app.adapters.narrators.claude_haiku_narrator.anthropic.AsyncAnthropic") as mock_cls:
        client = AsyncMock()
        mock_cls.return_value = client
        yield client


class TestClaudeHaikuNarratorZeroTokenPath:
    async def test_returns_ok_message_when_no_alerts(self, tmp_path):
        ctx = make_context(alerts=[])
        narrator = ClaudeHaikuNarrator(
            api_key="dummy",
            profile_path=tmp_path / "missing.toml",
            persona_path=tmp_path / "missing.txt",
        )
        msg = await narrator.narrate(ctx)
        assert "✅" in msg

    async def test_does_not_call_api_when_no_alerts(self, mock_anthropic, tmp_path):
        ctx = make_context(alerts=[])
        narrator = ClaudeHaikuNarrator(
            api_key="dummy",
            profile_path=tmp_path / "missing.toml",
            persona_path=tmp_path / "missing.txt",
        )
        await narrator.narrate(ctx)
        mock_anthropic.messages.create.assert_not_called()


class TestClaudeHaikuNarratorAPICall:
    async def test_calls_api_when_alerts_exist(self, mock_anthropic, tmp_path):
        mock_anthropic.messages.create = AsyncMock(
            return_value=make_claude_response("Análise do dia.")
        )
        ctx = make_context(alerts=[make_alert()])
        narrator = ClaudeHaikuNarrator(
            api_key="dummy",
            profile_path=tmp_path / "missing.toml",
            persona_path=tmp_path / "missing.txt",
        )
        result = await narrator.narrate(ctx)
        assert result == "Análise do dia."
        mock_anthropic.messages.create.assert_called_once()

    async def test_uses_haiku_model(self, mock_anthropic, tmp_path):
        mock_anthropic.messages.create = AsyncMock(
            return_value=make_claude_response("ok")
        )
        ctx = make_context(alerts=[make_alert()])
        narrator = ClaudeHaikuNarrator(
            api_key="dummy",
            profile_path=tmp_path / "missing.toml",
            persona_path=tmp_path / "missing.txt",
        )
        await narrator.narrate(ctx)
        call_kwargs = mock_anthropic.messages.create.call_args.kwargs
        assert "haiku" in call_kwargs["model"]

    async def test_calls_api_for_info_only_alerts(self, mock_anthropic, tmp_path):
        # Provento anunciado (info) deve também chamar a API
        mock_anthropic.messages.create = AsyncMock(
            return_value=make_claude_response("Provento anunciado!")
        )
        alerts = [make_alert(rule="provento_announced", severity=AlertSeverity.info)]
        ctx = make_context(alerts=alerts)
        narrator = ClaudeHaikuNarrator(
            api_key="dummy",
            profile_path=tmp_path / "missing.toml",
            persona_path=tmp_path / "missing.txt",
        )
        result = await narrator.narrate(ctx)
        assert result == "Provento anunciado!"


class TestClaudeHaikuNarratorFallback:
    async def test_falls_back_to_template_on_api_error(self, mock_anthropic, tmp_path):
        import anthropic as anthropic_module
        mock_anthropic.messages.create = AsyncMock(
            side_effect=anthropic_module.APIConnectionError(request=MagicMock())
        )
        ctx = make_context(alerts=[make_alert()])
        narrator = ClaudeHaikuNarrator(
            api_key="dummy",
            profile_path=tmp_path / "missing.toml",
            persona_path=tmp_path / "missing.txt",
        )
        result = await narrator.narrate(ctx)
        # Fallback do TemplateNarrator tem o header com data
        assert "26/06/2026" in result

    async def test_falls_back_on_status_error(self, mock_anthropic, tmp_path):
        import anthropic as anthropic_module
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_anthropic.messages.create = AsyncMock(
            side_effect=anthropic_module.APIStatusError(
                "rate limited", response=mock_response, body={}
            )
        )
        ctx = make_context(alerts=[make_alert()])
        narrator = ClaudeHaikuNarrator(
            api_key="dummy",
            profile_path=tmp_path / "missing.toml",
            persona_path=tmp_path / "missing.txt",
        )
        result = await narrator.narrate(ctx)
        assert "26/06/2026" in result

    async def test_falls_back_on_unexpected_exception(self, mock_anthropic, tmp_path):
        # Cobre linhas 132-133 — except Exception genérico
        mock_anthropic.messages.create = AsyncMock(
            side_effect=RuntimeError("unexpected")
        )
        ctx = make_context(alerts=[make_alert()])
        narrator = ClaudeHaikuNarrator(
            api_key="dummy",
            profile_path=tmp_path / "missing.toml",
            persona_path=tmp_path / "missing.txt",
        )
        result = await narrator.narrate(ctx)
        assert "26/06/2026" in result


class TestClaudeHaikuNarratorPersona:
    def test_loads_system_prompt_from_files(self, tmp_path):
        profile = tmp_path / "profile.toml"
        persona = tmp_path / "persona.txt"
        profile.write_text('[investor]\nnome = "Vitor"\nperfil = "moderado"\nhorizonte = "longo prazo"\nobjetivo = "renda"\naversao_volatilidade = "media"\n[fii]\nfoco = ["papel"]\nevitar = ["hotel"]\nmeta_dy_minimo = 9.0\n[reit]\nfoco = ["dividendos"]\nmoeda_referencia = "BRL"\n[acoes]\nestilo = "valor"\nmercados = ["BR"]')
        persona.write_text("Analista para {nome}, perfil {perfil}.")

        result = _load_system_prompt(profile, persona)
        assert "Vitor" in result
        assert "moderado" in result

    def test_returns_empty_string_when_profile_missing(self, tmp_path):
        result = _load_system_prompt(
            tmp_path / "missing.toml",
            tmp_path / "persona.txt",
        )
        assert result == ""

    def test_returns_empty_string_when_persona_missing(self, tmp_path):
        profile = tmp_path / "profile.toml"
        profile.write_text('[investor]\nnome = "X"')
        result = _load_system_prompt(profile, tmp_path / "missing.txt")
        assert result == ""

    def test_returns_raw_template_when_key_missing_in_profile(self, tmp_path):
        profile = tmp_path / "profile.toml"
        persona = tmp_path / "persona.txt"
        profile.write_text('[investor]\nnome = "Vitor"')
        persona.write_text("Analista para {nome}, perfil {perfil_inexistente}.")
        result = _load_system_prompt(profile, persona)
        assert "{perfil_inexistente}" in result


class TestFlattenProfile:
    def test_flattens_investor_section_without_prefix(self):
        profile = {"investor": {"nome": "Vitor", "perfil": "moderado"}}
        flat = _flatten_profile(profile)
        assert flat["nome"] == "Vitor"
        assert flat["perfil"] == "moderado"

    def test_flattens_nested_section_with_prefix(self):
        profile = {"fii": {"foco": ["papel", "logística"]}}
        flat = _flatten_profile(profile)
        assert flat["fii_foco"] == "papel, logística"

    def test_converts_list_to_comma_separated_string(self):
        profile = {"fii": {"evitar": ["hotel", "desenvolvimento"]}}
        flat = _flatten_profile(profile)
        assert flat["fii_evitar"] == "hotel, desenvolvimento"


class TestFormatAlerts:
    def test_critical_before_warning_in_output(self):
        alerts = [
            make_alert(ticker="ZZZ11", severity=AlertSeverity.warning),
            make_alert(ticker="AAA11", severity=AlertSeverity.critical),
        ]
        result = _format_alerts(alerts)
        assert result.index("AAA11") < result.index("ZZZ11")

    def test_streak_note_when_greater_than_one(self):
        alert = make_alert(streak=4)
        result = _format_alerts([alert])
        assert "4 semanas" in result

    def test_no_streak_note_when_streak_is_one(self):
        alert = make_alert(streak=1)
        result = _format_alerts([alert])
        assert "semana" not in result

    def test_empty_list_returns_placeholder(self):
        result = _format_alerts([])
        assert result == "(sem alertas)"
