"""Tests for the CLI token generator — verifies it uses user UUID from DB."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import jwt
import pytest

from tests.conftest import TEST_JWT_SECRET
from wikimind.cli.create_token import _lookup_user_by_email, main
from wikimind.models import User


class _FakeSessionCtx:
    """Async context manager that yields a test db_session."""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *args):
        pass


def _mock_engine_begin():
    """Return a mock engine whose begin() skips create_all."""
    mock_engine = AsyncMock()
    mock_conn = AsyncMock()
    mock_begin = AsyncMock()
    mock_begin.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_begin.__aexit__ = AsyncMock(return_value=False)
    mock_engine.begin = lambda: mock_begin
    return mock_engine


@pytest.mark.asyncio
async def test_lookup_user_by_email_returns_uuid(db_session):
    """_lookup_user_by_email should return the user's UUID, not the email."""
    user = User(
        id="uuid-abc-123",
        email="alice@example.com",
        name="Alice",
        auth_provider="google",
        auth_provider_id="g-1",
    )
    db_session.add(user)
    await db_session.commit()

    with (
        patch(
            "wikimind.database.get_async_engine",
            return_value=_mock_engine_begin(),
        ),
        patch(
            "wikimind.database.get_session_factory",
            return_value=lambda: _FakeSessionCtx(db_session),
        ),
    ):
        user_id, user_name = await _lookup_user_by_email("alice@example.com")

    assert user_id == "uuid-abc-123"
    assert user_name == "Alice"


@pytest.mark.asyncio
async def test_lookup_user_by_email_exits_when_not_found(db_session):
    """_lookup_user_by_email should sys.exit(1) when no user matches."""
    with (
        patch(
            "wikimind.database.get_async_engine",
            return_value=_mock_engine_begin(),
        ),
        patch(
            "wikimind.database.get_session_factory",
            return_value=lambda: _FakeSessionCtx(db_session),
        ),
        pytest.raises(SystemExit) as exc_info,
    ):
        await _lookup_user_by_email("nobody@example.com")

    assert exc_info.value.code == 1


def test_main_generates_token_with_user_uuid(monkeypatch):
    """main() should produce a JWT whose sub claim is the user's UUID, not the email."""
    monkeypatch.setattr(
        "sys.argv",
        ["create_token", "--email", "alice@example.com", "--secret", TEST_JWT_SECRET],
    )

    # Patch _lookup_user_by_email to return a known UUID
    async def _fake_lookup(email):
        return ("uuid-abc-123", "Alice")

    monkeypatch.setattr("wikimind.cli.create_token._lookup_user_by_email", _fake_lookup)

    # Capture the printed token (stdout only, not stderr)
    captured = {}
    original_print = print

    def _capture_print(text, **kwargs):
        file = kwargs.get("file")
        if file is None:
            captured["token"] = text
        else:
            original_print(text, **kwargs)

    monkeypatch.setattr("builtins.print", _capture_print)

    main()

    token = captured["token"]
    decoded = jwt.decode(token, TEST_JWT_SECRET, algorithms=["HS256"], options={"verify_aud": False})

    # The critical fix: sub must be the UUID, not the email
    assert decoded["sub"] == "uuid-abc-123"
    assert decoded["user"]["id"] == "uuid-abc-123"
    assert decoded["user"]["email"] == "alice@example.com"
    assert decoded["user"]["name"] == "Alice"
    assert decoded["iss"] == "wikimind"
    assert decoded["aud"] == "wikimind-api"
    assert decoded["token_use"] == "api"


def test_main_uses_custom_token_name(monkeypatch):
    """When --name is provided, the token should use it instead of the DB name."""
    monkeypatch.setattr(
        "sys.argv",
        [
            "create_token",
            "--email",
            "alice@example.com",
            "--secret",
            TEST_JWT_SECRET,
            "--name",
            "my-custom-name",
        ],
    )

    async def _fake_lookup(email):
        return ("uuid-abc-123", "Alice")

    monkeypatch.setattr("wikimind.cli.create_token._lookup_user_by_email", _fake_lookup)

    captured = {}
    original_print = print

    def _capture_print(text, **kwargs):
        if kwargs.get("file") is None:
            captured["token"] = text
        else:
            original_print(text, **kwargs)

    monkeypatch.setattr("builtins.print", _capture_print)

    main()

    decoded = jwt.decode(captured["token"], TEST_JWT_SECRET, algorithms=["HS256"], options={"verify_aud": False})
    assert decoded["user"]["name"] == "my-custom-name"
