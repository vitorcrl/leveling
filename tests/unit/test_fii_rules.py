from datetime import date

import pytest

from app.adapters.rules.fii_rule_set import FIIRuleSet
from app.core.config import Settings
from app.domain.models_asset import AlertSeverity, AssetSnapshot


# Settings com thresholds fixos para que os testes não dependam do .env
@pytest.fixture
def settings() -> Settings:
    return Settings(
        DATABASE_URL="postgresql+asyncpg://x:x@localhost/x",
        FII_MIN_DY=8.0,
        FII_MAX_PVP=1.15,
        FII_PVP_DISCOUNT=0.80,
        FII_MAX_VACANCIA=15.0,
        FII_MAX_LTV=70.0,
        FII_MIN_LIQUIDEZ=500_000,
        FII_MAX_PRICE_DROP=5.0,
        FII_MIN_DELTA_DY=-1.0,
    )


@pytest.fixture
def rules(settings: Settings) -> FIIRuleSet:
    return FIIRuleSet(settings=settings)


def make_snapshot(**kwargs) -> AssetSnapshot:
    """Cria snapshot com defaults saudáveis — só sobrescreve o que o teste precisa."""
    defaults = dict(
        ticker="TEST11",
        market="BR",
        date=date(2026, 6, 26),
        price=100.0,
        dy_12m=10.0,
        pvp=1.0,
        liquidez=1_000_000,
    )
    defaults.update(kwargs)
    return AssetSnapshot(**defaults)


class TestRuleLowDY:
    def test_fires_when_dy_below_minimum(self, rules):
        snap = make_snapshot(dy_12m=7.0)
        alerts = rules.evaluate(snap)
        assert any(a.rule == "low_dy" for a in alerts)

    def test_does_not_fire_when_dy_at_minimum(self, rules):
        snap = make_snapshot(dy_12m=8.0)
        alerts = rules.evaluate(snap)
        assert not any(a.rule == "low_dy" for a in alerts)

    def test_alert_is_warning_severity(self, rules):
        snap = make_snapshot(dy_12m=5.0)
        alerts = [a for a in rules.evaluate(snap) if a.rule == "low_dy"]
        assert alerts[0].severity == AlertSeverity.warning

    def test_alert_contains_current_and_threshold_values(self, rules):
        snap = make_snapshot(dy_12m=6.5)
        alerts = [a for a in rules.evaluate(snap) if a.rule == "low_dy"]
        assert alerts[0].value == 6.5
        assert alerts[0].threshold == 8.0


class TestRuleFallingDY:
    def test_fires_when_delta_below_threshold(self, rules):
        snap = make_snapshot(delta_dy=-2.0)
        alerts = rules.evaluate(snap)
        assert any(a.rule == "falling_dy" for a in alerts)

    def test_does_not_fire_when_delta_at_threshold(self, rules):
        snap = make_snapshot(delta_dy=-1.0)
        alerts = rules.evaluate(snap)
        assert not any(a.rule == "falling_dy" for a in alerts)

    def test_does_not_fire_when_dy_rising(self, rules):
        snap = make_snapshot(delta_dy=0.5)
        alerts = rules.evaluate(snap)
        assert not any(a.rule == "falling_dy" for a in alerts)


class TestRuleOvervaluedPVP:
    def test_fires_when_pvp_above_max(self, rules):
        snap = make_snapshot(pvp=1.20)
        alerts = rules.evaluate(snap)
        assert any(a.rule == "overvalued_pvp" for a in alerts)

    def test_does_not_fire_when_pvp_zero(self, rules):
        # pvp=0.0 significa dado ausente — não deve disparar nenhuma regra de P/VP
        snap = make_snapshot(pvp=0.0)
        alerts = rules.evaluate(snap)
        assert not any("pvp" in a.rule for a in alerts)

    def test_does_not_fire_when_pvp_at_max(self, rules):
        snap = make_snapshot(pvp=1.15)
        alerts = rules.evaluate(snap)
        assert not any(a.rule == "overvalued_pvp" for a in alerts)


class TestRuleDiscountPVP:
    def test_fires_when_pvp_below_discount(self, rules):
        snap = make_snapshot(pvp=0.75)
        alerts = rules.evaluate(snap)
        assert any(a.rule == "discount_pvp" for a in alerts)

    def test_is_info_severity(self, rules):
        snap = make_snapshot(pvp=0.75)
        alerts = [a for a in rules.evaluate(snap) if a.rule == "discount_pvp"]
        assert alerts[0].severity == AlertSeverity.info

    def test_does_not_fire_when_pvp_zero(self, rules):
        snap = make_snapshot(pvp=0.0)
        alerts = rules.evaluate(snap)
        assert not any(a.rule == "discount_pvp" for a in alerts)


class TestRuleHighVacancia:
    def test_fires_when_vacancia_above_max(self, rules):
        snap = make_snapshot(vacancia=20.0)
        alerts = rules.evaluate(snap)
        assert any(a.rule == "high_vacancia" for a in alerts)

    def test_does_not_fire_when_vacancia_none(self, rules):
        snap = make_snapshot(vacancia=None)
        alerts = rules.evaluate(snap)
        assert not any(a.rule == "high_vacancia" for a in alerts)

    def test_does_not_fire_when_vacancia_at_max(self, rules):
        snap = make_snapshot(vacancia=15.0)
        alerts = rules.evaluate(snap)
        assert not any(a.rule == "high_vacancia" for a in alerts)

    def test_message_includes_delta_when_rising(self, rules):
        snap = make_snapshot(vacancia=18.0, delta_vacancia=2.0)
        alerts = [a for a in rules.evaluate(snap) if a.rule == "high_vacancia"]
        assert "+2.0pp" in alerts[0].message


