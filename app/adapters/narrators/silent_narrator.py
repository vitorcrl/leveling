# Narrator usado quando nenhum alerta foi disparado no dia.
# Implementa NarratorPort — zero tokens consumidos, zero chamadas à API.
# É a implementação padrão: só entra o ClaudeHaikuNarrator quando há alertas.

import logging

from app.domain.models_asset import DigestContext

logger = logging.getLogger(__name__)


class SilentNarrator:
    """
    Retorna uma mensagem padrão sem chamar nenhuma API.
    Usado pelo fii_runner quando DigestContext.total_alerts == 0.

    Custo: zero tokens, zero latência extra.
    """

    async def narrate(self, context: DigestContext) -> str:
        logger.info(
            "SilentNarrator: no alerts for %d assets on %s",
            context.watchlist_size,
            context.date,
        )

        # Formata a data no padrão brasileiro para a mensagem do Telegram
        date_br = context.date.strftime("%d/%m/%Y")

        return (
            f"✅ FIIs — {date_br}\n"
            f"Todos os {context.watchlist_size} fundos dentro dos parâmetros."
        )
