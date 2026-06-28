from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.models_asset import AssetSnapshot
from app.repositories.fii_repository import FIIRepository


def make_snapshot(ticker: str = "KNCR11", snap_date: date = date(2026, 6, 26)) -> AssetSnapshot:
    return AssetSnapshot(
        ticker=ticker, market="BR", date=snap_date,
        price=97.50, dy_12m=10.5, pvp=0.92, liquidez=1_000_000,
    )


def make_repo(session=None):
    return FIIRepository(session or AsyncMock())


class TestSaveSnapshot:
    async def test_saves_new_snapshot(self):
        session = MagicMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
        session.commit = AsyncMock()

        repo = make_repo(session)
        await repo.save_snapshot(make_snapshot())

        session.add.assert_called_once()
        session.commit.assert_called_once()

    async def test_skips_duplicate_snapshot(self):
        session = MagicMock()
        # Simula SELECT encontrando registro já existente
        existing = MagicMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=existing)))
        session.commit = AsyncMock()

        repo = make_repo(session)
        await repo.save_snapshot(make_snapshot())

        session.add.assert_not_called()
        session.commit.assert_not_called()

    async def test_saves_optional_fields(self):
        session = MagicMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
        session.commit = AsyncMock()

        snap = make_snapshot()
        snap.vacancia = 12.5
        snap.ltv = 65.0
        snap.provento_anunciado = 0.095

        repo = make_repo(session)
        await repo.save_snapshot(snap)

        orm_obj = session.add.call_args.args[0]
        assert orm_obj.vacancia == 12.5
        assert orm_obj.ltv == 65.0
        assert orm_obj.provento_anunciado == pytest.approx(0.095)


class TestGetPreviousSnapshot:
    async def test_returns_orm_when_found(self):
        previous_orm = MagicMock()
        session = AsyncMock()
        session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=previous_orm))
        )

        repo = make_repo(session)
        result = await repo.get_previous_snapshot("KNCR11", before=date(2026, 6, 26))
        assert result is previous_orm

    async def test_returns_none_when_not_found(self):
        session = AsyncMock()
        session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

        repo = make_repo(session)
        result = await repo.get_previous_snapshot("KNCR11", before=date(2026, 6, 26))
        assert result is None


class TestCountSnapshotsSince:
    async def test_returns_count_from_database(self):
        session = AsyncMock()
        session.execute = AsyncMock(
            return_value=MagicMock(scalar_one=MagicMock(return_value=3))
        )

        repo = make_repo(session)
        count = await repo.count_snapshots_since("KNCR11", since=date(2026, 6, 1))
        assert count == 3

    async def test_returns_zero_when_no_records(self):
        session = AsyncMock()
        session.execute = AsyncMock(
            return_value=MagicMock(scalar_one=MagicMock(return_value=None))
        )

        repo = make_repo(session)
        count = await repo.count_snapshots_since("KNCR11", since=date(2026, 6, 1))
        assert count == 0


class TestSumProventos:
    async def test_returns_sum_when_proventos_exist(self):
        session = AsyncMock()
        session.execute = AsyncMock(
            return_value=MagicMock(scalar_one=MagicMock(return_value=0.285))
        )

        repo = make_repo(session)
        total = await repo.sum_proventos("MXRF11", since=date(2026, 1, 1))
        assert total == pytest.approx(0.285)

    async def test_returns_zero_when_no_proventos(self):
        session = AsyncMock()
        session.execute = AsyncMock(
            return_value=MagicMock(scalar_one=MagicMock(return_value=None))
        )

        repo = make_repo(session)
        total = await repo.sum_proventos("MXRF11", since=date(2026, 1, 1))
        assert total == 0.0
