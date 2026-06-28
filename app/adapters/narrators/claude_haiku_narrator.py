# Narrator principal do pipeline — só chama a Claude API quando há alertas.
# Implementa NarratorPort.
#
# Filosofia de custo zero:
#   - context.alerts vazio  → retorna mensagem estática (zero tokens)
#   - context.alerts não vazio → chama claude-haiku-4-5 com persona do analista
#
# A persona é carregada de dois arquivos externos:
#   - investor_profile.toml  → quem é o investidor (nome, perfil, foco)
#   - prompts/analyst_persona.txt → system prompt com as diretrizes do analista
#
# Separar persona do código permite ajustar o tom sem tocar no Python.
# Se a chamada à API falhar, o TemplateNarrator entra como fallback.

import logging
import tomllib
from pathlib import Path

import anthropic

from app.adapters.narrators.template_narrator import TemplateNarrator
from app.core.config import get_settings
from app.domain.models_asset import Alert, AlertSeverity, DigestContext

logger = logging.getLogger(__name__)

# Modelo mais barato da família Claude — ideal para narração de texto curto.
# Preço (Jun/2026): $1.00 input / $5.00 output por 1M tokens.
_MODEL = "claude-haiku-4-5"

# Limita a resposta a ~400 tokens — suficiente para um digest diário conciso.
_MAX_TOKENS = 512

_ICON = {
    AlertSeverity.critical: "🚨",
    AlertSeverity.warning: "⚠️",
    AlertSeverity.info: "🔔",
}

# Caminhos padrão relativos à raiz do projeto.
# Podem ser sobrescritos no construtor para testes ou deploys customizados.
_DEFAULT_PROFILE = Path("investor_profile.toml")
_DEFAULT_PERSONA = Path("app/adapters/narrators/prompts/analyst_persona.txt")


class ClaudeHaikuNarrator:
    """
    Narrator que usa claude-haiku-4-5 com persona de analista financeiro.
    Implementa NarratorPort.

    Custo: zero tokens quando não há alertas nem eventos.
    Fallback: TemplateNarrator quando a API está indisponível.
    """

    def __init__(
        self,
        api_key: str | None = None,
        profile_path: Path | str | None = None,
        persona_path: Path | str | None = None,
    ) -> None:
        self._api_key = api_key
        self._client: anthropic.AsyncAnthropic | None = None
        self._fallback = TemplateNarrator()

        # Carrega e compila o system prompt uma vez no construtor.
        # Barato: leitura de dois arquivos pequenos, feita só na inicialização.
        self._system_prompt = _load_system_prompt(
            profile_path=Path(profile_path) if profile_path else _DEFAULT_PROFILE,
            persona_path=Path(persona_path) if persona_path else _DEFAULT_PERSONA,
        )

    def _get_client(self) -> anthropic.AsyncAnthropic:
        # Lazy init — evita import-time de Settings que quebraria testes sem .env
        if self._client is None:
            key = self._api_key or get_settings().ANTHROPIC_API_KEY
            self._client = anthropic.AsyncAnthropic(api_key=key)
        return self._client

    async def narrate(self, context: DigestContext) -> str:
        # Caminho zero tokens — nem alertas nem eventos informativos (ex: proventos).
        # Checar len(alerts) e não total_alerts porque total_alerts ignora severity=info.
        # Se checarmos só total_alerts==0, um provento anunciado seria silenciado.
        if not context.alerts:
            logger.info(
                "ClaudeHaikuNarrator: no alerts for %d assets on %s — skipping API call",
                context.watchlist_size,
                context.date,
            )
            date_br = context.date.strftime("%d/%m/%Y")
            return (
                f"✅ FIIs — {date_br}\n"
                f"Todos os {context.watchlist_size} fundos dentro dos parâmetros."
            )

        logger.info(
            "ClaudeHaikuNarrator: calling %s for %d alerts on %s",
            _MODEL,
            context.total_alerts,
            context.date,
        )

        try:
            client = self._get_client()
            user_prompt = _build_user_prompt(context)

            response = await client.messages.create(
                model=_MODEL,
                max_tokens=_MAX_TOKENS,
                system=self._system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )

            text = response.content[0].text.strip()

            logger.info(
                "ClaudeHaikuNarrator: received %d chars, stop_reason=%s",
                len(text),
                response.stop_reason,
            )

            return text

        except anthropic.APIStatusError as exc:
            logger.warning(
                "ClaudeHaikuNarrator: API error %s — falling back to TemplateNarrator",
                exc.status_code,
            )
        except anthropic.APIConnectionError:
            logger.warning(
                "ClaudeHaikuNarrator: connection error — falling back to TemplateNarrator"
            )
        except Exception:
            logger.exception(
                "ClaudeHaikuNarrator: unexpected error — falling back to TemplateNarrator"
            )

        return await self._fallback.narrate(context)


