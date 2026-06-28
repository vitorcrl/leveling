from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.models_asset import Alert, AlertSeverity, AssetSnapshot, DigestContext
from app.pipeline.asset_pipeline import AssetPipeline

_CHAT_ID = 123456789


def make_snapshot(ticker: str = "TEST11") -> AssetSnapshot:
    return AssetSnapshot(
        ticker=ticker, market="BR", date=date(2026, 6, 26),
        price=100.0, dy_12m=10.0, pvp=0.95, liquidez=1_000_000,
    )


def make_pipeline(
    fetch_result=None,
    alerts=None,
    score=70,
    narrate_result="Análise do dia.",
    send_raises=None,
):
    data = MagicMock()
    data.fetch = AsyncMock(return_value=fetch_result or make_snapshot())

    rules = MagicMock()
    rules.evaluate = MagicMock(return_value=alerts or [])

    scorer = MagicMock()
    scorer.score = MagicMock(return_value=score)

    narrator = MagicMock()
    narrator.narrate = AsyncMock(return_value=narrate_result)

    delivery = MagicMock()
    if send_raises:
        delivery.send = AsyncMock(side_effect=send_raises)
    else:
        delivery.send = AsyncMock(return_value=None)

    return AssetPipeline(
        data=data, rules=rules, scorer=scorer, narrator=narrator, delivery=delivery,
    ), data, rules, scorer, narrator, delivery


class TestAssetPipelineRun:
    async def test_fetches_each_ticker(self):
        pipeline, data, *_ = make_pipeline()
        await pipeline.run(tickers=["KNCR11", "MXRF11"], chat_id=_CHAT_ID)
        assert data.fetch.call_count == 2

    async def test_evaluates_rules_for_each_snapshot(self):
        pipeline, _, rules, *_ = make_pipeline()
        await pipeline.run(tickers=["KNCR11", "MXRF11"], chat_id=_CHAT_ID)
        assert rules.evaluate.call_count == 2

    async def test_scores_each_snapshot(self):
        pipeline, _, _, scorer, *_ = make_pipeline()
        await pipeline.run(tickers=["KNCR11", "MXRF11"], chat_id=_CHAT_ID)
        assert scorer.score.call_count == 2

    async def test_narrates_once(self):
        pipeline, *_, narrator, _ = make_pipeline()
        await pipeline.run(tickers=["KNCR11"], chat_id=_CHAT_ID)
        narrator.narrate.assert_called_once()

    async def test_delivers_once_with_chat_id(self):
        pipeline, *_, delivery = make_pipeline()
        await pipeline.run(tickers=["KNCR11"], chat_id=_CHAT_ID)
        delivery.send.assert_called_once_with("Análise do dia.", _CHAT_ID)

    async def test_context_contains_all_snapshots(self):
        snap_a = make_snapshot("AAAA11")
        snap_b = make_snapshot("BBBB11")

        data = MagicMock()
        data.fetch = AsyncMock(side_effect=[snap_a, snap_b])
        rules = MagicMock()
        rules.evaluate = MagicMock(return_value=[])
        scorer = MagicMock()
        scorer.score = MagicMock(return_value=50)
        narrator = MagicMock()
        captured_context: list[DigestContext] = []

        async def capture(ctx):
            captured_context.append(ctx)
            return "ok"

        narrator.narrate = capture
        delivery = MagicMock()
        delivery.send = AsyncMock()

        pipeline = AssetPipeline(
            data=data, rules=rules, scorer=scorer, narrator=narrator, delivery=delivery
        )
        await pipeline.run(tickers=["AAAA11", "BBBB11"], chat_id=_CHAT_ID)

        ctx = captured_context[0]
        tickers_in_ctx = {s.ticker for s in ctx.snapshots}
        assert "AAAA11" in tickers_in_ctx
        assert "BBBB11" in tickers_in_ctx

    async def test_failed_fetch_does_not_stop_other_tickers(self):
        data = MagicMock()
        data.fetch = AsyncMock(side_effect=[RuntimeError("timeout"), make_snapshot("MXRF11")])
        rules = MagicMock()
        rules.evaluate = MagicMock(return_value=[])
        scorer = MagicMock()
        scorer.score = MagicMock(return_value=50)
        narrator = MagicMock()
        narrator.narrate = AsyncMock(return_value="ok")
        delivery = MagicMock()
        delivery.send = AsyncMock()

        pipeline = AssetPipeline(
            data=data, rules=rules, scorer=scorer, narrator=narrator, delivery=delivery
        )
        await pipeline.run(tickers=["KNCR11", "MXRF11"], chat_id=_CHAT_ID)

        call_args = narrator.narrate.call_args.args[0]
        assert len(call_args.snapshots) == 1
        assert call_args.snapshots[0].ticker == "MXRF11"

    async def test_failed_rules_do_not_stop_pipeline(self):
        rules = MagicMock()
        rules.evaluate = MagicMock(side_effect=RuntimeError("regra quebrada"))
        data = MagicMock()
        data.fetch = AsyncMock(return_value=make_snapshot())
        scorer = MagicMock()
        scorer.score = MagicMock(return_value=50)
        narrator = MagicMock()
        narrator.narrate = AsyncMock(return_value="ok")
        delivery = MagicMock()
        delivery.send = AsyncMock()

        pipeline = AssetPipeline(
            data=data, rules=rules, scorer=scorer, narrator=narrator, delivery=delivery
        )
        await pipeline.run(tickers=["KNCR11"], chat_id=_CHAT_ID)

        narrator.narrate.assert_called_once()

    async def test_enrich_snapshot_callback_is_called(self):
        enriched = make_snapshot()
        enriched.delta_dy = -1.5

        enrich = AsyncMock(return_value=enriched)

        pipeline, _, _, _, narrator, _ = make_pipeline()
        await pipeline.run(tickers=["KNCR11"], chat_id=_CHAT_ID, enrich_snapshot=enrich)

        enrich.assert_called_once()

    async def test_enrich_failure_uses_original_snapshot(self):
        enrich = AsyncMock(side_effect=RuntimeError("db offline"))
        pipeline, _, _, _, narrator, _ = make_pipeline()
        await pipeline.run(tickers=["KNCR11"], chat_id=_CHAT_ID, enrich_snapshot=enrich)
        narrator.narrate.assert_called_once()

    async def test_scores_stored_in_context(self):
        captured: list[DigestContext] = []

        data = MagicMock()
        data.fetch = AsyncMock(return_value=make_snapshot("KNCR11"))
        rules = MagicMock()
        rules.evaluate = MagicMock(return_value=[])
        scorer = MagicMock()
        scorer.score = MagicMock(return_value=85)

        async def capture(ctx):
            captured.append(ctx)
            return "ok"

        narrator = MagicMock()
        narrator.narrate = capture
        delivery = MagicMock()
        delivery.send = AsyncMock()

        pipeline = AssetPipeline(
            data=data, rules=rules, scorer=scorer, narrator=narrator, delivery=delivery
        )
        await pipeline.run(tickers=["KNCR11"], chat_id=_CHAT_ID)

        assert captured[0].scores["KNCR11"] == 85

    async def test_run_with_empty_tickers_still_delivers(self):
        pipeline, _, _, _, narrator, delivery = make_pipeline()
        await pipeline.run(tickers=[], chat_id=_CHAT_ID)
        delivery.send.assert_called_once()
