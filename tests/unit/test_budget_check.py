"""Tests for LLMRouter budget check logic."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import TEST_USER_ID
from wikimind.config import get_runtime_config
from wikimind.engine import llm_router as llm_router_mod
from wikimind.engine.llm_router import LLMRouter


@pytest.fixture(autouse=True)
def _reset_runtime_config():
    """Reset RuntimeConfig overrides between tests."""
    rc = get_runtime_config()
    saved = rc._overrides.copy()
    yield
    rc._overrides.clear()
    rc._overrides.update(saved)


def _make_emitter():
    """Create a mock BudgetEventEmitter with trackable async methods."""
    emitter = MagicMock()
    emitter.emit_budget_warning = AsyncMock()
    emitter.emit_budget_exceeded = AsyncMock()
    return emitter


def _make_router(budget_usd=50.0, warning_pct=0.8, cache_seconds=60, emitter=None):
    llm_settings = SimpleNamespace(
        default_provider="anthropic",
        fallback_enabled=True,
        monthly_budget_usd=budget_usd,
        budget_warning_pct=warning_pct,
        budget_check_cache_seconds=cache_seconds,
        anthropic=SimpleNamespace(enabled=True, model="claude-sonnet-4-5"),
        openai=SimpleNamespace(enabled=False, model="gpt-4o-mini"),
        google=SimpleNamespace(enabled=False, model="gemini-2.0-flash"),
        ollama=SimpleNamespace(enabled=False, model="llama3"),
        mock=SimpleNamespace(enabled=False, model="mock-1"),
        ollama_base_url="http://localhost:11434",
        trace_enabled=False,
        trace_store_content=False,
    )
    settings = SimpleNamespace(llm=llm_settings)
    with patch.object(llm_router_mod, "get_settings", return_value=settings):
        router = LLMRouter(event_emitter=emitter)
    # Also set RuntimeConfig so _rc.get_monthly_budget_usd() returns the test value
    rc = get_runtime_config()
    rc._overrides["llm.monthly_budget_usd"] = budget_usd
    return router


def _mock_session_factory(spend: float):
    scalar_result = MagicMock()
    scalar_result.scalar = MagicMock(return_value=spend)
    session = MagicMock()
    session.execute = AsyncMock(return_value=scalar_result)
    # async context manager for the session scope: async with ctx as session
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    # session_factory() returns ctx  (the async context manager)
    session_factory = MagicMock(return_value=ctx)
    # get_session_factory() (with return_value=session_factory) means:
    #   calling the patched get_session_factory returns session_factory
    # In code: get_session_factory()() -> session_factory() -> ctx
    # async with ctx as session_var
    return session_factory


async def test_budget_warning_fires_at_threshold() -> None:
    emitter = _make_emitter()
    router = _make_router(budget_usd=100.0, warning_pct=0.8, emitter=emitter)
    factory = _mock_session_factory(spend=85.0)

    with patch.object(llm_router_mod, "get_session_factory", return_value=factory):
        await router._check_budget(user_id=TEST_USER_ID)

    emitter.emit_budget_warning.assert_awaited_once()
    emitter.emit_budget_exceeded.assert_not_awaited()
    assert TEST_USER_ID in router._budget_warning_sent
    assert TEST_USER_ID not in router._budget_exceeded_sent


async def test_budget_exceeded_fires_at_100pct() -> None:
    emitter = _make_emitter()
    router = _make_router(budget_usd=100.0, warning_pct=0.8, emitter=emitter)
    factory = _mock_session_factory(spend=110.0)

    with patch.object(llm_router_mod, "get_session_factory", return_value=factory):
        await router._check_budget(user_id=TEST_USER_ID)

    emitter.emit_budget_warning.assert_awaited_once()
    emitter.emit_budget_exceeded.assert_awaited_once()
    assert TEST_USER_ID in router._budget_warning_sent
    assert TEST_USER_ID in router._budget_exceeded_sent


async def test_warning_fires_only_once() -> None:
    emitter = _make_emitter()
    router = _make_router(budget_usd=100.0, warning_pct=0.8, emitter=emitter)
    factory = _mock_session_factory(spend=85.0)

    with patch.object(llm_router_mod, "get_session_factory", return_value=factory):
        await router._check_budget(user_id=TEST_USER_ID)
        # invalidate cache so second call re-queries
        router._cache_expires_at[TEST_USER_ID] = 0.0
        await router._check_budget(user_id=TEST_USER_ID)

    assert emitter.emit_budget_warning.await_count == 1


async def test_exceeded_fires_only_once() -> None:
    emitter = _make_emitter()
    router = _make_router(budget_usd=100.0, warning_pct=0.8, emitter=emitter)
    factory = _mock_session_factory(spend=110.0)

    with patch.object(llm_router_mod, "get_session_factory", return_value=factory):
        await router._check_budget(user_id=TEST_USER_ID)
        router._cache_expires_at[TEST_USER_ID] = 0.0
        await router._check_budget(user_id=TEST_USER_ID)

    assert emitter.emit_budget_exceeded.await_count == 1


async def test_cache_prevents_requery_within_ttl() -> None:
    emitter = _make_emitter()
    router = _make_router(budget_usd=100.0, warning_pct=0.8, cache_seconds=60, emitter=emitter)
    session_factory = _mock_session_factory(spend=85.0)
    # session_factory() -> ctx, ctx.__aenter__ -> session
    session = session_factory.return_value.__aenter__.return_value

    with patch.object(llm_router_mod, "get_session_factory", return_value=session_factory):
        await router._check_budget(user_id=TEST_USER_ID)
        first_call_count = session.execute.await_count
        # Reset warning flag so second call doesn't short-circuit at the top,
        # but cache is still valid so no DB query should happen.
        router._budget_warning_sent.pop(TEST_USER_ID, None)
        await router._check_budget(user_id=TEST_USER_ID)

    # session.execute should not have been called again
    assert session.execute.await_count == first_call_count


async def test_below_threshold_no_events() -> None:
    emitter = _make_emitter()
    router = _make_router(budget_usd=100.0, warning_pct=0.8, emitter=emitter)
    factory = _mock_session_factory(spend=50.0)

    with patch.object(llm_router_mod, "get_session_factory", return_value=factory):
        await router._check_budget(user_id=TEST_USER_ID)

    emitter.emit_budget_warning.assert_not_awaited()
    emitter.emit_budget_exceeded.assert_not_awaited()
    assert TEST_USER_ID not in router._budget_warning_sent
    assert TEST_USER_ID not in router._budget_exceeded_sent


async def test_both_flags_set_returns_early_without_query() -> None:
    router = _make_router()
    router._budget_warning_sent[TEST_USER_ID] = (2026, 4)
    router._budget_exceeded_sent[TEST_USER_ID] = (2026, 4)
    factory = _mock_session_factory(spend=999.0)

    with (
        patch.object(llm_router_mod, "get_session_factory", return_value=factory),
        patch.object(router, "_budget_flag_is_set", return_value=True),
    ):
        await router._check_budget(user_id=TEST_USER_ID)

    factory.assert_not_called()
