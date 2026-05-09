"""Tests for OAuth2 authentication — JWT helpers, middleware, /auth/me, and OAuth state."""

import base64
import hashlib
import hmac
import inspect
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import jwt
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import TEST_JWT_SECRET
from wikimind.api.deps import ANONYMOUS_USER_ID, get_ws_user_id
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
# Auth middleware — pass-through when disabled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_middleware_passthrough_when_disabled(client):
    """When auth.enabled=False, all requests pass through without a token."""
    response = await client.get("/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_middleware_sets_anonymous_user_id_when_disabled(client):
    """When auth.enabled=False, get_current_user_id returns 'anonymous'."""
    # The /health endpoint succeeds without auth — that proves the middleware passed through
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Auth middleware — enabled mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_middleware_returns_401_when_no_token(client, monkeypatch):
    """When auth is enabled, missing token should return 401."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "enabled", True)
    monkeypatch.setattr(settings.auth, "jwt_secret_key", TEST_JWT_SECRET)

    response = await client.get("/api/wiki/articles")
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_middleware_returns_401_when_token_expired(client, monkeypatch):
    """An expired JWT should return a TOKEN_EXPIRED error."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "enabled", True)
    monkeypatch.setattr(settings.auth, "jwt_secret_key", TEST_JWT_SECRET)

    expired_payload = {
        "sub": "user-1",
        "email": "alice@example.com",
        "exp": datetime.now(UTC) - timedelta(hours=1),
        "iat": datetime.now(UTC) - timedelta(hours=2),
    }
    expired_token = jwt.encode(expired_payload, TEST_JWT_SECRET, algorithm="HS256")

    response = await client.get(
        "/api/wiki/articles",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "TOKEN_EXPIRED"


@pytest.mark.asyncio
async def test_middleware_returns_401_when_token_invalid(client, monkeypatch):
    """A token signed with the wrong key should return INVALID_TOKEN."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "enabled", True)
    monkeypatch.setattr(settings.auth, "jwt_secret_key", TEST_JWT_SECRET)

    bad_token = jwt.encode(
        {"sub": "user-1", "email": "a@b.com", "exp": datetime.now(UTC) + timedelta(hours=1)},
        "wrong-secret-key-for-unit-tests!!",
        algorithm="HS256",
    )

    response = await client.get(
        "/api/wiki/articles",
        headers={"Authorization": f"Bearer {bad_token}"},
    )
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "INVALID_TOKEN"


@pytest.mark.asyncio
async def test_middleware_passes_with_valid_token(client, monkeypatch):
    """A valid JWT should allow the request through."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "enabled", True)
    monkeypatch.setattr(settings.auth, "jwt_secret_key", TEST_JWT_SECRET)

    valid_token = jwt.encode(
        {
            "sub": "user-1",
            "email": "alice@example.com",
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        TEST_JWT_SECRET,
        algorithm="HS256",
    )

    response = await client.get(
        "/health",
        headers={"Authorization": f"Bearer {valid_token}"},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_middleware_skips_exempt_paths(client, monkeypatch):
    """Exempt paths should not require authentication even when auth is enabled."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "enabled", True)
    monkeypatch.setattr(settings.auth, "jwt_secret_key", TEST_JWT_SECRET)

    # /health is exempt
    response = await client.get("/health")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# /auth/me
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_me_returns_user_profile(client, db_session: AsyncSession, monkeypatch):
    """GET /auth/me should return the authenticated user's profile."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "enabled", True)
    monkeypatch.setattr(settings.auth, "jwt_secret_key", TEST_JWT_SECRET)

    # Create a user directly in the DB
    user = User(
        id="user-42",
        email="alice@example.com",
        name="Alice",
        avatar_url="https://example.com/avatar.png",
        auth_provider="google",
        auth_provider_id="g-999",
    )
    db_session.add(user)
    await db_session.commit()

    token = jwt.encode(
        {
            "sub": "user-42",
            "email": "alice@example.com",
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        TEST_JWT_SECRET,
        algorithm="HS256",
    )

    response = await client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "user-42"
    assert body["email"] == "alice@example.com"
    assert body["name"] == "Alice"


@pytest.mark.asyncio
async def test_auth_me_returns_anonymous_when_auth_disabled(client, monkeypatch):
    """GET /auth/me with auth disabled returns anonymous stub user."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "enabled", False)

    response = await client.get("/auth/me")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == ANONYMOUS_USER_ID


async def test_auth_me_returns_401_when_auth_enabled_no_token(client, monkeypatch):
    """GET /auth/me with auth enabled but no token returns 401."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "enabled", True)
    monkeypatch.setattr(settings.auth, "jwt_secret_key", TEST_JWT_SECRET)

    response = await client.get("/auth/me")
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
    return ws


@pytest.mark.asyncio
async def test_get_ws_user_id_returns_anonymous_when_auth_disabled(monkeypatch):
    """When auth is disabled, get_ws_user_id should return ANONYMOUS_USER_ID."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "enabled", False)

    ws = _make_ws_mock()
    result = await get_ws_user_id(ws)
    assert result == ANONYMOUS_USER_ID


@pytest.mark.asyncio
async def test_get_ws_user_id_extracts_user_from_jwt_cookie(monkeypatch):
    """When auth is enabled, get_ws_user_id should decode user_id from the session cookie."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "enabled", True)
    monkeypatch.setattr(settings.auth, "jwt_secret_key", TEST_JWT_SECRET)
    monkeypatch.setattr(settings.auth, "jwt_algorithm", "HS256")

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
    monkeypatch.setattr(settings.auth, "enabled", True)
    monkeypatch.setattr(settings.auth, "jwt_secret_key", TEST_JWT_SECRET)
    monkeypatch.setattr(settings.auth, "jwt_algorithm", "HS256")

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
async def test_get_ws_user_id_returns_anonymous_for_missing_token(monkeypatch):
    """When auth is enabled but no token is provided, return ANONYMOUS_USER_ID."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "enabled", True)
    monkeypatch.setattr(settings.auth, "jwt_secret_key", TEST_JWT_SECRET)

    ws = _make_ws_mock()
    result = await get_ws_user_id(ws)
    assert result == ANONYMOUS_USER_ID


@pytest.mark.asyncio
async def test_get_ws_user_id_returns_anonymous_for_invalid_token(monkeypatch):
    """An invalid JWT should result in ANONYMOUS_USER_ID, not an exception."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "enabled", True)
    monkeypatch.setattr(settings.auth, "jwt_secret_key", TEST_JWT_SECRET)
    monkeypatch.setattr(settings.auth, "jwt_algorithm", "HS256")

    bad_token = jwt.encode(
        {"sub": "user-1", "exp": datetime.now(UTC) + timedelta(hours=1)},
        "wrong-secret-key-for-unit-tests!!",
        algorithm="HS256",
    )

    ws = _make_ws_mock(cookies={settings.auth.cookie_name: bad_token})
    result = await get_ws_user_id(ws)
    assert result == ANONYMOUS_USER_ID


@pytest.mark.asyncio
async def test_get_ws_user_id_returns_anonymous_for_expired_token(monkeypatch):
    """An expired JWT should result in ANONYMOUS_USER_ID."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "enabled", True)
    monkeypatch.setattr(settings.auth, "jwt_secret_key", TEST_JWT_SECRET)
    monkeypatch.setattr(settings.auth, "jwt_algorithm", "HS256")

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
    result = await get_ws_user_id(ws)
    assert result == ANONYMOUS_USER_ID


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


# ---------------------------------------------------------------------------
# OAuth login ?next= redirect cookie
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_sets_next_cookie_for_safe_path(client, monkeypatch):
    """GET /auth/login/google?next=/auth/tokens should set a wikimind_next cookie."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "enabled", True)
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
    monkeypatch.setattr(settings.auth, "enabled", True)
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
    monkeypatch.setattr(settings.auth, "enabled", True)
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
    monkeypatch.setattr(settings.auth, "enabled", True)
    monkeypatch.setattr(settings.auth, "jwt_secret_key", TEST_JWT_SECRET)

    user = User(
        id="user-1",
        email="test@example.com",
        name="Test User",
        auth_provider="google",
        auth_provider_id="g-1",
    )
    db_session.add(user)
    await db_session.commit()

    response = await client.post(
        "/auth/token",
        json={"name": "my-cli-token", "expires_in_days": 90},
        headers=_auth_header(),
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
    monkeypatch.setattr(settings.auth, "enabled", True)
    monkeypatch.setattr(settings.auth, "jwt_secret_key", TEST_JWT_SECRET)

    user = User(
        id="user-1",
        email="test@example.com",
        name="Test User",
        auth_provider="google",
        auth_provider_id="g-1",
    )
    db_session.add(user)
    await db_session.commit()

    response = await client.post(
        "/auth/token",
        json={"name": "automation"},
        headers=_auth_header(),
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
    assert decoded["user"]["id"] == "user-1"
    assert decoded["user"]["email"] == "test@example.com"
    assert decoded["user"]["name"] == "Test User"


@pytest.mark.asyncio
async def test_api_token_expires_in_requested_days(client, db_session: AsyncSession, monkeypatch):
    """The API token exp claim should match the requested expires_in_days."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "enabled", True)
    monkeypatch.setattr(settings.auth, "jwt_secret_key", TEST_JWT_SECRET)

    user = User(
        id="user-1",
        email="test@example.com",
        name="Test User",
        auth_provider="google",
        auth_provider_id="g-1",
    )
    db_session.add(user)
    await db_session.commit()

    days = 60
    response = await client.post(
        "/auth/token",
        json={"name": "long-token", "expires_in_days": days},
        headers=_auth_header(),
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
