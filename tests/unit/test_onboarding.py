"""Tests for onboarding status endpoints.

Covers:
- GET /settings/onboarding-status (default, after completion)
- POST /settings/onboarding-status (mark complete)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from wikimind.api.routes import settings as settings_mod
from wikimind.models import UserPreference


def _make_session_with_pref(pref: UserPreference | None):
    """Return a fake session_factory where session.get() returns *pref*."""
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
    """Return a fake session_factory whose session.get() cycles through *responses*."""
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

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)

    session_factory = MagicMock(return_value=ctx)
    return session_factory


# ---------------------------------------------------------------------------
# GET /settings/onboarding-status
# ---------------------------------------------------------------------------


async def test_onboarding_status_default(client) -> None:
    """Default onboarding status is not completed, step 0."""
    session_factory = _make_multi_call_session_factory([None, None])

    with patch.object(settings_mod, "get_session_factory", return_value=session_factory):
        resp = await client.get("/settings/onboarding-status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["completed"] is False
    assert data["step"] == 0


async def test_onboarding_status_completed(client) -> None:
    """Returns completed=True when onboarding has been marked complete."""
    completed_pref = UserPreference(key="onboarding.completed", value="true")
    step_pref = UserPreference(key="onboarding.step", value="5")
    session_factory = _make_multi_call_session_factory([completed_pref, step_pref])

    with patch.object(settings_mod, "get_session_factory", return_value=session_factory):
        resp = await client.get("/settings/onboarding-status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["completed"] is True
    assert data["step"] == 5


# ---------------------------------------------------------------------------
# POST /settings/onboarding-status
# ---------------------------------------------------------------------------


async def test_complete_onboarding(client) -> None:
    """POST marks onboarding as complete and returns updated status."""
    session_factory, _session = _make_session_with_pref(None)

    with patch.object(settings_mod, "get_session_factory", return_value=session_factory):
        resp = await client.post("/settings/onboarding-status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["completed"] is True
    assert data["step"] == 5
