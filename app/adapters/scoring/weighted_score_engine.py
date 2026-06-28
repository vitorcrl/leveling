# Motor de score de oportunidade de compra para ativos.
# Implementa ScorePort — injetado no AssetPipeline pelo fii_runner.py.
#
# A lógica é código puro: sem I/O, sem banco, sem Claude.
# Recebe um AssetSnapshot e devolve um inteiro 0–100.
# Score alto = oportunidade melhor = mais peso no orçamento semanal.
#
# A fórmula vem da spec (Parte 2) e é deliberadamente simples:
# fácil de auditar, fácil de ajustar, fácil de testar.

import logging

from app.domain.models_asset import AssetSnapshot
from app.domain.ports import ScorePort

logger = logging.getLogger(__name__)

# Pesos padrão para FIIs brasileiros — podem ser sobrescritos na instanciação.
# A soma dos pesos positivos máximos = 100 (40 + 30 + 10 + 20 de bônus extras).
# Os penalizadores podem levar o score abaixo de 0 (clampado em 0 no final).
FII_WEIGHTS: dict[str, float] = {
    "pvp": 40.0,       # até 40 pts — P/VP abaixo de 1.0 gera desconto proporcional
    "dy": 30.0,        # até 30 pts — DY proporcional, cap em 15%
    "delta_dy": 10.0,  # +10 se DY subindo, -15 se caindo mais de 1pp
    "vacancia": 2.0,   # -2 pts por ponto percentual acima de 15%
    "ltv": 1.5,        # -1.5 pts por ponto percentual acima de 60%
    "liquidez": 20.0,  # -20 pts se liquidez abaixo de R$500k/dia
}


class WeightedScoreEngine:
    """
    Calcula o score de oportunidade (0–100) de um ativo usando pesos configuráveis.
    Implementa ScorePort.

    Uso:
        engine = WeightedScoreEngine()               # pesos padrão FII
        engine = WeightedScoreEngine(weights=REIT_WEIGHTS)  # pesos customizados
        score = engine.score(snapshot)               # retorna int 0–100
    """

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        # Permite injetar pesos diferentes para REITs (Parte 3) sem criar nova classe
        self._w = weights or FII_WEIGHTS

    def score(self, snapshot: AssetSnapshot) -> int:
        """
        Aplica a fórmula de score ao snapshot e retorna um inteiro 0–100.
        Nunca retorna negativo nem acima de 100 — clampado nas extremidades.
        """
        raw = self._calculate(snapshot)
        result = max(0, min(100, round(raw)))

        logger.debug(
            "Score %s: raw=%.1f → clamped=%d",
            snapshot.ticker, raw, result,
        )

        return result

    def _calculate(self, s: AssetSnapshot) -> float:
        score = 0.0

        # --- P/VP (até +40 pts) ---
        # Quanto mais abaixo de 1.0, maior o desconto sobre o patrimônio.
        # pvp=0.0 significa dado ausente — não pontua nem penaliza.
        if s.pvp > 0.0:
            if s.pvp < 1.0:
                # ex: pvp=0.85 → (1.0 - 0.85) * 40 = 6 pts
                score += (1.0 - s.pvp) * self._w["pvp"]
            # pvp >= 1.0 não pontua, mas também não penaliza aqui
            # (a regra de P/VP alto já gera alerta no FIIRuleSet)

        # --- DY 12M (até +30 pts) ---
        # Proporcional ao DY, com cap em 15% para não inflar fundos arriscados.
        # ex: dy=10% → min(10/15, 1.0) * 30 = 20 pts
        # ex: dy=18% → min(18/15, 1.0) * 30 = 30 pts (cap)
        score += min(s.dy_12m / 15.0, 1.0) * self._w["dy"]

        # --- Delta DY (+10 ou -15 pts) ---
        # DY subindo é sinal positivo; queda acentuada é sinal de deterioração.
        if s.delta_dy > 0:
            score += self._w["delta_dy"]           # +10 pts
        elif s.delta_dy < -1.0:
            score -= self._w["delta_dy"] * 1.5     # -15 pts

        # --- Vacância (-2 pts por pp acima de 15%) ---
        # Só aplica para fundos de tijolo (vacancia não é None).
        # ex: vacancia=20% → (20 - 15) * 2 = -10 pts
        if s.vacancia is not None and s.vacancia > 15.0:
            score -= (s.vacancia - 15.0) * self._w["vacancia"]

        # --- LTV (-1.5 pts por pp acima de 60%) ---
        # Só aplica para fundos de papel (ltv não é None).
        # ex: ltv=74% → (74 - 60) * 1.5 = -21 pts
        if s.ltv is not None and s.ltv > 60.0:
            score -= (s.ltv - 60.0) * self._w["ltv"]

        # --- Liquidez baixa (-20 pts fixos) ---
        # Penalização binária: ou tem liquidez mínima ou não tem.
        # Os thresholds aqui (500k, 15%, 60%) são fixos por design — o score
        # é usado para alocação relativa entre fundos, não para disparar alertas.
        # Os alertas (que o usuário vê) lêem de Settings. Se mudar o threshold
        # no .env, o alerta muda mas o peso no score permanece estável.
        if s.liquidez < 500_000:
            score -= self._w["liquidez"]

        return score
