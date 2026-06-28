# Placeholder para integração futura com APIs externas de análise de FIIs.
# Implementa RulePort — pode ser injetado no lugar do FIIRuleSet ou em
# conjunto com ele (o pipeline aceita qualquer implementação da porta).
#
# Candidatos naturais para preencher este adapter:
#   - Funds Explorer API  → dados fundamentalistas detalhados de FIIs
#   - Status Invest API   → rankings e comparativos de setor
#   - Clube FII API       → ratings e análises editoriais
#
# Para ativar: implemente _fetch_alerts() chamando a API escolhida e
# mapeie a resposta para objetos Alert. O pipeline não muda nada.

import logging

from app.domain.models_asset import Alert, AssetSnapshot

logger = logging.getLogger(__name__)


class ExternalAPIRuleAdapter:
    """
    Adapter de regras via API externa — atualmente retorna lista vazia.

    Quando implementado, este adapter pode:
      - Complementar o FIIRuleSet com dados que a brapi.dev não fornece
      - Substituir regras locais por ratings calculados externamente
      - Adicionar análise editorial (ex: "fundo em watchlist negativa")

    Para usar junto com FIIRuleSet no pipeline, crie um CompositeRuleSet
    que chame os dois evaluate() e una os resultados — sem mudar o pipeline.
    """

    def __init__(self, api_url: str = "", api_key: str = "") -> None:
        self._api_url = api_url
        self._api_key = api_key

        if not api_url:
            logger.info(
                "ExternalAPIRuleAdapter initialized without api_url — "
                "will return empty alerts until configured"
            )

    def evaluate(self, snapshot: AssetSnapshot) -> list[Alert]:
        """
        Consulta a API externa e retorna alertas para o ticker.
        Atualmente não implementado — retorna lista vazia (comportamento seguro).
        """
        if not self._api_url:
            return []

        # TODO: implementar quando uma API externa for escolhida
        # Esqueleto do fluxo esperado:
        #
        #   response = httpx.get(
        #       f"{self._api_url}/fiis/{snapshot.ticker}/alerts",
        #       headers={"Authorization": f"Bearer {self._api_key}"},
        #   )
        #   return [_map_to_alert(snapshot.ticker, item) for item in response.json()]
        #
        # Nota: se a API externa for async, mudar a assinatura para
        # `async def evaluate(...)` e atualizar o pipeline accordingly.

        logger.debug("ExternalAPIRuleAdapter.evaluate called but not implemented for %s", snapshot.ticker)
        return []
