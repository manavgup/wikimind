"""Tests for MCP JWT authentication."""
from __future__ import annotations

import time

import jwt
import pytest

from wikimind.mcp.auth import WikiMindJWTAuthProvider

SECRET = "test-secret-key-at-least-32-chars-long"
USER_ID = "test-user-123"


def _make_token(payload: dict, secret: str = SECRET) -> str:
    return jwt.encode(payload, secret, algorithm="HS256")


def _valid_payload(**overrides) -> dict:
    base = {"sub": USER_ID, "email": "test@test.com", "exp": int(time.time()) + 3600}
    base.update(overrides)
    return base


class TestJWTValidation:
    @pytest.mark.asyncio
    async def test_valid_token_returns_user_id(self):
        provider = WikiMindJWTAuthProvider(secret=SECRET)
        token = _make_token(_valid_payload())
        result = await provider.verify_token(token)
        assert result.client_id == USER_ID

    @pytest.mark.asyncio
    async def test_expired_token_raises(self):
        provider = WikiMindJWTAuthProvider(secret=SECRET)
        token = _make_token(_valid_payload(exp=int(time.time()) - 100))
        with pytest.raises(Exception):
            await provider.verify_token(token)

    @pytest.mark.asyncio
    async def test_wrong_secret_raises(self):
        provider = WikiMindJWTAuthProvider(secret=SECRET)
        token = _make_token(_valid_payload(), secret="wrong-secret")
        with pytest.raises(Exception):
            await provider.verify_token(token)

    @pytest.mark.asyncio
    async def test_missing_sub_raises(self):
        provider = WikiMindJWTAuthProvider(secret=SECRET)
        token = _make_token({"email": "x@y.com", "exp": int(time.time()) + 3600})
        with pytest.raises(Exception):
            await provider.verify_token(token)

    @pytest.mark.asyncio
    async def test_non_hs256_algorithm_rejected(self):
        provider = WikiMindJWTAuthProvider(secret=SECRET)
        token = jwt.encode(_valid_payload(), SECRET, algorithm="HS384")
        with pytest.raises(Exception):
            await provider.verify_token(token)
