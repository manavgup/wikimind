"""Tests for OAuth2 authentication — JWT helpers, middleware, /auth/me, and OAuth state."""

import base64
import hashlib
import hmac
import inspect
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import TEST_JWT_SECRET, TEST_USER_ID
from wikimind.api.deps import get_ws_user_id
from wikimind.api.routes import ws as ws_mod
from wikimind.api.routes.auth import (
    _consume_oauth_state,
    _generate_oauth_state,
)
from wikimind.config import get_settings
from wikimind.models import OAuthUserInfo, User
from wikimind.services.user import UserService

_service = UserService()

# ---------------------------------------------------------------------------
# JWT creation / decoding
# ---------------------------------------------------------------------------


def test_create_jwt_contains_expected_claims():
    """JWT payload should contain sub, email, iat, and exp claims."""
    settings = get_settings()
    settings.auth.jwt_secret_key = TEST_JWT_SECRET
    settings.auth.jwt_algorithm = "HS256"
    settings.auth.jwt_expiry_minutes = 60

    user = User(
        id="user-1",
        email="alice@example.com",
        auth_provider="google",
        auth_provider_id="g-123",
    )

    token = _service.create_jwt(user, settings)
    payload = jwt.decode(token, TEST_JWT_SECRET, algorithms=["HS256"])

    assert payload["sub"] == "user-1"
    assert payload["email"] == "alice@example.com"
    assert "exp" in payload
    assert "iat" in payload


def test_create_jwt_expiry():
    """JWT should expire after the configured number of minutes."""
    settings = get_settings()
    settings.auth.jwt_secret_key = TEST_JWT_SECRET
    settings.auth.jwt_algorithm = "HS256"
    settings.auth.jwt_expiry_minutes = 30

    user = User(
        id="user-1",
        email="alice@example.com",
        auth_provider="github",
        auth_provider_id="gh-456",
    )

    token = _service.create_jwt(user, settings)
    payload = jwt.decode(token, TEST_JWT_SECRET, algorithms=["HS256"])

    now = datetime.now(UTC)
    exp = datetime.fromtimestamp(payload["exp"], tz=UTC)
    # Expiry should be ~30 minutes from now (within a 5-second tolerance)
    assert abs((exp - now).total_seconds() - 1800) < 5


# ---------------------------------------------------------------------------
# Auth middleware — dev mode auto-auth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_middleware_auto_auth_in_test_mode(client):
    """In test mode, all requests are auto-authenticated as TEST_USER_ID."""
    response = await client.get("/health")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Auth middleware — production mode (JWT required)
# ---------------------------------------------------------------------------


