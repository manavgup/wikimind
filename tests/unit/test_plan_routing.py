"""Tests for plan-aware LLM routing."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wikimind.models import CompletionRequest


class TestPlanAwareComplete:
    @pytest.mark.asyncio
    async def test_passthrough_in_self_hosted_mode(self):
        """In self-hosted mode, passes through directly to router."""
        from wikimind.services.plan_routing import plan_aware_complete

        mock_router = AsyncMock()
        mock_response = MagicMock()
        mock_router.complete.return_value = mock_response

        request = CompletionRequest(
            system="test",
            messages=[{"role": "user", "content": "hi"}],
        )

        with patch("wikimind.services.plan_routing.get_settings") as mock_settings:
            mock_settings.return_value.billing_enabled = False
            result = await plan_aware_complete(mock_router, request, "user-1", session=None)

        assert result == mock_response
        mock_router.complete.assert_called_once_with(request, user_id="user-1")

    @pytest.mark.asyncio
    async def test_passthrough_when_no_session(self):
        """When session is None, passes through directly regardless of billing mode."""
        from wikimind.services.plan_routing import plan_aware_complete

        mock_router = AsyncMock()
        mock_response = MagicMock()
        mock_router.complete.return_value = mock_response

        request = CompletionRequest(
            system="test",
            messages=[{"role": "user", "content": "hi"}],
        )

        with patch("wikimind.services.plan_routing.get_settings") as mock_settings:
            mock_settings.return_value.billing_enabled = True
            result = await plan_aware_complete(mock_router, request, "user-1", session=None)

        assert result == mock_response
        mock_router.complete.assert_called_once_with(request, user_id="user-1")

    @pytest.mark.asyncio
    async def test_applies_plan_restrictions_in_hosted_mode(self):
        """In hosted mode with a session, applies plan provider/model restrictions."""
        from wikimind.services.plan_routing import plan_aware_complete

        mock_router = AsyncMock()
        mock_response = MagicMock()
        mock_router.complete.return_value = mock_response
        mock_router.has_user_key = AsyncMock(return_value=False)

        mock_plan = MagicMock()
        mock_plan.byok_allowed = False
        mock_plan.llm_provider = "openai"
        mock_plan.llm_model = "gpt-4o-mini"

        mock_session = MagicMock()

        request = CompletionRequest(
            system="test",
            messages=[{"role": "user", "content": "hi"}],
        )

        mock_quota_module = MagicMock(
            get_effective_plan=AsyncMock(return_value=mock_plan),
            check_daily_llm_spend=AsyncMock(),
        )
        with (
            patch("wikimind.services.plan_routing.get_settings") as mock_settings,
            patch.dict("sys.modules", {"wikimind.services.quota": mock_quota_module}),
        ):
            mock_settings.return_value.billing_enabled = True
            result = await plan_aware_complete(mock_router, request, "user-1", session=mock_session)

        assert result == mock_response
        assert request.disable_fallback is True

    @pytest.mark.asyncio
    async def test_byok_bypasses_plan_restrictions(self):
        """BYOK users on plans with byok_allowed use full router without restrictions."""
        from wikimind.services.plan_routing import plan_aware_complete

        mock_router = AsyncMock()
        mock_response = MagicMock()
        mock_router.complete.return_value = mock_response
        mock_router.has_user_key = AsyncMock(return_value=True)

        mock_plan = MagicMock()
        mock_plan.byok_allowed = True
        mock_plan.llm_provider = "openai"
        mock_plan.llm_model = "gpt-4o-mini"

        mock_session = MagicMock()

        request = CompletionRequest(
            system="test",
            messages=[{"role": "user", "content": "hi"}],
        )

        with patch("wikimind.services.plan_routing.get_settings") as mock_settings:
            mock_settings.return_value.billing_enabled = True

            with patch.dict(
                "sys.modules",
                {
                    "wikimind.services.quota": MagicMock(
                        get_effective_plan=AsyncMock(return_value=mock_plan),
                        check_daily_llm_spend=AsyncMock(),
                    )
                },
            ):
                result = await plan_aware_complete(mock_router, request, "user-1", session=mock_session)

        assert result == mock_response
        # BYOK path calls complete without modifying disable_fallback
        assert request.disable_fallback is False
        mock_router.complete.assert_called_once_with(request, user_id="user-1")
