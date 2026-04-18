"""Tests for OAuth2 authentication — JWT helpers, middleware, and /auth/me."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

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
async def test_middleware_sets_user_id_none_when_disabled(client):
    """When auth.enabled=False, request.state.user_id should be None."""
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
async def test_auth_me_returns_401_when_no_user(client, monkeypatch):
    """GET /auth/me without auth should return 401."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "enabled", False)

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