class TestRuleHighLTV:
    def test_fires_when_ltv_above_max(self, rules):
        snap = make_snapshot(ltv=75.0)
        alerts = rules.evaluate(snap)
        assert any(a.rule == "high_ltv" for a in alerts)

    def test_escalates_to_critical_when_ltv_very_high(self, rules):
        # FII_MAX_LTV=70, então >80 (70+10) escala para critical
        snap = make_snapshot(ltv=85.0)
        alerts = [a for a in rules.evaluate(snap) if a.rule == "high_ltv"]
        assert alerts[0].severity == AlertSeverity.critical

    def test_warning_when_ltv_moderately_above_max(self, rules):
        snap = make_snapshot(ltv=75.0)
        alerts = [a for a in rules.evaluate(snap) if a.rule == "high_ltv"]
        assert alerts[0].severity == AlertSeverity.warning

    def test_does_not_fire_when_ltv_none(self, rules):
        snap = make_snapshot(ltv=None)
        alerts = rules.evaluate(snap)
        assert not any(a.rule == "high_ltv" for a in alerts)


class TestRuleLowLiquidez:
    def test_fires_when_liquidez_below_min(self, rules):
        snap = make_snapshot(liquidez=100_000)
        alerts = rules.evaluate(snap)
        assert any(a.rule == "low_liquidez" for a in alerts)

    def test_does_not_fire_when_liquidez_at_min(self, rules):
        snap = make_snapshot(liquidez=500_000)
        alerts = rules.evaluate(snap)
        assert not any(a.rule == "low_liquidez" for a in alerts)


class TestRuleProventoAnnounced:
    def test_fires_when_provento_announced(self, rules):
        snap = make_snapshot(provento_anunciado=0.095)
        alerts = rules.evaluate(snap)
        assert any(a.rule == "provento_announced" for a in alerts)

    def test_is_info_severity(self, rules):
        snap = make_snapshot(provento_anunciado=0.095)
        alerts = [a for a in rules.evaluate(snap) if a.rule == "provento_announced"]
        assert alerts[0].severity == AlertSeverity.info

    def test_does_not_fire_when_provento_none(self, rules):
        snap = make_snapshot(provento_anunciado=None)
        alerts = rules.evaluate(snap)
        assert not any(a.rule == "provento_announced" for a in alerts)

    def test_does_not_fire_when_provento_zero(self, rules):
        snap = make_snapshot(provento_anunciado=0.0)
        alerts = rules.evaluate(snap)
        assert not any(a.rule == "provento_announced" for a in alerts)


class TestRulePriceDrop:
    def test_fires_when_drop_exceeds_max(self, rules):
        snap = make_snapshot(delta_price=-6.0)
        alerts = rules.evaluate(snap)
        assert any(a.rule == "price_drop" for a in alerts)

    def test_is_critical_severity(self, rules):
        snap = make_snapshot(delta_price=-6.0)
        alerts = [a for a in rules.evaluate(snap) if a.rule == "price_drop"]
        assert alerts[0].severity == AlertSeverity.critical

    def test_does_not_fire_when_drop_below_threshold(self, rules):
        snap = make_snapshot(delta_price=-3.0)
        alerts = rules.evaluate(snap)
        assert not any(a.rule == "price_drop" for a in alerts)

    def test_does_not_fire_on_price_rise(self, rules):
        snap = make_snapshot(delta_price=3.0)
        alerts = rules.evaluate(snap)
        assert not any(a.rule == "price_drop" for a in alerts)


class TestEvaluateAggregation:
    def test_multiple_rules_can_fire_for_same_ticker(self, rules):
        # DY baixo + liquidez baixa + queda de preço ao mesmo tempo
        snap = make_snapshot(dy_12m=5.0, liquidez=100_000, delta_price=-7.0)
        alerts = rules.evaluate(snap)
        rules_fired = {a.rule for a in alerts}
        assert "low_dy" in rules_fired
        assert "low_liquidez" in rules_fired
        assert "price_drop" in rules_fired

    def test_healthy_fund_fires_no_alerts(self, rules):
        snap = make_snapshot(
            dy_12m=11.0, pvp=0.95, liquidez=2_000_000,
            delta_price=0.5, delta_dy=0.2,
        )
        alerts = [a for a in rules.evaluate(snap)
                  if a.severity != AlertSeverity.info]
        assert alerts == []

    def test_rule_exception_does_not_stop_other_rules(self, rules):
        # Cobre linhas 58-60 — uma regra quebrando não deve derrubar as demais
        original_rule = rules._rule_low_dy

        def broken_rule(snap):
            raise RuntimeError("regra com bug")

        rules._rule_low_dy = broken_rule
        # Com DY baixo mas regra quebrada, as outras regras ainda devem rodar
        snap = make_snapshot(dy_12m=5.0, liquidez=100_000)
        alerts = rules.evaluate(snap)
        # low_liquidez ainda deve disparar mesmo com low_dy quebrada
        assert any(a.rule == "low_liquidez" for a in alerts)
        rules._rule_low_dy = original_rule
