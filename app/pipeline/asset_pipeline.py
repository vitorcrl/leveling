from __future__ import annotations

import logging
from datetime import date

from app.domain.models_asset import Alert, DigestContext
from app.domain.ports import DataPort, DeliveryPort, NarratorPort, RulePort, ScorePort

logger = logging.getLogger(__name__)


class AssetPipeline:
    """
    Orquestrador genérico do pipeline de análise de ativos.

    Cada porta é injetada — o pipeline não sabe nem se importa com a
    implementação concreta: FIIs, REITs, ações ou qualquer outro ativo
    que implemente os Protocols em domain/ports.py.

    Fluxo: COLLECT → DIFF (deltas via callback) → FILTER → NARRATE → DELIVER
    """

    def __init__(
        self,
        data: DataPort,
        rules: RulePort,
        scorer: ScorePort,
        narrator: NarratorPort,
        delivery: DeliveryPort,
    ) -> None:
        self._data = data
        self._rules = rules
        self._scorer = scorer
        self._narrator = narrator
        self._delivery = delivery

    async def run(
        self,
        tickers: list[str],
        chat_id: int | str,
        run_date: date | None = None,
        enrich_snapshot=None,
    ) -> None:
        """
        Executa o pipeline para a lista de tickers e entrega ao chat_id informado.

        enrich_snapshot: callable opcional — recebe o AssetSnapshot recém-buscado
        e devolve um novo com os deltas preenchidos (comparação com semana anterior).
        Quando None, os deltas ficam em zero (comportamento padrão do DataPort).
        """
        today = run_date or date.today()
        snapshots = []
        all_alerts: list[Alert] = []
        scores: dict[str, int] = {}

        for ticker in tickers:
            try:
                snapshot = await self._data.fetch(ticker)
            except Exception:
                logger.exception("Falha ao buscar dados de %s — ticker ignorado", ticker)
                continue

            if enrich_snapshot is not None:
                try:
                    snapshot = await enrich_snapshot(snapshot)
                except Exception:
                    logger.exception("Falha ao enriquecer snapshot de %s — deltas zerados", ticker)

            try:
                alerts = self._rules.evaluate(snapshot)
            except Exception:
                logger.exception("Falha ao avaliar regras para %s", ticker)
                alerts = []

            try:
                scores[ticker] = self._scorer.score(snapshot)
            except Exception:
                logger.exception("Falha ao calcular score para %s", ticker)
                scores[ticker] = 0

            snapshots.append(snapshot)
            all_alerts.extend(alerts)

        context = DigestContext(
            date=today,
            snapshots=snapshots,
            alerts=all_alerts,
            scores=scores,
        )

        message = await self._narrator.narrate(context)
        await self._delivery.send(message, chat_id)
