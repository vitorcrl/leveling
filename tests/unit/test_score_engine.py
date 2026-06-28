from datetime import date

import pytest

from app.adapters.scoring.weighted_score_engine import FII_WEIGHTS, WeightedScoreEngine
from app.domain.models_asset import AssetSnapshot


def make_snapshot(**kwargs) -> AssetSnapshot:
    """Snapshot com defaults neutros — score ~18 (só DY contribui)."""
    defaults = dict(
        ticker="TEST11",
        market="BR",
        date=date(2026, 6, 26),
        price=100.0,
        dy_12m=9.0,
        pvp=0.0,       # 0.0 = dado ausente, não pontua
        liquidez=1_000_000,
    )
    defaults.update(kwargs)
    return AssetSnapshot(**defaults)


class TestScoreBoundaries:
    def test_score_is_never_negative(self):
        engine = WeightedScoreEngine()
        # Pior caso possível: sem DY, sem pvp, liquidez zero, LTV altíssimo
        snap = make_snapshot(dy_12m=0.0, pvp=0.0, liquidez=0.0, ltv=200.0)
        assert engine.score(snap) == 0

    def test_score_is_never_above_100(self):
        engine = WeightedScoreEngine()
        # Melhor caso: pvp baixíssimo, DY alto, delta positivo, liquidez ok
        snap = make_snapshot(dy_12m=20.0, pvp=0.01, liquidez=5_000_000, delta_dy=1.0)
        assert engine.score(snap) <= 100

    def test_score_is_integer(self):
        engine = WeightedScoreEngine()
        snap = make_snapshot(dy_12m=10.0, pvp=0.9)
        assert isinstance(engine.score(snap), int)


class TestPVPComponent:
    def test_pvp_below_one_adds_points(self):
        engine = WeightedScoreEngine()
        snap_discount = make_snapshot(pvp=0.85, dy_12m=0.0, liquidez=1_000_000)
        snap_no_pvp = make_snapshot(pvp=0.0, dy_12m=0.0, liquidez=1_000_000)
        assert engine.score(snap_discount) > engine.score(snap_no_pvp)

    def test_pvp_zero_does_not_score(self):
        engine = WeightedScoreEngine()
        # pvp=0.0 significa dado ausente — não pontua nem penaliza
        snap = make_snapshot(pvp=0.0, dy_12m=0.0, liquidez=1_000_000)
        assert engine.score(snap) == 0

    def test_pvp_above_one_does_not_add_points(self):
        engine = WeightedScoreEngine()
        snap_above = make_snapshot(pvp=1.10, dy_12m=0.0, liquidez=1_000_000)
        snap_at_one = make_snapshot(pvp=1.0, dy_12m=0.0, liquidez=1_000_000)
        # Ambos não pontuam por pvp — score deve ser igual (zero nesse caso)
        assert engine.score(snap_above) == engine.score(snap_at_one)

    def test_pvp_formula(self):
        engine = WeightedScoreEngine()
        # pvp=0.75: (1.0 - 0.75) * 40 = 10 pts de pvp
        snap = make_snapshot(pvp=0.75, dy_12m=0.0, liquidez=1_000_000)
        assert engine.score(snap) == 10


class TestDYComponent:
    def test_higher_dy_gives_higher_score(self):
        engine = WeightedScoreEngine()
        snap_high = make_snapshot(dy_12m=14.0, pvp=0.0, liquidez=1_000_000)
        snap_low = make_snapshot(dy_12m=7.0, pvp=0.0, liquidez=1_000_000)
        assert engine.score(snap_high) > engine.score(snap_low)

    def test_dy_capped_at_15_percent(self):
        engine = WeightedScoreEngine()
        # DY 15% e 20% devem dar o mesmo score (cap em 15%)
        snap_15 = make_snapshot(dy_12m=15.0, pvp=0.0, liquidez=1_000_000)
        snap_20 = make_snapshot(dy_12m=20.0, pvp=0.0, liquidez=1_000_000)
        assert engine.score(snap_15) == engine.score(snap_20)