# ---------------------------------------------------------------------------
# Carregamento da persona
# ---------------------------------------------------------------------------


def _load_system_prompt(profile_path: Path, persona_path: Path) -> str:
    """
    Lê o investor_profile.toml e injeta os valores no template analyst_persona.txt.
    O resultado é o system prompt final enviado para a Claude.
    Retorna string vazia se algum arquivo não existir — o narrator ainda funciona
    sem persona, só perde a personalização.
    """
    if not profile_path.exists():
        logger.warning("investor_profile.toml not found at %s — using generic prompt", profile_path)
        return ""

    if not persona_path.exists():
        logger.warning("analyst_persona.txt not found at %s — using generic prompt", persona_path)
        return ""

    with open(profile_path, "rb") as f:
        profile = tomllib.load(f)

    persona_template = persona_path.read_text(encoding="utf-8")

    # Achata o TOML aninhado em chaves com prefixo de seção para o format()
    # ex: profile["fii"]["foco"] → fii_foco no template
    flat = _flatten_profile(profile)

    try:
        return persona_template.format(**flat)
    except KeyError as exc:
        logger.warning("analyst_persona.txt references missing key %s — using raw template", exc)
        return persona_template


def _flatten_profile(profile: dict, prefix: str = "") -> dict[str, str]:
    """
    Converte {'investor': {'nome': 'Vitor'}, 'fii': {'foco': [...]}}
    em {'nome': 'Vitor', 'fii_foco': 'papel, logística', ...}
    para uso direto no str.format() do template.
    """
    result: dict[str, str] = {}
    for key, value in profile.items():
        if isinstance(value, dict):
            # Seção aninhada — achata com prefixo, exceto [investor] que vai sem prefixo
            sub_prefix = "" if key == "investor" else f"{key}_"
            result.update(_flatten_profile(value, prefix=sub_prefix))
        elif isinstance(value, list):
            result[f"{prefix}{key}"] = ", ".join(str(v) for v in value)
        else:
            result[f"{prefix}{key}"] = str(value)
    return result


# ---------------------------------------------------------------------------
# Construção do prompt do usuário
# ---------------------------------------------------------------------------


def _build_user_prompt(context: DigestContext) -> str:
    """
    Monta a mensagem do usuário com os alertas do dia.
    O system prompt (persona) já foi injetado separado — aqui só vai o contexto.
    """
    date_br = context.date.strftime("%d/%m/%Y")
    alerts_text = _format_alerts(context.alerts)

    return (
        f"Data: {date_br}\n"
        f"Watchlist: {context.watchlist_size} fundos\n"
        f"Alertas: {context.total_alerts} | Eventos: {context.total_events}\n"
        f"\n"
        f"{alerts_text}"
    )


def _format_alerts(alerts: list[Alert]) -> str:
    """Formata alertas ordenados por severity (críticos primeiro) para o prompt."""
    if not alerts:
        return "(sem alertas)"

    _order = {AlertSeverity.critical: 0, AlertSeverity.warning: 1, AlertSeverity.info: 2}
    sorted_alerts = sorted(alerts, key=lambda a: (_order[a.severity], a.ticker))

    lines: list[str] = []
    for alert in sorted_alerts:
        icon = _ICON[alert.severity]
        streak = f" (há {alert.streak} semanas)" if alert.streak > 1 else ""
        lines.append(f"{icon} {alert.ticker} [{alert.rule}]: {alert.message}{streak}")

    return "\n".join(lines)
