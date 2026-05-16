"""Tests for MCP JWT authentication.

Verifies the WikiMindJWTAuthProvider correctly validates JWTs and
that tool handlers extract user_id from the auth context.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from mcp.server.auth.middleware.auth_context import AuthenticatedUser, auth_context_var

from tests.conftest import TEST_JWT_SECRET, TEST_USER_ID
from wikimind.mcp.auth import WikiMindJWTAuthProvider

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def auth_provider():
    """Create an auth provider instance."""
    return WikiMindJWTAuthProvider()


@pytest.fixture
def valid_token():
    """Create a valid JWT token."""
    payload = {
        "sub": TEST_USER_ID,
        "email": "test@example.com",
        "exp": int(time.time()) + 3600,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


@pytest.fixture
def valid_token_nested_email():
    """Create a valid JWT with email in nested user claim."""
    payload = {
        "sub": TEST_USER_ID,
        "user": {"email": "nested@example.com"},
        "exp": int(time.time()) + 3600,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


@pytest.fixture
def expired_token():
    """Create an expired JWT token."""
    payload = {
        "sub": TEST_USER_ID,
        "email": "test@example.com",
        "exp": int(time.time()) - 3600,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


# ---------------------------------------------------------------------------
# WikiMindJWTAuthProvider.verify_token
# ---------------------------------------------------------------------------


class TestWikiMindJWTAuthProvider:
    """Test JWT verification for MCP HTTP transport."""

    async def test_valid_token_returns_access_token(self, auth_provider, valid_token):
        with patch("wikimind.mcp.auth.get_settings") as mock_settings:
            mock_settings.return_value.auth.jwt_secret_key = TEST_JWT_SECRET
            mock_settings.return_value.auth.jwt_algorithm = "HS256"

            result = await auth_provider.verify_token(valid_token)

            assert result is not None
            assert result.client_id == TEST_USER_ID
            assert result.claims["user_id"] == TEST_USER_ID
            assert result.claims["email"] == "test@example.com"

    async def test_nested_email_extraction(self, auth_provider, valid_token_nested_email):
        with patch("wikimind.mcp.auth.get_settings") as mock_settings:
            mock_settings.return_value.auth.jwt_secret_key = TEST_JWT_SECRET
            mock_settings.return_value.auth.jwt_algorithm = "HS256"

            result = await auth_provider.verify_token(valid_token_nested_email)

            assert result is not None
            assert result.claims["email"] == "nested@example.com"

    async def test_expired_token_returns_none(self, auth_provider, expired_token):
        with patch("wikimind.mcp.auth.get_settings") as mock_settings:
            mock_settings.return_value.auth.jwt_secret_key = TEST_JWT_SECRET
            mock_settings.return_value.auth.jwt_algorithm = "HS256"

            result = await auth_provider.verify_token(expired_token)

            assert result is None

    async def test_invalid_token_returns_none(self, auth_provider):
        with patch("wikimind.mcp.auth.get_settings") as mock_settings:
            mock_settings.return_value.auth.jwt_secret_key = TEST_JWT_SECRET
            mock_settings.return_value.auth.jwt_algorithm = "HS256"

            result = await auth_provider.verify_token("not-a-valid-jwt")

            assert result is None

    async def test_wrong_secret_returns_none(self, auth_provider, valid_token):
        with patch("wikimind.mcp.auth.get_settings") as mock_settings:
            mock_settings.return_value.auth.jwt_secret_key = "wrong-secret"
            mock_settings.return_value.auth.jwt_algorithm = "HS256"

            result = await auth_provider.verify_token(valid_token)

            assert result is None

    async def test_missing_sub_claim_returns_none(self, auth_provider):
        payload = {
            "email": "test@example.com",
            "exp": int(time.time()) + 3600,
        }
        token = jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")

        with patch("wikimind.mcp.auth.get_settings") as mock_settings:
            mock_settings.return_value.auth.jwt_secret_key = TEST_JWT_SECRET
            mock_settings.return_value.auth.jwt_algorithm = "HS256"

            result = await auth_provider.verify_token(token)

            assert result is None


# ---------------------------------------------------------------------------
# _get_mcp_user_id with auth context
# ---------------------------------------------------------------------------


class TestGetMCPUserIdWithAuth:
    """Test that _get_mcp_user_id reads from auth context when available."""

    async def test_returns_user_id_from_auth_context(self):
        from fastmcp.server.auth import AccessToken

        from wikimind.mcp.server import _get_mcp_user_id

        access_token = AccessToken(
            token="fake-token",
            client_id=TEST_USER_ID,
            scopes=[],
            claims={"user_id": TEST_USER_ID, "email": "test@example.com"},
        )
        auth_user = AuthenticatedUser(auth_info=access_token)

        token = auth_context_var.set(auth_user)
        try:
            result = await _get_mcp_user_id()
            assert result == TEST_USER_ID
        finally:
            auth_context_var.reset(token)

    async def test_falls_back_to_dev_user_when_no_auth_context(self):
        from wikimind.mcp.server import _get_mcp_user_id

        # Ensure auth_context_var is unset
        token = auth_context_var.set(None)
        try:
            with patch("wikimind.mcp.server.get_dev_user_id", new_callable=AsyncMock) as mock:
                mock.return_value = "dev-user-123"
                result = await _get_mcp_user_id()
                assert result == "dev-user-123"
                mock.assert_called_once()
        finally:
            auth_context_var.reset(token)


# ---------------------------------------------------------------------------
# run_server auth configuration
# ---------------------------------------------------------------------------


class TestRunServerAuthConfig:
    """Test that run_server correctly applies auth for HTTP transport."""

    def test_http_transport_sets_auth_when_require_auth_true(self):
        from wikimind.mcp.server import mcp as mcp_server

        # Reset any existing auth
        mcp_server.auth = None

        with (
            patch("wikimind.mcp.server.get_settings") as mock_settings,
            patch.object(mcp_server, "run") as mock_run,
            patch("sys.argv", ["mcp-server", "--transport", "http"]),
        ):
            mock_settings.return_value.mcp.require_auth = True
            mock_settings.return_value.auth.jwt_secret_key = TEST_JWT_SECRET
            mock_settings.return_value.auth.jwt_algorithm = "HS256"

            from wikimind.mcp.server import run_server

            run_server()

            # Auth should be set
            assert mcp_server.auth is not None
            assert isinstance(mcp_server.auth, WikiMindJWTAuthProvider)
            mock_run.assert_called_once_with(transport="http", host="127.0.0.1", port=9100)

        # Cleanup
        mcp_server.auth = None

    def test_http_transport_no_auth_when_require_auth_false(self):
        from wikimind.mcp.server import mcp as mcp_server

        # Reset any existing auth
        mcp_server.auth = None

        with (
            patch("wikimind.mcp.server.get_settings") as mock_settings,
            patch.object(mcp_server, "run") as mock_run,
            patch("sys.argv", ["mcp-server", "--transport", "http"]),
        ):
            mock_settings.return_value.mcp.require_auth = False

            from wikimind.mcp.server import run_server

            run_server()

            # Auth should NOT be set
            assert mcp_server.auth is None
            mock_run.assert_called_once_with(transport="http", host="127.0.0.1", port=9100)

    def test_stdio_transport_never_sets_auth(self):
        from wikimind.mcp.server import mcp as mcp_server

        # Reset any existing auth
        mcp_server.auth = None

        with (
            patch.object(mcp_server, "run") as mock_run,
            patch("sys.argv", ["mcp-server", "--transport", "stdio"]),
        ):
            from wikimind.mcp.server import run_server

            run_server()

            # Auth should NOT be set for stdio
            assert mcp_server.auth is None
            mock_run.assert_called_once_with(transport="stdio")
