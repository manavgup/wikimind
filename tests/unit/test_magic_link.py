"""Tests for magic link (passwordless email) login flow."""

import base64
import hashlib
import hmac
import time
from unittest.mock import patch

import jwt
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from wikimind.config import get_settings
from wikimind.models import User
from wikimind.services.user import UserService

_service = UserService()


# ---------------------------------------------------------------------------
# POST /auth/magic-link — request a magic link
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_magic_link_returns_ok(client):
    """POST /auth/magic-link should return 200 with a consistent message."""
    response = await client.post(
        "/auth/magic-link",
        json={"email": "test@example.com"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "login link" in body["message"]
    assert body["dev_token"] is not None


@pytest.mark.asyncio
async def test_request_magic_link_disabled(client, monkeypatch):
    """POST /auth/magic-link should return 400 when magic link is disabled."""
    settings = get_settings()
    monkeypatch.setattr(settings.auth, "magic_link_enabled", False)

    response = await client.post(
        "/auth/magic-link",
        json={"email": "test@example.com"},
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# POST /auth/magic-link/verify — verify token and get session JWT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_magic_link_verify_creates_session(client):
    """Verifying a valid token should return an access_token and user info."""
    settings = get_settings()
    settings.auth.jwt_secret_key = "test-secret"  # pragma: allowlist secret

    # Request a magic link
    response = await client.post(
        "/auth/magic-link",
        json={"email": "alice@example.com"},
    )
    token = response.json()["dev_token"]

    # Verify the token
    response = await client.post(
        "/auth/magic-link/verify",
        json={"token": token},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["email"] == "alice@example.com"

    # The returned JWT should be valid
    payload = jwt.decode(
        body["access_token"],
        settings.auth.jwt_secret_key,
        algorithms=[settings.auth.jwt_algorithm],
    )
    assert payload["email"] == "alice@example.com"
    assert payload["sub"] == body["user"]["id"]


@pytest.mark.asyncio
async def test_magic_link_verify_rejects_expired_token(client, monkeypatch):
    """An expired magic link token should be rejected with 401."""
    settings = get_settings()
    settings.auth.jwt_secret_key = "test-secret"  # pragma: allowlist secret
    settings.auth.magic_link_ttl_seconds = 600

    # Create a token with a timestamp in the past
    email = "expired@example.com"
    old_timestamp = str(int(time.time()) - 700)  # 700 seconds ago, TTL is 600
    payload = f"{email}:{old_timestamp}"
    signature = hmac.new(
        settings.auth.jwt_secret_key.encode(),
        payload.encode(),
        hashlib.sha256,
    ).digest()
    token_bytes = f"{payload}:{base64.urlsafe_b64encode(signature).decode()}".encode()
    expired_token = base64.urlsafe_b64encode(token_bytes).decode()

    response = await client.post(
        "/auth/magic-link/verify",
        json={"token": expired_token},
    )
    assert response.status_code == 401
    assert "expired" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_magic_link_verify_rejects_tampered_token(client):
    """A tampered magic link token should be rejected with 401."""
    settings = get_settings()
    settings.auth.jwt_secret_key = "test-secret"  # pragma: allowlist secret

    # Create a valid token, then tamper with it
    email = "tamper@example.com"
    timestamp = str(int(time.time()))
    payload = f"{email}:{timestamp}"
    # Sign with a different key
    wrong_sig = hmac.new(
        b"wrong-secret",
        payload.encode(),
        hashlib.sha256,
    ).digest()
    token_bytes = f"{payload}:{base64.urlsafe_b64encode(wrong_sig).decode()}".encode()
    tampered_token = base64.urlsafe_b64encode(token_bytes).decode()

    response = await client.post(
        "/auth/magic-link/verify",
        json={"token": tampered_token},
    )
    assert response.status_code == 401
    assert "signature" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_magic_link_verify_creates_user_if_not_exists(client, db_session: AsyncSession):
    """Verifying a magic link for a new email should auto-create the user."""
    settings = get_settings()
    settings.auth.jwt_secret_key = "test-secret"  # pragma: allowlist secret

    # Request and verify a magic link for a new user
    response = await client.post(
        "/auth/magic-link",
        json={"email": "newuser@example.com"},
    )
    token = response.json()["dev_token"]

    response = await client.post(
        "/auth/magic-link/verify",
        json={"token": token},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == "newuser@example.com"
    # Name should default to the part before @ for new users
    assert body["user"]["name"] == "newuser"


@pytest.mark.asyncio
async def test_magic_link_verify_rejects_garbage_token(client):
    """A completely invalid token should be rejected with 401."""
    response = await client.post(
        "/auth/magic-link/verify",
        json={"token": "not-a-valid-token!!!"},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# UserService — unit tests for token creation/verification
# ---------------------------------------------------------------------------


def test_create_and_verify_magic_link_token():
    """Round-trip: create a token and verify it returns the email."""
    settings = get_settings()
    settings.auth.jwt_secret_key = "test-secret"  # pragma: allowlist secret
    settings.auth.magic_link_ttl_seconds = 600

    token = _service.create_magic_link_token("round@trip.com", settings)
    email = _service.verify_magic_link_token(token, settings)
    assert email == "round@trip.com"


def test_verify_magic_link_token_expired():
    """Expired tokens should raise ValueError."""
    settings = get_settings()
    settings.auth.jwt_secret_key = "test-secret"  # pragma: allowlist secret
    settings.auth.magic_link_ttl_seconds = 1  # 1 second TTL

    token = _service.create_magic_link_token("exp@test.com", settings)

    with patch("wikimind.services.user.time") as mock_time:
        # Simulate time passing beyond TTL
        mock_time.time.return_value = time.time() + 10
        with pytest.raises(ValueError, match="expired"):
            _service.verify_magic_link_token(token, settings)


def test_verify_magic_link_token_tampered():
    """Tampered tokens should raise ValueError."""
    settings = get_settings()
    settings.auth.jwt_secret_key = "test-secret"  # pragma: allowlist secret

    token = _service.create_magic_link_token("ok@test.com", settings)

    # Tamper with the token by changing a character
    decoded = base64.urlsafe_b64decode(token.encode()).decode()
    tampered = decoded.replace("ok@test.com", "evil@test.com")
    bad_token = base64.urlsafe_b64encode(tampered.encode()).decode()

    with pytest.raises(ValueError, match="signature"):
        _service.verify_magic_link_token(bad_token, settings)


@pytest.mark.asyncio
async def test_get_or_create_by_email_creates_new(db_session: AsyncSession):
    """get_or_create_by_email should create a new user if email not found."""
    user = await _service.get_or_create_by_email(db_session, "brand-new@example.com")
    assert user.email == "brand-new@example.com"
    assert user.auth_provider == "magic_link"
    assert user.name == "brand-new"


@pytest.mark.asyncio
async def test_get_or_create_by_email_returns_existing(db_session: AsyncSession):
    """get_or_create_by_email should return existing user if email matches."""
    existing = User(
        email="existing@example.com",
        name="Existing User",
        auth_provider="google",
        auth_provider_id="g-123",
    )
    db_session.add(existing)
    await db_session.commit()
    await db_session.refresh(existing)

    user = await _service.get_or_create_by_email(db_session, "existing@example.com")
    assert user.id == existing.id
    assert user.name == "Existing User"
    assert user.auth_provider == "google"  # Should not overwrite provider
