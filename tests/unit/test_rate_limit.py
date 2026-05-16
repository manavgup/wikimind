"""Unit tests for rate limiting middleware."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

if TYPE_CHECKING:
    from httpx import AsyncClient


class TestRateLimitConfig:
    """Test that RateLimitConfig defaults are sensible."""

    def test_defaults(self):
        from wikimind.config import RateLimitConfig

        cfg = RateLimitConfig()
        assert cfg.enabled is True
        assert cfg.auth_limit == "5/minute"
        assert cfg.query_limit == "30/minute"
        assert cfg.ingest_limit == "10/minute"

    def test_custom_values(self):
        from wikimind.config import RateLimitConfig

        cfg = RateLimitConfig(
            enabled=False,
            auth_limit="10/minute",
            query_limit="60/minute",
            ingest_limit="20/minute",
        )
        assert cfg.enabled is False
        assert cfg.auth_limit == "10/minute"
        assert cfg.query_limit == "60/minute"
        assert cfg.ingest_limit == "20/minute"


class TestRateLimitKeyFunc:
    """Test the key extraction function."""

    def test_extracts_user_id(self):
        from wikimind.middleware.rate_limit import _key_func

        request = MagicMock()
        request.state.user_id = "user-123"
        assert _key_func(request) == "user-123"

    def test_falls_back_to_ip(self):
        from wikimind.middleware.rate_limit import _key_func

        request = MagicMock()
        request.state.user_id = None
        request.client.host = "192.168.1.1"
        assert _key_func(request) == "192.168.1.1"

    def test_no_user_id_attr_falls_back_to_ip(self):
        from wikimind.middleware.rate_limit import _key_func

        request = MagicMock(spec=[])
        request.state = None
        request.client = MagicMock()
        request.client.host = "10.0.0.1"
        assert _key_func(request) == "10.0.0.1"


class TestRateLimitExceededHandler:
    """Test the 429 error response format."""

    def test_handler_returns_429_with_retry_after(self):
        from wikimind.middleware.rate_limit import rate_limit_exceeded_handler

        request = MagicMock()
        request.state.request_id = "req-abc"

        exc = MagicMock()
        exc.detail = "5 per 1 minute"
        exc.headers = {"Retry-After": "42"}

        response = rate_limit_exceeded_handler(request, exc)
        assert response.status_code == 429
        assert response.headers.get("Retry-After") == "42"
        body = json.loads(response.body.decode())
        assert body["error"]["code"] == "rate_limited"
        assert body["error"]["request_id"] == "req-abc"
        assert "5 per 1 minute" in body["error"]["message"]

    def test_handler_defaults_retry_after_to_60(self):
        from wikimind.middleware.rate_limit import rate_limit_exceeded_handler

        request = MagicMock()
        request.state.request_id = "req-xyz"

        exc = MagicMock()
        exc.detail = "10 per 1 minute"
        exc.headers = {}

        response = rate_limit_exceeded_handler(request, exc)
        assert response.headers.get("Retry-After") == "60"

    def test_handler_missing_request_id(self):
        from wikimind.middleware.rate_limit import rate_limit_exceeded_handler

        request = MagicMock()
        del request.state.request_id  # simulate missing attribute

        exc = MagicMock()
        exc.detail = "rate limited"
        exc.headers = {"Retry-After": "30"}

        response = rate_limit_exceeded_handler(request, exc)
        body = json.loads(response.body.decode())
        assert body["error"]["request_id"] == "unknown"


class TestRateLimitIntegration:
    """Integration tests: verify rate-limited endpoints return 429 when exceeded."""

    @pytest.mark.asyncio
    async def test_auth_login_rate_limited(self, client: AsyncClient):
        """Auth login endpoint returns 429 after exceeding 5/minute limit."""
        from wikimind.middleware.rate_limit import limiter

        # Reset counters from any prior tests that hit this endpoint
        limiter.reset()
        limiter.enabled = True
        try:
            # The rate limit is 5/minute — make 6 requests
            for _ in range(5):
                resp = await client.get("/auth/login/google", follow_redirects=False)
                # May be 307 (redirect) or 400 (no client_id) — both are fine
                assert resp.status_code in (307, 302, 400)

            # 6th request should be rate limited
            resp = await client.get("/auth/login/google", follow_redirects=False)
            assert resp.status_code == 429
            assert "Retry-After" in resp.headers
            body = resp.json()
            assert body["error"]["code"] == "rate_limited"
        finally:
            limiter.reset()

    @pytest.mark.asyncio
    async def test_ingest_url_not_rate_limited_on_first_request(self, client: AsyncClient):
        """First ingest request should not be rate-limited."""
        from wikimind.middleware.rate_limit import limiter

        limiter.reset()
        limiter.enabled = True
        try:
            resp = await client.post(
                "/api/ingest/url",
                json={"url": "https://example.com/article"},
            )
            # Should not be 429 on first request (may fail for other reasons)
            assert resp.status_code != 429
        finally:
            limiter.reset()

    @pytest.mark.asyncio
    async def test_query_not_rate_limited_on_first_request(self, client: AsyncClient):
        """First query request should not be rate-limited."""
        from wikimind.middleware.rate_limit import limiter

        limiter.reset()
        limiter.enabled = True
        try:
            resp = await client.post(
                "/api/query",
                json={"question": "What is AI?"},
            )
            # Should not be 429 on first request
            assert resp.status_code != 429
        finally:
            limiter.reset()

    @pytest.mark.asyncio
    async def test_rate_limit_disabled_allows_unlimited(self, client: AsyncClient):
        """When rate limiting is disabled, no 429 responses are returned."""
        from wikimind.middleware.rate_limit import limiter

        limiter.reset()
        limiter.enabled = False
        try:
            # Make more requests than the limit — none should be rate limited
            for _ in range(10):
                resp = await client.get("/auth/login/google", follow_redirects=False)
                assert resp.status_code != 429
        finally:
            limiter.enabled = True
            limiter.reset()
