# Implementação de RulePort para ativos (FIIs brasileiros e REITs).
# Cada regra é um método privado que recebe um AssetSnapshot e retorna
# uma lista de Alert — vazia se nada disparou, com um item se disparou.
#
# O AssetRuleSet.evaluate() chama todas as regras em sequência e agrega
# os alertas. Isso permite que um mesmo fundo dispare múltiplos alertas
# no mesmo dia (ex: DY baixo E vacância alta ao mesmo tempo).
#
# Os thresholds vêm de Settings — nenhum número mágico hardcoded aqui.
# Para ajustar um threshold, basta mudar o .env e reiniciar o processo.

import logging

from app.core.config import Settings, get_settings
from app.domain.models_asset import Alert, AlertSeverity, AssetSnapshot

logger = logging.getLogger(__name__)


class AssetRuleSet:
    """
    Conjunto de 9 regras de análise para ativos da watchlist.
    Implementa RulePort — injetado no AssetPipeline pelo journey_runner.py.

    Uso:
        rules = AssetRuleSet(settings)
        alerts = rules.evaluate(snapshot)
    """

    def __init__(self, settings: Settings | None = None) -> None:
        # Aceita settings injetado (útil nos testes para passar valores customizados)
        # ou carrega o singleton cacheado como padrão.
        self._s = settings or get_settings()

    def evaluate(self, snapshot: AssetSnapshot) -> list[Alert]:
        """
        Aplica todas as regras ao snapshot e retorna os alertas disparados.
        Nunca lança exceção — erros em uma regra são logados e ignorados
        para não interromper a avaliação das demais.
        """
        alerts: list[Alert] = []

        rules = [
            self._rule_low_dy,
            self._rule_falling_dy,
            self._rule_overvalued_pvp,
            self._rule_discount_pvp,
            self._rule_high_vacancia,
            self._rule_high_ltv,
            self._rule_low_liquidez,
            self._rule_provento_announced,
            self._rule_price_drop,
        ]

        for rule in rules:
            try:
                alerts.extend(rule(snapshot))
            except Exception:
                # Uma regra com dado inesperado não deve derrubar as outras
                logger.exception("Error evaluating rule %s for %s", rule.__name__, snapshot.ticker)

        return alerts

    # -------------------------------------------------------------------------
    # Regra 1 — DY 12M abaixo do mínimo
    # Fundos com DY baixo podem estar com problemas de geração de renda ou
    # com cotação muito inflada em relação aos proventos distribuídos.
    # -------------------------------------------------------------------------
    def _rule_low_dy(self, s: AssetSnapshot) -> list[Alert]:
        if s.dy_12m == 0.0:
            return []
        if s.dy_12m < self._s.ASSET_MIN_DY:
            return [Alert(
                ticker=s.ticker,
                rule="low_dy",
                message=f"DY 12M de {s.dy_12m:.1f}% abaixo do mínimo de {self._s.ASSET_MIN_DY:.1f}%",
                severity=AlertSeverity.warning,
                value=s.dy_12m,
                threshold=self._s.ASSET_MIN_DY,
            )]
        return []

    # -------------------------------------------------------------------------
    # Regra 2 — DY caindo na semana
    # Queda consistente no DY pode sinalizar vacância crescente ou
    # redução de proventos — sinal de deterioração antes de aparecer no preço.
    # -------------------------------------------------------------------------
    def _rule_falling_dy(self, s: AssetSnapshot) -> list[Alert]:
        if s.delta_dy < self._s.ASSET_MIN_DELTA_DY:
            return [Alert(
                ticker=s.ticker,
                rule="falling_dy",
                message=(
                    f"DY caindo: {s.dy_12m:.1f}% "
                    f"(variação de {s.delta_dy:+.2f}pp em 7 dias)"
                ),
                severity=AlertSeverity.warning,
                value=s.delta_dy,
                threshold=self._s.ASSET_MIN_DELTA_DY,
            )]
        return []

    # -------------------------------------------------------------------------
    # Regra 3 — P/VP sobrevalorizado
    # P/VP acima de 1.15 significa que o mercado está pagando 15% a mais
    # do que o patrimônio do fundo vale — margem de segurança reduzida.
    # -------------------------------------------------------------------------
    def _rule_overvalued_pvp(self, s: AssetSnapshot) -> list[Alert]:
        # pvp=0.0 significa que a API não retornou o dado — ignorar
        if s.pvp == 0.0:
            return []
        if s.pvp > self._s.ASSET_MAX_PVP:
            return [Alert(
                ticker=s.ticker,
                rule="overvalued_pvp",
                message=f"P/VP de {s.pvp:.2f} acima do limite de {self._s.ASSET_MAX_PVP:.2f}",
                severity=AlertSeverity.warning,
                value=s.pvp,
                threshold=self._s.ASSET_MAX_PVP,
            )]
        return []

    # -------------------------------------------------------------------------
    # Regra 4 — P/VP em desconto
    # P/VP abaixo de 0.80 é oportunidade: o mercado está pagando menos
    # do que o patrimônio vale. Alerta severity=info (evento positivo).
    # -------------------------------------------------------------------------
    def _rule_discount_pvp(self, s: AssetSnapshot) -> list[Alert]:
        if s.pvp == 0.0:
            return []
        if s.pvp < self._s.ASSET_PVP_DISCOUNT:
            return [Alert(
                ticker=s.ticker,
                rule="discount_pvp",
                message=f"P/VP em desconto: {s.pvp:.2f} (abaixo de {self._s.ASSET_PVP_DISCOUNT:.2f})",
                severity=AlertSeverity.info,
                value=s.pvp,
                threshold=self._s.ASSET_PVP_DISCOUNT,
            )]
        return []

    # -------------------------------------------------------------------------
    # Regra 5 — Vacância alta (fundos de tijolo)
    # Vacância elevada reduz a receita de aluguel e, consequentemente,
    # os proventos. Só avalia se o campo está preenchido (fundos tijolo).
    # -------------------------------------------------------------------------
    def _rule_high_vacancia(self, s: AssetSnapshot) -> list[Alert]:
        if s.vacancia is None:
            # Fundo de papel (CRI/LCI) não tem vacância — regra não se aplica
            return []
        if s.vacancia > self._s.ASSET_MAX_VACANCIA:
            return [Alert(
                ticker=s.ticker,
                rule="high_vacancia",
                message=(
                    f"Vacância de {s.vacancia:.1f}% acima do limite de "
                    f"{self._s.ASSET_MAX_VACANCIA:.1f}%"
                    + (f" (+{s.delta_vacancia:.1f}pp vs semana)" if s.delta_vacancia > 0 else "")
                ),
                severity=AlertSeverity.warning,
                value=s.vacancia,
                threshold=self._s.ASSET_MAX_VACANCIA,
            )]
        return []

    # -------------------------------------------------------------------------
    # Regra 6 — LTV alto (fundos de papel)
    # LTV alto significa que os imóveis que lastreiam os CRIs estão muito
    # alavancados — risco de inadimplência do devedor aumenta.
    # Só avalia se o campo está preenchido (fundos papel).
    # -------------------------------------------------------------------------
    def _rule_high_ltv(self, s: AssetSnapshot) -> list[Alert]:
        if s.ltv is None:
            # Fundo de tijolo não tem LTV — regra não se aplica
            return []
        severity = (
            AlertSeverity.critical if s.ltv > self._s.ASSET_MAX_LTV + 10
            else AlertSeverity.warning
        )
        if s.ltv > self._s.ASSET_MAX_LTV:
            return [Alert(
                ticker=s.ticker,
                rule="high_ltv",
                message=f"LTV em {s.ltv:.1f}% acima do limite de {self._s.ASSET_MAX_LTV:.1f}%",
                severity=severity,
                value=s.ltv,
                threshold=self._s.ASSET_MAX_LTV,
            )]
        return []

    # -------------------------------------------------------------------------
    # Regra 7 — Liquidez baixa
    # Volume financeiro diário abaixo de R$500k dificulta entrada e saída
    # de posição sem impactar o preço (spread alto, risco de não conseguir vender).
    # -------------------------------------------------------------------------
    def _rule_low_liquidez(self, s: AssetSnapshot) -> list[Alert]:
        if s.liquidez < self._s.ASSET_MIN_LIQUIDEZ:
            return [Alert(
                ticker=s.ticker,
                rule="low_liquidez",
                message=(
                    f"Liquidez de R${s.liquidez:,.0f}/dia abaixo do mínimo "
                    f"de R${self._s.ASSET_MIN_LIQUIDEZ:,.0f}"
                ),
                severity=AlertSeverity.warning,
                value=s.liquidez,
                threshold=self._s.ASSET_MIN_LIQUIDEZ,
            )]
        return []

    # -------------------------------------------------------------------------
    # Regra 8 — Provento anunciado
    # Evento informativo: o fundo declarou proventos hoje.
    # severity=info porque é positivo — o narrator formata com 🔔 em vez de ⚠️.
    # -------------------------------------------------------------------------
    def _rule_provento_announced(self, s: AssetSnapshot) -> list[Alert]:
        if s.provento_anunciado is not None and s.provento_anunciado > 0:
            return [Alert(
                ticker=s.ticker,
                rule="provento_announced",
                message=f"Provento anunciado: R$ {s.provento_anunciado:.4f}/cota",
                severity=AlertSeverity.info,
                value=s.provento_anunciado,
            )]
        return []

    # -------------------------------------------------------------------------
    # Regra 9 — Queda brusca de cotação
    # Queda acima de 5% em um dia pode indicar fato relevante negativo,
    # crise setorial ou movimento de mercado que merece atenção imediata.
    # -------------------------------------------------------------------------
    def _rule_price_drop(self, s: AssetSnapshot) -> list[Alert]:
        # delta_price é negativo para queda (ex: -6.2 = caiu 6.2%)
        if s.delta_price < -self._s.ASSET_MAX_PRICE_DROP:
            return [Alert(
                ticker=s.ticker,
                rule="price_drop",
                message=(
                    f"Queda de {abs(s.delta_price):.1f}% hoje "
                    f"(limite: {self._s.ASSET_MAX_PRICE_DROP:.1f}%)"
                ),
                severity=AlertSeverity.critical,
                value=s.delta_price,
                threshold=-self._s.ASSET_MAX_PRICE_DROP,
            )]
        return []
