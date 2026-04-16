"""Tests for UserPreference-backed runtime settings overrides.

Covers:
- POST /settings/llm/default-provider (valid, invalid, not-enabled)
- PATCH /settings (budget, fallback)
- GET /settings reflecting DB overrides
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wikimind.api.routes import settings as settings_mod
from wikimind.models import UserPreference

# ---------------------------------------------------------------------------
# Session-factory helpers
# ---------------------------------------------------------------------------


def _make_session_with_pref(pref: UserPreference | None):
    """Return a fake session_factory where session.get() returns *pref*.

    Pattern used by helpers:
        async with get_session_factory()() as session:
            pref = await session.get(UserPreference, key)
    """
    session = MagicMock()
    session.get = AsyncMock(return_value=pref)
    session.add = MagicMock()
    session.commit = AsyncMock()

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)

    session_factory = MagicMock(return_value=ctx)
    return session_factory, session


def _make_multi_call_session_factory(responses: list):
    """Return a fake session_factory whose session.get() cycles through *responses*.

    Each entry in *responses* is the return value for a successive .get() call.
    Used when multiple helper calls (each opening its own session) need different results.
    """
    call_index = 0

    async def _get(model, key):
        nonlocal call_index
        val = responses[call_index] if call_index < len(responses) else None
        call_index += 1
        return val

    session = MagicMock()
    session.get = _get
    session.add = MagicMock()
    session.commit = AsyncMock()

    # scalars().all() for _apply_db_preferences style queries — not used here
    scalars_result = MagicMock()
    scalars_result.all = MagicMock(return_value=[])
    execute_result = MagicMock()
    execute_result.scalars = MagicMock(return_value=scalars_result)
    session.execute = AsyncMock(return_value=execute_result)

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)

    session_factory = MagicMock(return_value=ctx)
    return session_factory


# ---------------------------------------------------------------------------
# POST /settings/llm/default-provider
# ---------------------------------------------------------------------------


async def test_set_default_provider_valid(client) -> None:
    """Setting a valid, enabled provider with an API key configured returns 200."""
    session_factory, _ = _make_session_with_pref(None)

    with (
        patch.object(settings_mod, "get_session_factory", return_value=session_factory),
        patch.object(settings_mod, "get_api_key", return_value="sk-fake"),
    ):
        resp = await client.post("/settings/llm/default-provider", json={"provider": "anthropic"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "anthropic"
    assert data["status"] == "ok"


async def test_set_default_provider_invalid(client) -> None:
    """Sending an unknown provider name returns 400."""
    resp = await client.post("/settings/llm/default-provider", json={"provider": "nonexistent"})
    assert resp.status_code == 400
    assert "Unknown provider" in resp.json()["detail"]


async def test_set_default_provider_not_enabled(client) -> None:
    """Requesting a known but disabled provider returns 400."""
    # mock provider is disabled by default (enabled=False in MockConfig)
    resp = await client.post("/settings/llm/default-provider", json={"provider": "mock"})
    assert resp.status_code == 400
    assert "not enabled" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# PATCH /settings
# ---------------------------------------------------------------------------


async def test_patch_budget(client) -> None:
    """Patching monthly_budget_usd persists the preference and returns ok."""
    session_factory, _ = _make_session_with_pref(None)

    with patch.object(settings_mod, "get_session_factory", return_value=session_factory):
        resp = await client.patch("/settings", json={"monthly_budget_usd": 99.5})

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_patch_budget_invalid(client) -> None:
    """A non-positive budget value returns 400."""
    resp = await client.patch("/settings", json={"monthly_budget_usd": -1.0})
    assert resp.status_code == 400
    assert "positive" in resp.json()["detail"]


async def test_patch_fallback(client) -> None:
    """Patching fallback_enabled=false persists the preference and returns ok."""
    session_factory, _ = _make_session_with_pref(None)

    with patch.object(settings_mod, "get_session_factory", return_value=session_factory):
        resp = await client.patch("/settings", json={"fallback_enabled": False})

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# GET /settings reflects DB overrides
# ---------------------------------------------------------------------------


async def test_get_settings_reflects_overrides(client) -> None:
    """GET /settings should return DB-overridden values when preferences exist."""
    budget_pref = UserPreference(key="llm.monthly_budget_usd", value="123.45")
    fallback_pref = UserPreference(key="llm.fallback_enabled", value="false")
    provider_pref = UserPreference(key="llm.default_provider", value="anthropic")

    # _get_preference is called three times (default_provider, budget, fallback)
    session_factory = _make_multi_call_session_factory([provider_pref, budget_pref, fallback_pref])

    with patch.object(settings_mod, "get_session_factory", return_value=session_factory):
        resp = await client.get("/settings")

    assert resp.status_code == 200
    data = resp.json()
    assert data["llm"]["monthly_budget_usd"] == pytest.approx(123.45)
    assert data["llm"]["fallback_enabled"] is False
    assert data["llm"]["default_provider"] == "anthropic"
