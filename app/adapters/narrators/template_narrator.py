# Narrator de fallback que formata os alertas como texto estruturado
# sem chamar nenhuma API. Usado quando:
#   - ANTHROPIC_API_KEY não está configurada
#   - A API da Claude está fora do ar
#   - O operador quer economizar tokens em dias de muitos alertas
#
# A mensagem segue o mesmo formato dos exemplos da spec para que
# o Telegram renderize igual, independente de qual narrator foi usado.

import logging
from app.domain.models_asset import Alert, AlertSeverity, DigestContext

logger = logging.getLogger(__name__)

# Ícones por severity — mantém consistência com o exemplo da spec
_ICON = {
    AlertSeverity.critical: "🚨",
    AlertSeverity.warning: "⚠️",
    AlertSeverity.info: "🔔",
}


class TemplateNarrator:
    """
    Formata os alertas em texto estruturado sem chamar a Claude API.
    Implementa NarratorPort — substitui o ClaudeHaikuNarrator como fallback.

    A saída é determinística: mesmo input → mesmo output.
    Útil para testes e para dias em que a API está indisponível.
    """

    async def narrate(self, context: DigestContext) -> str:
        logger.info(
            "TemplateNarrator: formatting %d alerts for %s",
            len(context.alerts),
            context.date,
        )

        date_br = context.date.strftime("%d/%m/%Y")
        lines: list[str] = [f"📊 FIIs — {date_br}", ""]

        # Cotação de cada fundo — disponível mesmo sem plano pago
        snap_by_ticker = {s.ticker: s for s in context.snapshots}
        for snap in context.snapshots:
            arrow = "🔴" if snap.delta_price < 0 else "🟢"
            sign = "+" if snap.delta_price >= 0 else ""
            lines.append(
                f"{arrow} {snap.ticker}  R$ {snap.price:.2f}  {sign}{snap.delta_price:.2f}%"
            )
        if context.snapshots:
            lines.append("")

        _severity_order = {
            AlertSeverity.critical: 0,
            AlertSeverity.warning: 1,
            AlertSeverity.info: 2,
        }

        by_ticker: dict[str, list[Alert]] = {}
        for alert in context.alerts:
            by_ticker.setdefault(alert.ticker, []).append(alert)

        sorted_tickers = sorted(
            by_ticker.keys(),
            key=lambda t: min(_severity_order[a.severity] for a in by_ticker[t]),
        )

        for ticker in sorted_tickers:
            alerts_list = by_ticker[ticker]
            problems = [a for a in alerts_list if a.severity != AlertSeverity.info]
            events = [a for a in alerts_list if a.severity == AlertSeverity.info]

            if problems:
                top_severity = (
                    AlertSeverity.critical
                    if any(a.severity == AlertSeverity.critical for a in problems)
                    else AlertSeverity.warning
                )
                lines.append(f"{_ICON[top_severity]} {ticker}")
                for alert in problems:
                    streak_suffix = f" — há {alert.streak} semanas" if alert.streak > 1 else ""
                    lines.append(f"• {alert.message}{streak_suffix}")
                lines.append("")

            for event in events:
                lines.append(f"{_ICON[AlertSeverity.info]} {ticker} — {event.message}")

        if context.total_events > 0:
            lines.append("")

        lines.append(
            f"Watchlist: {context.watchlist_size} fundos | "
            f"{context.total_alerts} alertas | "
            f"{context.total_events} eventos"
        )

        return "\n".join(lines)
