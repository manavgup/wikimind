"""Tests for shared FastAPI dependencies in wikimind.api.deps."""

import pytest


class TestRequirePlan:
    @pytest.mark.asyncio
    async def test_returns_none_for_self_hosted(self, monkeypatch):
        """In self-hosted mode, require_plan returns None (no quota enforcement)."""
        monkeypatch.setenv("WIKIMIND_DEPLOYMENT_MODE", "self_hosted")
        # Clear cached settings
        from wikimind.config import get_settings

        get_settings.cache_clear()
        try:
            from unittest.mock import AsyncMock

            from wikimind.api.deps import require_plan

            # Call the underlying function directly with mock deps
            result = await require_plan(user_id="test-user", session=AsyncMock())
            assert result is None
        finally:
            get_settings.cache_clear()


class TestQuotaExceededHandler:
    @pytest.mark.asyncio
    async def test_handler_returns_429(self):
        """quota_exceeded_handler returns HTTP 429 with the standard error envelope."""
        import json
        from unittest.mock import MagicMock

        from wikimind.main import quota_exceeded_handler
        from wikimind.services.quota import QuotaExceededError

        exc = QuotaExceededError("source", 20, 20)
        mock_request = MagicMock()
        mock_request.state.request_id = "test-req-123"

        response = await quota_exceeded_handler(mock_request, exc)
        assert response.status_code == 429
        body = json.loads(response.body)
        assert body["error"]["code"] == "quota_exceeded"
        assert body["error"]["resource"] == "source"
        assert body["error"]["limit"] == 20
        assert body["error"]["used"] == 20
        assert body["error"]["upgrade_url"] == "/settings/billing"
        assert body["error"]["request_id"] == "test-req-123"
