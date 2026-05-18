"""Tests for MCP personal access token authentication (ADR-027).

Covers token generation format, hash storage, PAT validation (valid,
revoked, expired, nonexistent), JWT fallback, and API endpoints
(generate, list, revoke).
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from tests.conftest import TEST_USER_ID
from wikimind._datetime import utcnow_naive
from wikimind.api.routes.mcp_tokens import _generate_pat
from wikimind.models import MCPAccessToken

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlmodel.ext.asyncio.session import AsyncSession


# ---------------------------------------------------------------------------
# Token generation unit tests
# ---------------------------------------------------------------------------


class TestTokenGeneration:
    """Test the _generate_pat helper."""

    def test_token_format(self) -> None:
        """Token starts with wmk_ prefix and is 36 chars total."""
        raw, _hash, _prefix = _generate_pat()
        assert raw.startswith("wmk_")
        # wmk_ (4) + 32 hex chars = 36
        assert len(raw) == 36

    def test_hash_is_sha256(self) -> None:
        """Token hash matches SHA-256 of the raw token."""
        raw, token_hash, _prefix = _generate_pat()
        expected = hashlib.sha256(raw.encode()).hexdigest()
        assert token_hash == expected

    def test_prefix_is_first_12_chars(self) -> None:
        """Token prefix is the first 12 characters of the raw token."""
        raw, _hash, prefix = _generate_pat()
        assert prefix == raw[:12]
        assert prefix.startswith("wmk_")

    def test_tokens_are_unique(self) -> None:
        """Successive calls produce different tokens."""
        raw1, _, _ = _generate_pat()
        raw2, _, _ = _generate_pat()
        assert raw1 != raw2


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


class TestCreateMCPToken:
    """Test POST /api/settings/mcp-tokens."""

    @pytest.mark.anyio
    async def test_create_token(self, client: AsyncClient) -> None:
        """Creating a token returns plaintext once and correct metadata."""
        resp = await client.post(
            "/api/settings/mcp-tokens",
            json={"name": "Claude Desktop"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Claude Desktop"
        assert data["token"].startswith("wmk_")
        assert "id" in data
        assert "created_at" in data

    @pytest.mark.anyio
    async def test_create_token_empty_name_rejected(self, client: AsyncClient) -> None:
        """Empty name is rejected by validation."""
        resp = await client.post(
            "/api/settings/mcp-tokens",
            json={"name": ""},
        )
        assert resp.status_code == 422


class TestListMCPTokens:
    """Test GET /api/settings/mcp-tokens."""

    @pytest.mark.anyio
    async def test_list_tokens_empty(self, client: AsyncClient) -> None:
        """List returns empty array when no tokens exist."""
        resp = await client.get("/api/settings/mcp-tokens")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.anyio
    async def test_list_tokens_after_create(self, client: AsyncClient) -> None:
        """Created tokens appear in the list without plaintext."""
        # Create two tokens
        await client.post("/api/settings/mcp-tokens", json={"name": "Token A"})
        await client.post("/api/settings/mcp-tokens", json={"name": "Token B"})

        resp = await client.get("/api/settings/mcp-tokens")
        assert resp.status_code == 200
        tokens = resp.json()
        assert len(tokens) == 2
        names = {t["name"] for t in tokens}
        assert names == {"Token A", "Token B"}

        # Plaintext must NOT appear in list response
        for t in tokens:
            assert "token" not in t
            assert t["token_prefix"].startswith("wmk_")

    @pytest.mark.anyio
    async def test_list_tokens_ordered_newest_first(self, client: AsyncClient) -> None:
        """Tokens are ordered by created_at descending."""
        await client.post("/api/settings/mcp-tokens", json={"name": "First"})
        await client.post("/api/settings/mcp-tokens", json={"name": "Second"})

        resp = await client.get("/api/settings/mcp-tokens")
        tokens = resp.json()
        assert tokens[0]["name"] == "Second"
        assert tokens[1]["name"] == "First"


class TestRevokeMCPToken:
    """Test DELETE /api/settings/mcp-tokens/{token_id}."""

    @pytest.mark.anyio
    async def test_revoke_token(self, client: AsyncClient) -> None:
        """Revoking a token sets revoked=True."""
        create_resp = await client.post(
            "/api/settings/mcp-tokens",
            json={"name": "Revocable"},
        )
        token_id = create_resp.json()["id"]

        resp = await client.delete(f"/api/settings/mcp-tokens/{token_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "revoked"

        # Verify it shows as revoked in list
        list_resp = await client.get("/api/settings/mcp-tokens")
        revoked_tokens = [t for t in list_resp.json() if t["id"] == token_id]
        assert len(revoked_tokens) == 1
        assert revoked_tokens[0]["revoked"] is True

    @pytest.mark.anyio
    async def test_revoke_nonexistent_token(self, client: AsyncClient) -> None:
        """Revoking a nonexistent token returns 404."""
        resp = await client.delete("/api/settings/mcp-tokens/does-not-exist")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PAT validation tests (auth provider)
# ---------------------------------------------------------------------------


class TestPATValidation:
    """Test the MCP auth provider's PAT validation path."""

    @pytest.mark.anyio
    async def test_valid_pat(
        self,
        db_session: AsyncSession,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """A valid, non-revoked, non-expired PAT returns an AccessToken."""
        from wikimind.mcp.auth import WikiMindAuthProvider

        raw_token = f"wmk_{secrets.token_hex(16)}"
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

        token_row = MCPAccessToken(
            user_id=TEST_USER_ID,
            name="Test Token",
            token_hash=token_hash,
            token_prefix=raw_token[:12],
        )
        db_session.add(token_row)
        await db_session.commit()

        provider = WikiMindAuthProvider(secret="unused-for-pat")

        with patch("wikimind.mcp.auth.get_session_factory", return_value=session_factory):
            access_token = await provider.verify_token(raw_token)

        assert access_token is not None
        assert access_token.client_id == TEST_USER_ID

    @pytest.mark.anyio
    async def test_revoked_pat_rejected(
        self,
        db_session: AsyncSession,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """A revoked PAT raises ValueError."""
        from wikimind.mcp.auth import WikiMindAuthProvider

        raw_token = f"wmk_{secrets.token_hex(16)}"
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

        token_row = MCPAccessToken(
            user_id=TEST_USER_ID,
            name="Revoked Token",
            token_hash=token_hash,
            token_prefix=raw_token[:12],
            revoked=True,
        )
        db_session.add(token_row)
        await db_session.commit()

        provider = WikiMindAuthProvider(secret="unused")

        with (
            patch("wikimind.mcp.auth.get_session_factory", return_value=session_factory),
            pytest.raises(ValueError, match="revoked"),
        ):
            await provider.verify_token(raw_token)

    @pytest.mark.anyio
    async def test_expired_pat_rejected(
        self,
        db_session: AsyncSession,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """An expired PAT raises ValueError."""
        from wikimind.mcp.auth import WikiMindAuthProvider

        raw_token = f"wmk_{secrets.token_hex(16)}"
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

        token_row = MCPAccessToken(
            user_id=TEST_USER_ID,
            name="Expired Token",
            token_hash=token_hash,
            token_prefix=raw_token[:12],
            expires_at=utcnow_naive() - timedelta(hours=1),
        )
        db_session.add(token_row)
        await db_session.commit()

        provider = WikiMindAuthProvider(secret="unused")

        with (
            patch("wikimind.mcp.auth.get_session_factory", return_value=session_factory),
            pytest.raises(ValueError, match="expired"),
        ):
            await provider.verify_token(raw_token)

    @pytest.mark.anyio
    async def test_nonexistent_pat_rejected(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """A PAT with no matching hash raises ValueError."""
        from wikimind.mcp.auth import WikiMindAuthProvider

        raw_token = f"wmk_{secrets.token_hex(16)}"
        provider = WikiMindAuthProvider(secret="unused")

        with (
            patch("wikimind.mcp.auth.get_session_factory", return_value=session_factory),
            pytest.raises(ValueError, match="Invalid token"),
        ):
            await provider.verify_token(raw_token)


# ---------------------------------------------------------------------------
# JWT validation fallback
# ---------------------------------------------------------------------------


class TestJWTFallback:
    """Test that non-PAT tokens still route to JWT validation."""

    @pytest.mark.anyio
    async def test_jwt_still_works(self) -> None:
        """A valid JWT is still accepted via the auth provider."""
        import jwt as pyjwt

        from wikimind.mcp.auth import WikiMindAuthProvider

        secret = "test-jwt-secret-key-for-tests!!"  # pragma: allowlist secret
        token = pyjwt.encode({"sub": "user-123"}, secret, algorithm="HS256")

        provider = WikiMindAuthProvider(secret=secret)
        access_token = await provider.verify_token(token)
        assert access_token is not None
        assert access_token.client_id == "user-123"

    @pytest.mark.anyio
    async def test_invalid_jwt_rejected(self) -> None:
        """An invalid JWT raises ValueError."""
        from wikimind.mcp.auth import WikiMindAuthProvider

        provider = WikiMindAuthProvider(secret="my-secret")
        with pytest.raises(ValueError, match="Invalid token"):
            await provider.verify_token("not.a.valid.jwt")

    @pytest.mark.anyio
    async def test_expired_jwt_rejected(self) -> None:
        """An expired JWT raises ValueError."""
        import jwt as pyjwt

        from wikimind.mcp.auth import WikiMindAuthProvider

        secret = "test-jwt-secret-key-for-tests!!"  # pragma: allowlist secret
        past = utcnow_naive() - timedelta(hours=1)
        token = pyjwt.encode(
            {"sub": "user-123", "exp": past},
            secret,
            algorithm="HS256",
        )

        provider = WikiMindAuthProvider(secret=secret)
        with pytest.raises(ValueError, match="expired"):
            await provider.verify_token(token)