@pytest.fixture
async def _prod_client(monkeypatch):
    """ASGI client with the real (un-patched) AuthMiddleware in production mode."""
    from httpx import ASGITransport
    from httpx import AsyncClient as HttpxClient

    from wikimind.main import app

    settings = get_settings()
    monkeypatch.setattr(settings.auth, "jwt_secret_key", TEST_JWT_SECRET)
    monkeypatch.setattr(settings.auth, "dev_auto_auth", False)
    monkeypatch.setattr(settings, "env", "production")

    transport = ASGITransport(app=app)
    async with HttpxClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_middleware_returns_401_when_no_token(_prod_client):
    """Missing token should return 401 in production mode."""
    response = await _prod_client.get("/api/wiki/articles")
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_middleware_returns_401_when_token_expired(_prod_client):
    """An expired JWT should return a TOKEN_EXPIRED error."""
    expired_payload = {
        "sub": "user-1",
        "email": "alice@example.com",
        "exp": datetime.now(UTC) - timedelta(hours=1),
        "iat": datetime.now(UTC) - timedelta(hours=2),
    }
    expired_token = jwt.encode(expired_payload, TEST_JWT_SECRET, algorithm="HS256")

    response = await _prod_client.get(
        "/api/wiki/articles",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "TOKEN_EXPIRED"


@pytest.mark.asyncio
async def test_middleware_returns_401_when_token_invalid(_prod_client):
    """A token signed with the wrong key should return INVALID_TOKEN."""
    bad_token = jwt.encode(
        {"sub": "user-1", "email": "a@b.com", "exp": datetime.now(UTC) + timedelta(hours=1)},
        "wrong-secret-key-for-unit-tests!!",
        algorithm="HS256",
    )

    response = await _prod_client.get(
        "/api/wiki/articles",
        headers={"Authorization": f"Bearer {bad_token}"},
    )
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "INVALID_TOKEN"


@pytest.mark.asyncio
async def test_middleware_passes_with_valid_token(_prod_client):
    """A valid JWT should allow the request through."""
    valid_token = jwt.encode(
        {
            "sub": "user-1",
            "email": "alice@example.com",
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        TEST_JWT_SECRET,
        algorithm="HS256",
    )

    response = await _prod_client.get(
        "/health",
        headers={"Authorization": f"Bearer {valid_token}"},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_middleware_skips_exempt_paths(_prod_client):
    """Exempt paths should not require authentication even in production mode."""
    response = await _prod_client.get("/health")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Auth middleware — static extension bypass security (#544)
# ---------------------------------------------------------------------------


def test_png_not_in_static_extensions():
    """`.png` must not be in _STATIC_EXTENSIONS — API-served images need auth (#544)."""
    from wikimind.middleware.auth import _STATIC_EXTENSIONS

    assert ".png" not in _STATIC_EXTENSIONS


def test_svg_not_in_static_extensions():
    """`.svg` must not be in _STATIC_EXTENSIONS — API-served SVGs need auth (#544)."""
    from wikimind.middleware.auth import _STATIC_EXTENSIONS

    assert ".svg" not in _STATIC_EXTENSIONS


def test_static_extensions_include_js_css():
    """Frontend build assets (.js, .css) should remain in _STATIC_EXTENSIONS."""
    from wikimind.middleware.auth import _STATIC_EXTENSIONS

    assert ".js" in _STATIC_EXTENSIONS
    assert ".css" in _STATIC_EXTENSIONS


def test_assets_prefix_is_exempt():
    """The /assets/ prefix should be in EXEMPT_PREFIXES for static frontend files."""
    from wikimind.middleware.auth import EXEMPT_PREFIXES

    assert any(p == "/assets/" for p in EXEMPT_PREFIXES)


def test_png_path_not_exempt_from_auth():
    """An API path ending in .png must NOT match any extension or prefix exemption (#544).

    This verifies the middleware exemption logic directly, independent of
    HTTP transport and settings mocking.
    """
    from wikimind.middleware.auth import _STATIC_EXTENSIONS, EXEMPT_PATHS, EXEMPT_PREFIXES

    path = "/api/ingest/sources/123/images/test.png"
    is_exempt = (
        path in EXEMPT_PATHS
        or any(path.startswith(p) for p in EXEMPT_PREFIXES)
        or any(path.endswith(ext) for ext in _STATIC_EXTENSIONS)
    )
    assert not is_exempt, f"{path} should not be exempt from auth"


def test_assets_png_path_exempt_via_prefix():
    """A .png under /assets/ is exempt via the prefix rule, not the extension rule."""
    from wikimind.middleware.auth import EXEMPT_PREFIXES

    path = "/assets/logo.png"
    assert any(path.startswith(p) for p in EXEMPT_PREFIXES)


# ---------------------------------------------------------------------------
# /auth/me
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_me_returns_user_profile(client):
    """GET /auth/me should return the authenticated user's profile."""
    # The client fixture auto-authenticates as TEST_USER_ID and seeds the user row.
    response = await client.get("/auth/me")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == TEST_USER_ID
    assert body["email"] == "test@wikimind.local"


@pytest.mark.asyncio
async def test_auth_me_returns_401_when_no_user(_prod_client):
    """GET /auth/me with no authenticated user returns 401."""
    # /auth/me is an SPA route when Accept includes text/html (exempt from JWT).
    # Without auth the middleware sets user_id=None → the endpoint returns 401.
    response = await _prod_client.get("/auth/me")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# User upsert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_user_creates_new_user(db_session: AsyncSession):
    """First login should create a new User record."""
    user_info = OAuthUserInfo(
        id="google-id-1",
        email="new@example.com",
        name="New User",
        picture="https://example.com/pic.jpg",
    )
    user = await _service.upsert_oauth_user(db_session, "google", user_info)
    assert user.email == "new@example.com"
    assert user.auth_provider == "google"
    assert user.auth_provider_id == "google-id-1"


@pytest.mark.asyncio
async def test_upsert_user_updates_existing_user(db_session: AsyncSession):
    """Re-login should update the existing User record."""
    user_info = OAuthUserInfo(
        id="google-id-2",
        email="existing@example.com",
        name="Old Name",
        picture=None,
    )
    user1 = await _service.upsert_oauth_user(db_session, "google", user_info)

    user_info_updated = OAuthUserInfo(
        id="google-id-2",
        email="existing@example.com",
        name="New Name",
        picture="https://example.com/new.jpg",
    )
    user2 = await _service.upsert_oauth_user(db_session, "google", user_info_updated)

    assert user1.id == user2.id
    assert user2.name == "New Name"
    assert user2.avatar_url == "https://example.com/new.jpg"


# ---------------------------------------------------------------------------
# WebSocket user extraction — get_ws_user_id
# ---------------------------------------------------------------------------


def _make_ws_mock(
    cookies: dict[str, str] | None = None,
    query_params: dict[str, str] | None = None,
) -> MagicMock:
    """Build a MagicMock that mimics a ``WebSocket`` with cookies and query_params."""
    ws = MagicMock()
    ws.cookies = cookies or {}
    ws.query_params = query_params or {}
    ws.close = AsyncMock()
    return ws


@pytest.mark.asyncio
async def test_get_ws_user_id_extracts_user_from_jwt_cookie(monkeypatch):
    """get_ws_user_id should decode user_id from the session cookie."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "jwt_secret_key", TEST_JWT_SECRET)
    monkeypatch.setattr(settings.auth, "jwt_algorithm", "HS256")
    monkeypatch.setattr(settings.auth, "dev_auto_auth", False)
    monkeypatch.setattr(settings, "env", "production")

    token = jwt.encode(
        {
            "sub": "user-99",
            "email": "ws@example.com",
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        TEST_JWT_SECRET,
        algorithm="HS256",
    )

    ws = _make_ws_mock(cookies={settings.auth.cookie_name: token})
    result = await get_ws_user_id(ws)
    assert result == "user-99"


@pytest.mark.asyncio
async def test_get_ws_user_id_falls_back_to_token_query_param(monkeypatch):
    """When no cookie is present, get_ws_user_id should try the ``token`` query param."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "jwt_secret_key", TEST_JWT_SECRET)
    monkeypatch.setattr(settings.auth, "jwt_algorithm", "HS256")
    monkeypatch.setattr(settings.auth, "dev_auto_auth", False)
    monkeypatch.setattr(settings, "env", "production")

    token = jwt.encode(
        {
            "sub": "user-77",
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        TEST_JWT_SECRET,
        algorithm="HS256",
    )

    ws = _make_ws_mock(query_params={"token": token})
    result = await get_ws_user_id(ws)
    assert result == "user-77"


@pytest.mark.asyncio
async def test_get_ws_user_id_rejects_missing_token(monkeypatch):
    """When no token is provided, get_ws_user_id should reject the connection."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "jwt_secret_key", TEST_JWT_SECRET)
    monkeypatch.setattr(settings.auth, "dev_auto_auth", False)
    monkeypatch.setattr(settings, "env", "production")

    ws = _make_ws_mock()
    with pytest.raises(HTTPException):
        await get_ws_user_id(ws)


@pytest.mark.asyncio
async def test_get_ws_user_id_rejects_invalid_token(monkeypatch):
    """An invalid JWT should cause get_ws_user_id to reject the connection."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "jwt_secret_key", TEST_JWT_SECRET)
    monkeypatch.setattr(settings.auth, "jwt_algorithm", "HS256")
    monkeypatch.setattr(settings.auth, "dev_auto_auth", False)
    monkeypatch.setattr(settings, "env", "production")

    bad_token = jwt.encode(
        {"sub": "user-1", "exp": datetime.now(UTC) + timedelta(hours=1)},
        "wrong-secret-key-for-unit-tests!!",
        algorithm="HS256",
    )

    ws = _make_ws_mock(cookies={settings.auth.cookie_name: bad_token})
    with pytest.raises(HTTPException):
        await get_ws_user_id(ws)


@pytest.mark.asyncio
async def test_get_ws_user_id_rejects_expired_token(monkeypatch):
    """An expired JWT should cause get_ws_user_id to reject the connection."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "jwt_secret_key", TEST_JWT_SECRET)
    monkeypatch.setattr(settings.auth, "jwt_algorithm", "HS256")
    monkeypatch.setattr(settings.auth, "dev_auto_auth", False)
    monkeypatch.setattr(settings, "env", "production")

    expired_token = jwt.encode(
        {
            "sub": "user-1",
            "exp": datetime.now(UTC) - timedelta(hours=1),
            "iat": datetime.now(UTC) - timedelta(hours=2),
        },
        TEST_JWT_SECRET,
        algorithm="HS256",
    )

    ws = _make_ws_mock(cookies={settings.auth.cookie_name: expired_token})
    with pytest.raises(HTTPException):
        await get_ws_user_id(ws)


@pytest.mark.asyncio
async def test_websocket_endpoint_ignores_user_id_query_param(monkeypatch):
    """The /ws endpoint must NOT honour a ``user_id`` query parameter."""
    # Verify via source inspection that the ws.py module no longer reads user_id
    # from query_params — it delegates to get_ws_user_id instead.
    source = inspect.getsource(ws_mod.websocket_endpoint)
    assert "query_params" not in source, "websocket_endpoint should not read query_params directly"
    assert "get_ws_user_id" in source, "websocket_endpoint should delegate to get_ws_user_id"


# ---------------------------------------------------------------------------
# OAuth state token management (HMAC-signed stateless tokens)
# ---------------------------------------------------------------------------


def _build_state_token(provider: str, timestamp: int, secret: str) -> str:
    """Helper: build an HMAC-signed state token for testing."""
    payload = f"{provider}:{timestamp}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha384).hexdigest()
    raw = f"{payload}:{sig}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def test_generate_oauth_state_returns_unique_tokens(monkeypatch):
    """_generate_oauth_state should return distinct tokens for successive calls."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "jwt_secret_key", TEST_JWT_SECRET)

    token1 = _generate_oauth_state("google")
    # Advance time by 1 second to guarantee a different timestamp
    original_time = time.time
    monkeypatch.setattr(time, "time", lambda: original_time() + 1)
    token2 = _generate_oauth_state("google")
    assert token1 != token2
    assert len(token1) > 20


def test_generate_oauth_state_encodes_provider(monkeypatch):
    """The generated token should encode the provider name (verifiable via consume)."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "jwt_secret_key", TEST_JWT_SECRET)

    token = _generate_oauth_state("github")
    result = _consume_oauth_state(token)
    assert result == "github"


def test_consume_oauth_state_returns_provider(monkeypatch):
    """_consume_oauth_state should return the provider for a valid token."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "jwt_secret_key", TEST_JWT_SECRET)

    token = _generate_oauth_state("google")
    result = _consume_oauth_state(token)
    assert result == "google"


def test_consume_oauth_state_rejects_unknown_token(monkeypatch):
    """An unknown/garbage state token should return None."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "jwt_secret_key", TEST_JWT_SECRET)

    result = _consume_oauth_state("bogus-token")
    assert result is None


def test_consume_oauth_state_rejects_tampered_token(monkeypatch):
    """A token with a tampered payload should be rejected."""
    settings = get_settings()
    secret = TEST_JWT_SECRET  # pragma: allowlist secret
    monkeypatch.setattr(settings.auth, "jwt_secret_key", secret)

    token = _generate_oauth_state("google")
    # Decode, tamper with provider, re-encode (without re-signing)
    raw = base64.urlsafe_b64decode(token.encode()).decode()
    parts = raw.rsplit(":", 2)
    tampered_raw = f"evil:{parts[1]}:{parts[2]}"
    tampered = base64.urlsafe_b64encode(tampered_raw.encode()).decode()
    assert _consume_oauth_state(tampered) is None


def test_consume_oauth_state_rejects_expired_token(monkeypatch):
    """A state token older than oauth_state_ttl_seconds should be rejected."""
    settings = get_settings()
    secret = TEST_JWT_SECRET  # pragma: allowlist secret
    monkeypatch.setattr(settings.auth, "jwt_secret_key", secret)
    monkeypatch.setattr(settings.auth, "oauth_state_ttl_seconds", 600)

    # Build a token with a timestamp 601 seconds in the past
    old_ts = int(time.time()) - 601
    token = _build_state_token("github", old_ts, secret)
    result = _consume_oauth_state(token)
    assert result is None


def test_consume_oauth_state_rejects_wrong_signature(monkeypatch):
    """A token signed with a different secret should be rejected."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "jwt_secret_key", "correct-secret")

    # Build a token signed with a different secret
    token = _build_state_token("google", int(time.time()), "wrong-secret-key-for-unit-tests!!")
    result = _consume_oauth_state(token)
    assert result is None


def test_login_state_is_not_provider_name(monkeypatch):
    """The state parameter in the authorize URL must not be the provider name."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "jwt_secret_key", TEST_JWT_SECRET)

    token = _generate_oauth_state("google")
    assert token != "google"
    assert token != "github"


# ---------------------------------------------------------------------------
# GET /auth/tokens — token generation page
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_page_returns_html(client):
    """GET /auth/tokens should return the token generation HTML page."""
    resp = await client.get("/auth/tokens", headers={"Accept": "text/html"})
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "WikiMind" in resp.text
    assert "Generate Token" in resp.text


@pytest.mark.asyncio
async def test_token_page_uses_external_script(client):
    """Token page HTML should reference external JS, not inline scripts."""
    resp = await client.get("/auth/tokens", headers={"Accept": "text/html"})
    assert resp.status_code == 200
    assert '<script src="/auth/tokens.js">' in resp.text
    # No inline script blocks (only the external script tag)
    assert resp.text.count("<script") == 1


@pytest.mark.asyncio
async def test_token_page_js_served(client):
    """GET /auth/tokens.js should return JavaScript with correct content type."""
    resp = await client.get("/auth/tokens.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"]
    assert "checkAuth" in resp.text
    assert "generateToken" in resp.text


# ---------------------------------------------------------------------------
# OAuth login ?next= redirect cookie
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_sets_next_cookie_for_safe_path(client, monkeypatch):
    """GET /auth/login/google?next=/auth/tokens should set a wikimind_next cookie."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "google_client_id", "fake-id")
    monkeypatch.setattr(settings.auth, "jwt_secret_key", TEST_JWT_SECRET)

    resp = await client.get("/auth/login/google?next=/auth/tokens", follow_redirects=False)
    assert resp.status_code == 307
    assert "wikimind_next" in resp.cookies
    assert "/auth/tokens" in resp.cookies["wikimind_next"]


@pytest.mark.asyncio
async def test_login_ignores_unsafe_next_url(client, monkeypatch):
    """GET /auth/login/google?next=//evil.com should NOT set a wikimind_next cookie."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "google_client_id", "fake-id")
    monkeypatch.setattr(settings.auth, "jwt_secret_key", TEST_JWT_SECRET)

    resp = await client.get("/auth/login/google?next=//evil.com", follow_redirects=False)
    assert resp.status_code == 307
    assert "wikimind_next" not in resp.cookies


# ---------------------------------------------------------------------------
# X-Forwarded-Proto support
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_uses_x_forwarded_proto(client, monkeypatch):
    """Login redirect should use X-Forwarded-Proto for the callback URL."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "google_client_id", "fake-id")
    monkeypatch.setattr(settings.auth, "jwt_secret_key", TEST_JWT_SECRET)

    resp = await client.get(
        "/auth/login/google",
        headers={"X-Forwarded-Proto": "https", "Host": "wikimind.fly.dev"},
        follow_redirects=False,
    )
    assert resp.status_code == 307
    location = resp.headers["location"]
    assert "redirect_uri=https://wikimind.fly.dev/auth/callback" in location


# ---------------------------------------------------------------------------
# POST /auth/token — long-lived API tokens
# ---------------------------------------------------------------------------


def _auth_header(
    user_id: str = "user-1",
    secret: str = TEST_JWT_SECRET,  # pragma: allowlist secret
) -> dict[str, str]:
    """Build an Authorization header with a valid session JWT."""
    token = jwt.encode(
        {
            "sub": user_id,
            "email": "test@example.com",
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        secret,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_create_api_token_returns_jwt(client, db_session: AsyncSession, monkeypatch):
    """POST /auth/token should return a valid JWT with the expected response shape."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "jwt_secret_key", TEST_JWT_SECRET)

    # The client fixture auto-authenticates as TEST_USER_ID, and we need
    # a User row for that ID to exist for the token endpoint.
    # (The client fixture already seeds it.)

    response = await client.post(
        "/auth/token",
        json={"name": "my-cli-token", "expires_in_days": 90},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["name"] == "my-cli-token"
    assert "access_token" in body
    assert "expires_at" in body

    # The access_token should be a valid JWT
    decoded = jwt.decode(
        body["access_token"],
        TEST_JWT_SECRET,
        algorithms=["HS256"],
        options={"verify_aud": False},
    )
    assert decoded["sub"] is not None


@pytest.mark.asyncio
async def test_api_token_has_correct_claims(client, db_session: AsyncSession, monkeypatch):
    """The API token JWT should contain all expected claims."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "jwt_secret_key", TEST_JWT_SECRET)

    response = await client.post(
        "/auth/token",
        json={"name": "automation"},
    )
    assert response.status_code == 200

    decoded = jwt.decode(
        response.json()["access_token"],
        TEST_JWT_SECRET,
        algorithms=["HS256"],
        options={"verify_aud": False},
    )

    assert decoded["iss"] == "wikimind"
    assert decoded["aud"] == "wikimind-api"
    assert decoded["token_use"] == "api"
    assert "jti" in decoded
    assert "iat" in decoded
    assert "exp" in decoded
    assert decoded["user"]["id"] == TEST_USER_ID
    assert decoded["user"]["email"] == "test@wikimind.local"


@pytest.mark.asyncio
async def test_api_token_expires_in_requested_days(client, db_session: AsyncSession, monkeypatch):
    """The API token exp claim should match the requested expires_in_days."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "jwt_secret_key", TEST_JWT_SECRET)

    days = 60
    response = await client.post(
        "/auth/token",
        json={"name": "long-token", "expires_in_days": days},
    )
    assert response.status_code == 200

    decoded = jwt.decode(
        response.json()["access_token"],
        TEST_JWT_SECRET,
        algorithms=["HS256"],
        options={"verify_aud": False},
    )

    now = datetime.now(UTC)
    exp = datetime.fromtimestamp(decoded["exp"], tz=UTC)
    expected_seconds = days * 86400
    # Allow 10-second tolerance for test execution time
    assert abs((exp - now).total_seconds() - expected_seconds) < 10