class TestDeltaDYComponent:
    def test_rising_dy_adds_points(self):
        engine = WeightedScoreEngine()
        snap_rising = make_snapshot(delta_dy=0.5, pvp=0.0, dy_12m=0.0, liquidez=1_000_000)
        snap_flat = make_snapshot(delta_dy=0.0, pvp=0.0, dy_12m=0.0, liquidez=1_000_000)
        assert engine.score(snap_rising) > engine.score(snap_flat)

    def test_falling_dy_subtracts_points(self):
        engine = WeightedScoreEngine()
        snap_falling = make_snapshot(delta_dy=-2.0, dy_12m=10.0, pvp=0.0, liquidez=1_000_000)
        snap_flat = make_snapshot(delta_dy=0.0, dy_12m=10.0, pvp=0.0, liquidez=1_000_000)
        assert engine.score(snap_falling) < engine.score(snap_flat)

    def test_small_negative_delta_does_not_penalize(self):
        engine = WeightedScoreEngine()
        # delta entre -1.0 e 0 não penaliza nem bonifica
        snap_small = make_snapshot(delta_dy=-0.5, dy_12m=10.0, pvp=0.0, liquidez=1_000_000)
        snap_flat = make_snapshot(delta_dy=0.0, dy_12m=10.0, pvp=0.0, liquidez=1_000_000)
        assert engine.score(snap_small) == engine.score(snap_flat)


class TestLiquidezPenalty:
    def test_low_liquidez_subtracts_points(self):
        engine = WeightedScoreEngine()
        snap_low = make_snapshot(dy_12m=10.0, pvp=0.0, liquidez=100_000)
        snap_ok = make_snapshot(dy_12m=10.0, pvp=0.0, liquidez=1_000_000)
        assert engine.score(snap_low) < engine.score(snap_ok)

    def test_liquidez_exactly_at_threshold_does_not_penalize(self):
        engine = WeightedScoreEngine()
        snap = make_snapshot(dy_12m=0.0, pvp=0.0, liquidez=500_000)
        # Exatamente no threshold não deve penalizar
        assert engine.score(snap) == 0


class TestVacanciaPenalty:
    def test_high_vacancia_subtracts_points(self):
        engine = WeightedScoreEngine()
        snap_high = make_snapshot(dy_12m=10.0, pvp=0.0, liquidez=1_000_000, vacancia=25.0)
        snap_ok = make_snapshot(dy_12m=10.0, pvp=0.0, liquidez=1_000_000, vacancia=10.0)
        assert engine.score(snap_high) < engine.score(snap_ok)

    def test_vacancia_none_does_not_penalize(self):
        engine = WeightedScoreEngine()
        snap_none = make_snapshot(dy_12m=10.0, pvp=0.0, liquidez=1_000_000, vacancia=None)
        snap_zero = make_snapshot(dy_12m=10.0, pvp=0.0, liquidez=1_000_000, vacancia=0.0)
        # None não penaliza; vacancia=0 também não (abaixo de 15%)
        assert engine.score(snap_none) == engine.score(snap_zero)


class TestCustomWeights:
    def test_accepts_custom_weights(self):
        # Pesos zerados devem dar score 0 para qualquer snapshot
        zero_weights = {k: 0.0 for k in FII_WEIGHTS}
        engine = WeightedScoreEngine(weights=zero_weights)
        snap = make_snapshot(dy_12m=15.0, pvp=0.5, liquidez=5_000_000)
        assert engine.score(snap) == 0

    def test_custom_weights_override_defaults(self):
        # Pesos com só DY contando — pvp não deve influenciar
        dy_only = {**{k: 0.0 for k in FII_WEIGHTS}, "dy": 30.0}
        engine = WeightedScoreEngine(weights=dy_only)
        snap_pvp = make_snapshot(dy_12m=10.0, pvp=0.5, liquidez=1_000_000)
        snap_no_pvp = make_snapshot(dy_12m=10.0, pvp=0.0, liquidez=1_000_000)
        assert engine.score(snap_pvp) == engine.score(snap_no_pvp)
