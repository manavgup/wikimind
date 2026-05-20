"""Tests for webhook event processing."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from wikimind.services.billing import apply_entitlement


def _make_exec_result(one_or_none_val=None, one_val=None):
    """Build a MagicMock that mimics the sqlmodel exec result object."""
    result = MagicMock()
    result.one_or_none.return_value = one_or_none_val
    if one_val is not None:
        result.one.return_value = one_val
    return result


class TestApplyEntitlement:
    @pytest.mark.asyncio
    async def test_active_status_sets_plan(self):
        """Active status sets user.plan_id and clears effective_until."""
        session = AsyncMock()
        user = MagicMock()
        user.plan_id = None
        user.plan_effective_until = "some-date"

        mock_plan = MagicMock()
        mock_plan.id = "plan-pro"
        mock_plan.name = "pro"

        session.exec = AsyncMock(
            side_effect=[
                _make_exec_result(one_or_none_val=mock_plan),
                _make_exec_result(one_val=MagicMock(id="plan-free")),
            ]
        )

        await apply_entitlement(session, user, "active", "pro")
        assert user.plan_id == "plan-pro"
        assert user.plan_effective_until is None

    @pytest.mark.asyncio
    async def test_on_trial_sets_plan(self):
        """On_trial status sets plan like active."""
        session = AsyncMock()
        user = MagicMock()
        user.plan_id = None
        user.plan_effective_until = None

        mock_plan = MagicMock()
        mock_plan.id = "plan-pro"

        session.exec = AsyncMock(
            side_effect=[
                _make_exec_result(one_or_none_val=mock_plan),
                _make_exec_result(one_val=MagicMock(id="plan-free")),
            ]
        )

        await apply_entitlement(session, user, "on_trial", "pro")
        assert user.plan_id == "plan-pro"
        assert user.plan_effective_until is None

    @pytest.mark.asyncio
    async def test_cancelled_preserves_plan_until_period_end(self):
        """Cancelled status keeps Pro until period_end date."""
        session = AsyncMock()
        user = MagicMock()
        period_end = datetime(2026, 6, 1)

        mock_plan = MagicMock()
        mock_plan.id = "plan-pro"

        session.exec = AsyncMock(
            side_effect=[
                _make_exec_result(one_or_none_val=mock_plan),
                _make_exec_result(one_val=MagicMock(id="plan-free")),
            ]
        )

        await apply_entitlement(session, user, "cancelled", "pro", period_end)
        assert user.plan_id == "plan-pro"
        assert user.plan_effective_until == period_end

    @pytest.mark.asyncio
    async def test_expired_downgrades_to_free(self):
        """Expired status downgrades user to the default (free) plan immediately."""
        session = AsyncMock()
        user = MagicMock()
        default_plan = MagicMock()
        default_plan.id = "plan-free"

        mock_plan = MagicMock()
        mock_plan.id = "plan-pro"

        session.exec = AsyncMock(
            side_effect=[
                _make_exec_result(one_or_none_val=mock_plan),
                _make_exec_result(one_val=default_plan),
            ]
        )

        await apply_entitlement(session, user, "expired", "pro")
        assert user.plan_id == "plan-free"
        assert user.plan_effective_until is None

    @pytest.mark.asyncio
    async def test_unknown_plan_name_logs_warning_and_returns(self):
        """Unknown plan name logs warning and skips entitlement update."""
        session = AsyncMock()
        user = MagicMock()
        original_plan_id = "plan-existing"
        user.plan_id = original_plan_id

        session.exec = AsyncMock(return_value=_make_exec_result(one_or_none_val=None))

        await apply_entitlement(session, user, "active", "nonexistent-plan")
        # plan_id should remain unchanged since plan was not found
        assert user.plan_id == original_plan_id
