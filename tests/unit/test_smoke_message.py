"""
Teste de ponta a ponta com dados mockados — sem banco, sem API.
Simula o pipeline completo para CPTS11 com dados do plano free da brapi:
preço, volume e variação diária. P/VP e DY não estão disponíveis no plano free.
"""

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.adapters.delivery.telegram_adapter import TelegramAdapter, TelegramDeliveryError
from app.adapters.narrators.template_narrator import TemplateNarrator
from app.adapters.rules.fii_rule_set import FIIRuleSet
from app.adapters.scoring.weighted_score_engine import WeightedScoreEngine
from app.core.config import Settings
from app.domain.models_asset import AssetSnapshot, DigestContext
from app.pipeline.asset_pipeline import AssetPipeline


def make_settings(**kwargs) -> Settings:
    defaults = dict(
        FII_MIN_DY=8.0,
        FII_MAX_PVP=1.15,
        FII_PVP_DISCOUNT=0.80,
        FII_MAX_VACANCIA=15.0,
        FII_MAX_LTV=70.0,
        FII_MIN_LIQUIDEZ=500_000,
        FII_MAX_PRICE_DROP=5.0,
        FII_MIN_DELTA_DY=-1.0,
        TELEGRAM_BOT_TOKEN="test-token",
        TELEGRAM_CHAT_ID="123456789",
    )
    defaults.update(kwargs)
    return Settings(**defaults)


def make_cpts11_snapshot() -> AssetSnapshot:
    """
    CPTS11 com dados do plano free da brapi: preço, liquidez e variação do dia.
    P/VP e DY ficam em 0.0 — as regras ignoram campos zerados.
    """
    return AssetSnapshot(
        ticker="CPTS11",
        market="BR",
        date=date(2026, 6, 27),
        price=7.43,
        dy_12m=0.0,       # não disponível no plano free
        pvp=0.0,          # não disponível no plano free
        liquidez=6_945_822,  # 932143 cotas × R$7.43
        delta_price=-0.4,
    )


def make_cpts11_snapshot_price_drop() -> AssetSnapshot:
    """CPTS11 com queda de 6% no dia — dispara price_drop (critical)."""
    return AssetSnapshot(
        ticker="CPTS11",
        market="BR",
        date=date(2026, 6, 27),
        price=7.43,
        dy_12m=0.0,
        pvp=0.0,
        liquidez=6_945_822,
        delta_price=-6.0,
    )


class TestSmokePipelineCPTS11:
    async def test_no_alerts_for_healthy_cpts11(self):
        """Fundo com dados normais do plano free não dispara nenhum alerta."""
        from app.domain.models_asset import AlertSeverity
        settings = make_settings()
        rules = FIIRuleSet(settings=settings)
        snap = make_cpts11_snapshot()

        alerts = rules.evaluate(snap)

        assert alerts == [], (
            f"CPTS11 saudável não deveria ter alertas, mas tem: {alerts}"
        )

    async def test_price_drop_alert_fires(self):
        """Queda de 6% dispara price_drop (critical)."""
        settings = make_settings()
        rules = FIIRuleSet(settings=settings)
        snap = make_cpts11_snapshot_price_drop()

        alerts = rules.evaluate(snap)

        assert any(a.rule == "price_drop" for a in alerts), (
            "CPTS11 com queda de 6% deveria disparar price_drop"
        )

    async def test_low_liquidez_alert_fires(self):
        """Volume baixo dispara low_liquidez (warning)."""
        settings = make_settings()
        rules = FIIRuleSet(settings=settings)
        snap = AssetSnapshot(
            ticker="CPTS11",
            market="BR",
            date=date(2026, 6, 27),
            price=7.43,
            dy_12m=0.0,
            pvp=0.0,
            liquidez=100_000,  # abaixo de FII_MIN_LIQUIDEZ=500k
        )

        alerts = rules.evaluate(snap)

        assert any(a.rule == "low_liquidez" for a in alerts)

    async def test_template_narrator_mentions_cpts11(self):
        settings = make_settings()
        rules = FIIRuleSet(settings=settings)
        snap = make_cpts11_snapshot_price_drop()
        alerts = rules.evaluate(snap)

        context = DigestContext(
            date=date(2026, 6, 27),
            snapshots=[snap],
            alerts=alerts,
            scores={"CPTS11": WeightedScoreEngine().score(snap)},
        )

        message = await TemplateNarrator().narrate(context)

        assert "CPTS11" in message

    async def test_template_narrator_message_format(self):
        settings = make_settings()
        snap = make_cpts11_snapshot()

        context = DigestContext(
            date=date(2026, 6, 27),
            snapshots=[snap],
            alerts=[],
            scores={"CPTS11": WeightedScoreEngine().score(snap)},
        )

        message = await TemplateNarrator().narrate(context)

        assert "27/06/2026" in message
        assert "1 fundos" in message
        assert "0 alertas" in message

    async def test_full_pipeline_with_mock_telegram(self):
        """Pipeline completo: brapi mockada → regras → score → template → telegram mockado."""
        snap = make_cpts11_snapshot()

        mock_data = MagicMock()
        mock_data.fetch = AsyncMock(return_value=snap)

        settings = make_settings()
        sent_messages: list[str] = []

        mock_delivery = MagicMock()

        async def capture_send(msg: str) -> None:
            sent_messages.append(msg)

        mock_delivery.send = capture_send

        pipeline = AssetPipeline(
            data=mock_data,
            rules=FIIRuleSet(settings=settings),
            scorer=WeightedScoreEngine(),
            narrator=TemplateNarrator(),
            delivery=mock_delivery,
        )

        await pipeline.run(tickers=["CPTS11"], chat_id=123456789, run_date=date(2026, 6, 27))

        assert len(sent_messages) == 1
        message = sent_messages[0]
        assert "27/06/2026" in message
        assert "1 fundos" in message
        print("\n--- Mensagem que seria enviada ao Telegram ---")
        print(message)
        print("---")

    async def test_score_with_free_plan_data(self):
        """Com pvp=0.0 e dy_12m=0.0, score deve ser 0 (sem dados fundamentalistas)."""
        snap = make_cpts11_snapshot()
        score = WeightedScoreEngine().score(snap)
        assert score == 0, f"Score sem fundamentalistas deveria ser 0, foi {score}"

    async def test_telegram_adapter_raises_on_api_error(self):
        """Garante que TelegramDeliveryError é propagado quando a API rejeita."""
        from unittest.mock import patch

        adapter = TelegramAdapter(settings=make_settings())

        with patch("app.adapters.delivery.telegram_adapter.httpx.AsyncClient") as mock_cls:
            client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            response = MagicMock()
            response.status_code = 400
            response.text = "Bad Request: chat not found"
            client.post = AsyncMock(return_value=response)

            with pytest.raises(TelegramDeliveryError, match="400"):
                await adapter.send("Mensagem de teste para CPTS11")