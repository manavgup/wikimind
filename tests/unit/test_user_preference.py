"""Tests for UserPreference-backed runtime settings overrides.

Covers:
- POST /settings/llm/default-provider (valid, invalid, not-enabled)
- PATCH /settings (budget, fallback)
- GET /settings reflecting DB overrides
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wikimind.api.routes import settings as settings_mod

if TYPE_CHECKING:
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

    settings = settings_mod.get_settings()
    original_enabled = settings.llm.anthropic.enabled
    settings.llm.anthropic.enabled = True
    try:
        with (
            patch.object(settings_mod, "get_session_factory", return_value=session_factory),
            patch.object(settings_mod, "get_api_key", return_value="sk-fake"),
        ):
            resp = await client.post("/api/settings/llm/default-provider", json={"provider": "anthropic"})
    finally:
        settings.llm.anthropic.enabled = original_enabled

    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "anthropic"
    assert data["status"] == "ok"


async def test_set_default_provider_invalid(client) -> None:
    """Sending an unknown provider name returns 400."""
    resp = await client.post("/api/settings/llm/default-provider", json={"provider": "nonexistent"})
    assert resp.status_code == 400
    assert "Unknown provider" in resp.json()["error"]["message"]


async def test_set_default_provider_not_enabled(client) -> None:
    """Requesting a known but disabled provider returns 400."""
    # mock provider is disabled by default (enabled=False in MockConfig)
    resp = await client.post("/api/settings/llm/default-provider", json={"provider": "mock"})
    assert resp.status_code == 400
    assert "not enabled" in resp.json()["error"]["message"]


# ---------------------------------------------------------------------------
# PATCH /settings
# ---------------------------------------------------------------------------


async def test_patch_budget(client) -> None:
    """Patching monthly_budget_usd persists the preference and returns ok."""
    session_factory, _ = _make_session_with_pref(None)

    with patch.object(settings_mod, "get_session_factory", return_value=session_factory):
        resp = await client.patch("/api/settings", json={"monthly_budget_usd": 99.5})

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_patch_budget_invalid(client) -> None:
    """A non-positive budget value returns 400."""
    resp = await client.patch("/api/settings", json={"monthly_budget_usd": -1.0})
    assert resp.status_code == 400
    assert "positive" in resp.json()["error"]["message"]


async def test_patch_fallback(client) -> None:
    """Patching fallback_enabled=false persists the preference and returns ok."""
    session_factory, _ = _make_session_with_pref(None)

    with patch.object(settings_mod, "get_session_factory", return_value=session_factory):
        resp = await client.patch("/api/settings", json={"fallback_enabled": False})

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_patch_openai_compatible_runtime_config(client) -> None:
    """Patching OpenAI-compatible endpoint config updates RuntimeConfig (not Settings)."""
    from wikimind.config import get_runtime_config

    session_factory, _ = _make_session_with_pref(None)
    rc = get_runtime_config()
    with patch.object(settings_mod, "get_session_factory", return_value=session_factory):
        resp = await client.patch(
            "/api/settings",
            json={
                "openai_compatible_base_url": "https://openrouter.ai/api/v1/",
                "openai_compatible_model": "openai/gpt-4o-mini",
                "openai_compatible_supports_reasoning_effort": True,
                "openai_compatible_reasoning_format": "openrouter",
            },
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert rc.get_openai_compatible_base_url() == "https://openrouter.ai/api/v1"
    assert rc.get_openai_compatible_model() == "openai/gpt-4o-mini"
    assert rc.get_openai_compatible_field("supports_reasoning_effort") is True
    assert rc.get_openai_compatible_field("reasoning_format") == "openrouter"


async def test_patch_openai_compatible_rejects_invalid_base_url(client) -> None:
    """OpenAI-compatible base URLs must be absolute HTTP(S) URLs."""
    resp = await client.patch("/api/settings", json={"openai_compatible_base_url": "openrouter.ai/api/v1"})
    assert resp.status_code == 400
    assert "base URL" in resp.json()["error"]["message"]


@pytest.mark.parametrize(
    "payload",
    [
        {"openai_compatible_base_url": "https://attacker.example/v1"},
        {"openai_compatible_model": "attacker/model"},
        {"openai_compatible_supports_json_response_format": False},
        {"openai_compatible_supports_stream_usage": False},
        {"openai_compatible_supports_reasoning_effort": True},
        {"openai_compatible_max_tokens_field": "max_completion_tokens"},
        {"openai_compatible_reasoning_format": "openrouter"},
    ],
)
async def test_patch_openai_compatible_runtime_config_rejected_when_auth_enabled(
    client,
    monkeypatch,
    payload,
) -> None:
    """In production (non-dev mode), users cannot change global runtime config."""
    from fastapi import HTTPException

    from wikimind.api.routes.settings import SettingsUpdateRequest, _update_openai_compatible_settings

    settings = settings_mod.get_settings()
    # Temporarily override is_dev to False to simulate production
    original_env = settings.env
    settings.env = "production"
    try:
        request = SettingsUpdateRequest(**payload)
        with pytest.raises(HTTPException) as exc_info:
            await _update_openai_compatible_settings(request, "user-1")
        assert exc_info.value.status_code == 403
        assert "runtime settings are global" in exc_info.value.detail
    finally:
        settings.env = original_env


async def test_patch_openai_compatible_rejects_invalid_reasoning_format(client) -> None:
    """OpenAI-compatible reasoning format must be one of the supported payload styles."""
    resp = await client.patch("/api/settings", json={"openai_compatible_reasoning_format": "custom"})
    assert resp.status_code == 400
    assert "reasoning format" in resp.json()["error"]["message"]


# ---------------------------------------------------------------------------
# GET /settings reflects DB overrides
# ---------------------------------------------------------------------------


async def test_get_settings_reflects_overrides(client) -> None:
    """GET /settings should return RuntimeConfig-overridden values."""
    from wikimind.config import get_runtime_config

    rc = get_runtime_config()
    # Save originals
    orig_budget = rc.get("llm.monthly_budget_usd")
    orig_fallback = rc.get("llm.fallback_enabled")
    orig_provider = rc.get("llm.default_provider")

    rc.set("llm.monthly_budget_usd", 123.45)
    rc.set("llm.fallback_enabled", False)
    rc.set("llm.default_provider", "anthropic")
    try:
        resp = await client.get("/api/settings")
    finally:
        # Restore originals
        if orig_budget is not None:
            rc.set("llm.monthly_budget_usd", orig_budget)
        if orig_fallback is not None:
            rc.set("llm.fallback_enabled", orig_fallback)
        if orig_provider is not None:
            rc.set("llm.default_provider", orig_provider)

    assert resp.status_code == 200
    data = resp.json()
    assert data["llm"]["monthly_budget_usd"] == pytest.approx(123.45)
    assert data["llm"]["fallback_enabled"] is False
    assert data["llm"]["default_provider"] == "anthropic"
