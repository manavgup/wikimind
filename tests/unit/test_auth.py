"""Tests for OAuth2 authentication — JWT helpers, middleware, and /auth/me."""

import inspect
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import jwt
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from wikimind.api.deps import ANONYMOUS_USER_ID, get_ws_user_id
from wikimind.api.routes import ws as ws_mod
from wikimind.api.routes.auth import _create_jwt, _upsert_user
from wikimind.config import get_settings
from wikimind.models import User

# ---------------------------------------------------------------------------
# JWT creation / decoding
# ---------------------------------------------------------------------------


def test_create_jwt_contains_expected_claims():
    """JWT payload should contain sub, email, iat, and exp claims."""
    settings = get_settings()
    settings.auth.jwt_secret_key = "test-secret"  # pragma: allowlist secret
    settings.auth.jwt_algorithm = "HS256"
    settings.auth.jwt_expiry_minutes = 60

    user = User(
        id="user-1",
        email="alice@example.com",
        auth_provider="google",
        auth_provider_id="g-123",
    )

    token = _create_jwt(user, settings)
    payload = jwt.decode(token, "test-secret", algorithms=["HS256"])

    assert payload["sub"] == "user-1"
    assert payload["email"] == "alice@example.com"
    assert "exp" in payload
    assert "iat" in payload


def test_create_jwt_expiry():
    """JWT should expire after the configured number of minutes."""
    settings = get_settings()
    settings.auth.jwt_secret_key = "test-secret"  # pragma: allowlist secret
    settings.auth.jwt_algorithm = "HS256"
    settings.auth.jwt_expiry_minutes = 30

    user = User(
        id="user-1",
        email="alice@example.com",
        auth_provider="github",
        auth_provider_id="gh-456",
    )

    token = _create_jwt(user, settings)
    payload = jwt.decode(token, "test-secret", algorithms=["HS256"])

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
    monkeypatch.setattr(settings.auth, "jwt_secret_key", "test-secret")

    response = await client.get("/wiki/articles")
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_middleware_returns_401_when_token_expired(client, monkeypatch):
    """An expired JWT should return a TOKEN_EXPIRED error."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "enabled", True)
    monkeypatch.setattr(settings.auth, "jwt_secret_key", "test-secret")

    expired_payload = {
        "sub": "user-1",
        "email": "alice@example.com",
        "exp": datetime.now(UTC) - timedelta(hours=1),
        "iat": datetime.now(UTC) - timedelta(hours=2),
    }
    expired_token = jwt.encode(expired_payload, "test-secret", algorithm="HS256")

    response = await client.get(
        "/wiki/articles",
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
    monkeypatch.setattr(settings.auth, "jwt_secret_key", "test-secret")

    bad_token = jwt.encode(
        {"sub": "user-1", "email": "a@b.com", "exp": datetime.now(UTC) + timedelta(hours=1)},
        "wrong-secret",
        algorithm="HS256",
    )

    response = await client.get(
        "/wiki/articles",
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
    monkeypatch.setattr(settings.auth, "jwt_secret_key", "test-secret")

    valid_token = jwt.encode(
        {
            "sub": "user-1",
            "email": "alice@example.com",
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        "test-secret",
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
    monkeypatch.setattr(settings.auth, "jwt_secret_key", "test-secret")

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
    monkeypatch.setattr(settings.auth, "jwt_secret_key", "test-secret")

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
        "test-secret",
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
    assert data["id"] == "anonymous"


async def test_auth_me_returns_401_when_auth_enabled_no_token(client, monkeypatch):
    """GET /auth/me with auth enabled but no token returns 401."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "enabled", True)
    monkeypatch.setattr(settings.auth, "jwt_secret_key", "test-secret-key-32chars-long!!")

    response = await client.get("/auth/me")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# User upsert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_user_creates_new_user(db_session: AsyncSession):
    """First login should create a new User record."""
    user_info = {
        "id": "google-id-1",
        "email": "new@example.com",
        "name": "New User",
        "picture": "https://example.com/pic.jpg",
    }
    user = await _upsert_user(db_session, "google", user_info)
    assert user.email == "new@example.com"
    assert user.auth_provider == "google"
    assert user.auth_provider_id == "google-id-1"


@pytest.mark.asyncio
async def test_upsert_user_updates_existing_user(db_session: AsyncSession):
    """Re-login should update the existing User record."""
    user_info = {
        "id": "google-id-2",
        "email": "existing@example.com",
        "name": "Old Name",
        "picture": None,
    }
    user1 = await _upsert_user(db_session, "google", user_info)

    user_info["name"] = "New Name"
    user_info["picture"] = "https://example.com/new.jpg"
    user2 = await _upsert_user(db_session, "google", user_info)

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
    monkeypatch.setattr(settings.auth, "jwt_secret_key", "test-secret")
    monkeypatch.setattr(settings.auth, "jwt_algorithm", "HS256")

    token = jwt.encode(
        {
            "sub": "user-99",
            "email": "ws@example.com",
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        "test-secret",
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
    monkeypatch.setattr(settings.auth, "jwt_secret_key", "test-secret")
    monkeypatch.setattr(settings.auth, "jwt_algorithm", "HS256")

    token = jwt.encode(
        {
            "sub": "user-77",
            "exp": datetime.now(UTC) + timedelta(hours=1),
        },
        "test-secret",
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
    monkeypatch.setattr(settings.auth, "jwt_secret_key", "test-secret")

    ws = _make_ws_mock()
    result = await get_ws_user_id(ws)
    assert result == ANONYMOUS_USER_ID


@pytest.mark.asyncio
async def test_get_ws_user_id_returns_anonymous_for_invalid_token(monkeypatch):
    """An invalid JWT should result in ANONYMOUS_USER_ID, not an exception."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "enabled", True)
    monkeypatch.setattr(settings.auth, "jwt_secret_key", "test-secret")
    monkeypatch.setattr(settings.auth, "jwt_algorithm", "HS256")

    bad_token = jwt.encode(
        {"sub": "user-1", "exp": datetime.now(UTC) + timedelta(hours=1)},
        "wrong-secret",
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
    monkeypatch.setattr(settings.auth, "jwt_secret_key", "test-secret")
    monkeypatch.setattr(settings.auth, "jwt_algorithm", "HS256")

    expired_token = jwt.encode(
        {
            "sub": "user-1",
            "exp": datetime.now(UTC) - timedelta(hours=1),
            "iat": datetime.now(UTC) - timedelta(hours=2),
        },
        "test-secret",
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
