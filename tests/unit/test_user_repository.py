"""
Testes unitários do UserRepository — foco nos métodos novos (item 3, 5, 6a):
set_digest_weekday, get_onboarding_events, update_profile_summary,
save_onboarding com portfolio_shares/onboarding_events.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.repositories.user_repository import UserRepository


def make_repo(session=None) -> UserRepository:
    return UserRepository(session or AsyncMock())


def make_user_result(user) -> MagicMock:
    result = MagicMock()
    result.scalar_one = MagicMock(return_value=user)
    return result


class TestSetDigestWeekday:
    async def test_valid_weekday_persists(self):
        user = MagicMock(digest_weekday=0)
        session = MagicMock()
        session.execute = AsyncMock(return_value=make_user_result(user))
        session.commit = AsyncMock()

        repo = make_repo(session)
        result = await repo.set_digest_weekday("user-1", 2)

        assert result.digest_weekday == 2
        session.commit.assert_called_once()

    async def test_boundary_values_are_valid(self):
        for weekday in (0, 6):
            user = MagicMock()
            session = MagicMock()
            session.execute = AsyncMock(return_value=make_user_result(user))
            session.commit = AsyncMock()
            repo = make_repo(session)
            result = await repo.set_digest_weekday("user-1", weekday)
            assert result.digest_weekday == weekday

    async def test_negative_raises_value_error(self):
        repo = make_repo()
        with pytest.raises(ValueError):
            await repo.set_digest_weekday("user-1", -1)

    async def test_above_six_raises_value_error(self):
        repo = make_repo()
        with pytest.raises(ValueError):
            await repo.set_digest_weekday("user-1", 7)


class TestUpdateProfileSummary:
    async def test_persists_summary_dict(self):
        user = MagicMock()
        session = MagicMock()
        session.execute = AsyncMock(return_value=make_user_result(user))
        session.commit = AsyncMock()

        repo = make_repo(session)
        summary = {"resumo": "usuário motivado"}
        result = await repo.update_profile_summary("user-1", summary)

        assert result.user_profile_summary == summary
        session.commit.assert_called_once()

    async def test_can_reset_to_none(self):
        user = MagicMock()
        session = MagicMock()
        session.execute = AsyncMock(return_value=make_user_result(user))
        session.commit = AsyncMock()

        repo = make_repo(session)
        result = await repo.update_profile_summary("user-1", None)

        assert result.user_profile_summary is None


class TestGetOnboardingEvents:
    async def test_returns_events_ordered(self):
        events = [MagicMock(step="debt"), MagicMock(step="budget")]
        session = MagicMock()
        result_mock = MagicMock()
        result_mock.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=events)))
        session.execute = AsyncMock(return_value=result_mock)

        repo = make_repo(session)
        result = await repo.get_onboarding_events("user-1")

        assert result == events


class TestSaveOnboardingWithSharesAndEvents:
    async def test_creates_portfolio_with_real_shares(self):
        session = MagicMock()
        session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        session.flush = AsyncMock()
        session.commit = AsyncMock()

        repo = make_repo(session)
        await repo.save_onboarding(
            chat_id=123,
            stage=3,
            monthly_budget=Decimal("500"),
            risk_profile="conservador",
            debt_amount=None,
            savings_amount=Decimal("0"),
            goal_name="Netflix",
            goal_value_monthly=Decimal("50"),
            portfolio_shares={"MXRF11": 10, "KNCR11": 5},
        )

        added_portfolios = [
            call.args[0]
            for call in session.add.call_args_list
            if hasattr(call.args[0], "ticker")
        ]
        shares_by_ticker = {p.ticker: p.shares for p in added_portfolios}
        assert shares_by_ticker == {"MXRF11": 10, "KNCR11": 5}

    async def test_records_onboarding_events_in_same_transaction(self):
        session = MagicMock()
        session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        session.flush = AsyncMock()
        session.commit = AsyncMock()

        repo = make_repo(session)
        events = [
            {"step": "debt", "response_type": "answered", "raw_value": "não"},
            {"step": "essential_expense", "response_type": "skipped", "raw_value": None},
        ]
        await repo.save_onboarding(
            chat_id=123,
            stage=2,
            monthly_budget=Decimal("500"),
            risk_profile="conservador",
            debt_amount=None,
            savings_amount=Decimal("0"),
            goal_name="Netflix",
            goal_value_monthly=Decimal("50"),
            portfolio_shares={},
            onboarding_events=events,
        )

        added_events = [
            call.args[0]
            for call in session.add.call_args_list
            if hasattr(call.args[0], "step")
        ]
        assert len(added_events) == 2
        assert {e.step for e in added_events} == {"debt", "essential_expense"}
        assert {e.response_type for e in added_events} == {"answered", "skipped"}

    async def test_no_events_when_not_provided(self):
        session = MagicMock()
        session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        session.flush = AsyncMock()
        session.commit = AsyncMock()

        repo = make_repo(session)
        await repo.save_onboarding(
            chat_id=123,
            stage=2,
            monthly_budget=Decimal("500"),
            risk_profile="conservador",
            debt_amount=None,
            savings_amount=Decimal("0"),
            goal_name="Netflix",
            goal_value_monthly=Decimal("50"),
            portfolio_shares={},
        )

        added_events = [
            call.args[0]
            for call in session.add.call_args_list
            if hasattr(call.args[0], "step")
        ]
        assert added_events == []
