"""Tests for GET /settings/llm/cost/breakdown endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wikimind.api.routes import settings as settings_mod
from wikimind.models import Provider, TaskType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_session_factory(total: float, provider_rows: list, task_rows: list):
    """Return a mocked session_factory that returns pre-canned query results.

    Code pattern: async with get_session_factory()() as session:
    patch return_value=session_factory so get_session_factory() returns session_factory,
    then session_factory() returns ctx (async context manager), ctx.__aenter__ -> session.
    """
    call_count = 0

    async def _execute(stmt):
        nonlocal call_count
        result = MagicMock()
        if call_count == 0:
            result.scalar = MagicMock(return_value=total)
        elif call_count == 1:
            result.all = MagicMock(return_value=provider_rows)
        else:
            result.all = MagicMock(return_value=task_rows)
        call_count += 1
        return result

    session = MagicMock()
    session.execute = _execute
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    session_factory = MagicMock(return_value=ctx)
    return session_factory


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_empty_cost_log_returns_zeros(client) -> None:
    session_factory = _make_fake_session_factory(total=0.0, provider_rows=[], task_rows=[])
    with patch.object(settings_mod, "get_session_factory", return_value=session_factory):
        resp = await client.get("/settings/llm/cost/breakdown")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_usd"] == 0.0
    assert data["by_provider"] == {}
    assert data["by_task_type"] == {}
    assert data["budget_pct"] == 0.0


async def test_seeded_entries_group_by_provider(client) -> None:
    provider_rows = [
        (Provider.ANTHROPIC, 10.50, 42),
        (Provider.OPENAI, 2.00, 5),
    ]
    task_rows = [
        (TaskType.QA, 8.20, 30),
    ]
    session_factory = _make_fake_session_factory(total=12.50, provider_rows=provider_rows, task_rows=task_rows)
    with patch.object(settings_mod, "get_session_factory", return_value=session_factory):
        resp = await client.get("/settings/llm/cost/breakdown")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_usd"] == 12.50
    assert "anthropic" in data["by_provider"]
    assert data["by_provider"]["anthropic"]["cost_usd"] == pytest.approx(10.50)
    assert data["by_provider"]["anthropic"]["call_count"] == 42
    assert "openai" in data["by_provider"]


async def test_seeded_entries_group_by_task_type(client) -> None:
    provider_rows = [(Provider.ANTHROPIC, 8.20, 30)]
    task_rows = [
        (TaskType.QA, 5.00, 20),
        (TaskType.COMPILE, 3.20, 10),
    ]
    session_factory = _make_fake_session_factory(total=8.20, provider_rows=provider_rows, task_rows=task_rows)
    with patch.object(settings_mod, "get_session_factory", return_value=session_factory):
        resp = await client.get("/settings/llm/cost/breakdown")

    assert resp.status_code == 200
    data = resp.json()
    by_task = {k.lower(): v for k, v in data["by_task_type"].items()}
    assert "qa" in by_task
    assert by_task["qa"]["call_count"] == 20


async def test_budget_percentage_calculated_correctly(client) -> None:
    session_factory = _make_fake_session_factory(total=25.0, provider_rows=[], task_rows=[])
    with patch.object(settings_mod, "get_session_factory", return_value=session_factory):
        resp = await client.get("/settings/llm/cost/breakdown")

    assert resp.status_code == 200
    data = resp.json()
    budget = data["budget_usd"]
    expected_pct = round(25.0 / budget * 100, 1)
    assert data["budget_pct"] == pytest.approx(expected_pct, abs=0.1)
