"""Tests for subscription reconciliation."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestReconcileSubscriptions:
    @pytest.mark.asyncio
    async def test_skips_when_billing_disabled(self):
        """In self-hosted mode, reconciliation returns 0 immediately."""
        with patch("wikimind.services.billing.get_settings") as mock_settings:
            mock_settings.return_value.billing_enabled = False
            from wikimind.services.billing import reconcile_subscriptions

            result = await reconcile_subscriptions(AsyncMock())
            assert result == 0

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_subscriptions(self):
        """Returns 0 when no active subscriptions exist."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_session.exec.return_value = mock_result

        with patch("wikimind.services.billing.get_settings") as mock_settings:
            mock_settings.return_value.billing_enabled = True
            mock_settings.return_value.billing.lemon_squeezy_api_key = "test-key"
            from wikimind.services.billing import reconcile_subscriptions

            result = await reconcile_subscriptions(mock_session)
            assert result == 0

    @pytest.mark.asyncio
    async def test_reconciles_active_subscription_with_no_drift(self):
        """When local status matches LS status, no update is written but count is incremented."""
        from wikimind.services.billing import reconcile_subscriptions

        mock_sub = MagicMock()
        mock_sub.id = "sub-1"
        mock_sub.lemon_squeezy_subscription_id = "ls-123"
        mock_sub.user_id = "user-1"
        mock_sub.status = "active"

        mock_user = MagicMock()
        mock_user.id = "user-1"
        mock_user.plan_id = "plan-1"

        mock_plan = MagicMock()
        mock_plan.id = "plan-pro"
        mock_plan.name = "pro"

        mock_default_plan = MagicMock()
        mock_default_plan.id = "plan-free"
        mock_default_plan.name = "free"

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()

        sub_result = MagicMock()
        sub_result.all.return_value = [mock_sub]

        user_result = MagicMock()
        user_result.one_or_none.return_value = mock_user

        plan_result = MagicMock()
        plan_result.one_or_none.return_value = mock_plan

        apply_plan_result = MagicMock()
        apply_plan_result.one_or_none.return_value = mock_plan

        default_plan_result = MagicMock()
        default_plan_result.one.return_value = mock_default_plan

        mock_session.exec.side_effect = [
            sub_result,  # initial subscription query
            user_result,  # user lookup
            plan_result,  # plan lookup by variant_id
            apply_plan_result,  # plan lookup in apply_entitlement
            default_plan_result,  # default plan lookup in apply_entitlement
        ]

        ls_api_response = {
            "data": {
                "attributes": {
                    "status": "active",
                    "variant_id": "variant-pro",
                    "ends_at": None,
                }
            }
        }

        mock_http_response = MagicMock()
        mock_http_response.json.return_value = ls_api_response
        mock_http_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_http_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("wikimind.services.billing.get_settings") as mock_settings,
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            mock_settings.return_value.billing_enabled = True
            mock_settings.return_value.billing.lemon_squeezy_api_key = "test-key"

            result = await reconcile_subscriptions(mock_session)

        assert result == 1
        # Status was not changed since it matched
        assert mock_sub.status == "active"

    @pytest.mark.asyncio
    async def test_updates_status_on_drift(self):
        """When local status differs from LS status, subscription is updated."""
        from wikimind.services.billing import reconcile_subscriptions

        mock_sub = MagicMock()
        mock_sub.id = "sub-2"
        mock_sub.lemon_squeezy_subscription_id = "ls-456"
        mock_sub.user_id = "user-2"
        mock_sub.status = "active"  # local says active

        mock_user = MagicMock()
        mock_user.id = "user-2"
        mock_user.plan_id = "plan-pro"

        mock_plan = MagicMock()
        mock_plan.id = "plan-pro"
        mock_plan.name = "pro"

        mock_default_plan = MagicMock()
        mock_default_plan.id = "plan-free"
        mock_default_plan.name = "free"

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()

        sub_result = MagicMock()
        sub_result.all.return_value = [mock_sub]

        user_result = MagicMock()
        user_result.one_or_none.return_value = mock_user

        plan_result = MagicMock()
        plan_result.one_or_none.return_value = mock_plan

        apply_plan_result = MagicMock()
        apply_plan_result.one_or_none.return_value = mock_plan

        default_plan_result = MagicMock()
        default_plan_result.one.return_value = mock_default_plan

        mock_session.exec.side_effect = [
            sub_result,
            user_result,
            plan_result,
            apply_plan_result,
            default_plan_result,
        ]

        ls_api_response = {
            "data": {
                "attributes": {
                    "status": "cancelled",  # LS says cancelled
                    "variant_id": "variant-pro",
                    "ends_at": "2026-06-01T00:00:00+00:00",
                }
            }
        }

        mock_http_response = MagicMock()
        mock_http_response.json.return_value = ls_api_response
        mock_http_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_http_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("wikimind.services.billing.get_settings") as mock_settings,
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            mock_settings.return_value.billing_enabled = True
            mock_settings.return_value.billing.lemon_squeezy_api_key = "test-key"

            result = await reconcile_subscriptions(mock_session)

        # Should have updated local status to cancelled
        assert mock_sub.status == "cancelled"
        assert result == 1

    @pytest.mark.asyncio
    async def test_continues_on_http_error(self):
        """A failing HTTP call for one subscription does not abort the loop."""
        import httpx

        from wikimind.services.billing import reconcile_subscriptions

        mock_sub = MagicMock()
        mock_sub.id = "sub-err"
        mock_sub.lemon_squeezy_subscription_id = "ls-bad"
        mock_sub.user_id = "user-3"
        mock_sub.status = "active"

        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()

        sub_result = MagicMock()
        sub_result.all.return_value = [mock_sub]
        mock_session.exec.return_value = sub_result

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.HTTPError("connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("wikimind.services.billing.get_settings") as mock_settings,
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            mock_settings.return_value.billing_enabled = True
            mock_settings.return_value.billing.lemon_squeezy_api_key = "test-key"

            # Should not raise; errors are caught and logged
            result = await reconcile_subscriptions(mock_session)

        assert result == 0
        mock_session.commit.assert_awaited_once()


class TestApplyEntitlement:
    @pytest.mark.asyncio
    async def test_active_status_assigns_plan(self):
        """Active subscription assigns the named plan with no expiry."""
        from wikimind.services.billing import apply_entitlement

        mock_user = MagicMock()
        mock_plan = MagicMock()
        mock_plan.id = "plan-pro"

        mock_default_plan = MagicMock()
        mock_default_plan.id = "plan-free"

        mock_session = AsyncMock()

        plan_result = MagicMock()
        plan_result.one_or_none.return_value = mock_plan

        default_result = MagicMock()
        default_result.one.return_value = mock_default_plan

        mock_session.exec.side_effect = [plan_result, default_result]

        await apply_entitlement(mock_session, mock_user, "active", "pro")

        assert mock_user.plan_id == "plan-pro"
        assert mock_user.plan_effective_until is None

    @pytest.mark.asyncio
    async def test_expired_status_downgrades_to_default(self):
        """Expired subscription reverts user to the default free plan."""
        from wikimind.services.billing import apply_entitlement

        mock_user = MagicMock()
        mock_plan = MagicMock()
        mock_plan.id = "plan-pro"

        mock_default_plan = MagicMock()
        mock_default_plan.id = "plan-free"

        mock_session = AsyncMock()

        plan_result = MagicMock()
        plan_result.one_or_none.return_value = mock_plan

        default_result = MagicMock()
        default_result.one.return_value = mock_default_plan

        mock_session.exec.side_effect = [plan_result, default_result]

        await apply_entitlement(mock_session, mock_user, "expired", "pro")

        assert mock_user.plan_id == "plan-free"
        assert mock_user.plan_effective_until is None

    @pytest.mark.asyncio
    async def test_unknown_plan_name_logs_warning_and_returns(self):
        """Unknown plan name in entitlement logs a warning and does not mutate user."""
        from wikimind.services.billing import apply_entitlement

        mock_user = MagicMock()
        mock_session = AsyncMock()

        plan_result = MagicMock()
        plan_result.one_or_none.return_value = None  # plan not found

        mock_session.exec.return_value = plan_result

        original_plan_id = mock_user.plan_id

        await apply_entitlement(mock_session, mock_user, "active", "nonexistent-plan")

        # User plan_id should not have been mutated
        assert mock_user.plan_id == original_plan_id
