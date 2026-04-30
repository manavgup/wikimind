"""Tests for horizontal scaling (multi-replica) features.

Covers Redis Pub/Sub WebSocket broadcast, budget flag dedup, and
BackgroundCompiler safety verification.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from wikimind.api.routes import ws as ws_mod
from wikimind.api.routes.ws import ConnectionManager, _publish_to_redis
from wikimind.engine import llm_router as llm_router_mod
from wikimind.engine.llm_router import LLMRouter

# ---------------------------------------------------------------------------
# WebSocket ConnectionManager — Redis Pub/Sub
# ---------------------------------------------------------------------------


class TestConnectionManagerLocalBroadcast:
    """Test _local_broadcast delivers to local connections only."""

    async def test_local_broadcast_delivers_to_matching_user(self) -> None:
        mgr = ConnectionManager()
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_text = AsyncMock()
        await mgr.connect(ws, user_id="user-1")

        await mgr._local_broadcast({"event": "test"}, user_id="user-1")

        ws.send_text.assert_awaited_once()
        payload = json.loads(ws.send_text.call_args[0][0])
        assert payload["event"] == "test"

    async def test_local_broadcast_skips_other_users(self) -> None:
        mgr = ConnectionManager()
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_text = AsyncMock()
        await mgr.connect(ws, user_id="user-1")

        await mgr._local_broadcast({"event": "test"}, user_id="user-2")

        ws.send_text.assert_not_awaited()

    async def test_local_broadcast_none_user_reaches_all(self) -> None:
        mgr = ConnectionManager()
        ws1 = MagicMock()
        ws1.accept = AsyncMock()
        ws1.send_text = AsyncMock()
        ws2 = MagicMock()
        ws2.accept = AsyncMock()
        ws2.send_text = AsyncMock()
        await mgr.connect(ws1, user_id="user-1")
        await mgr.connect(ws2, user_id="user-2")

        await mgr._local_broadcast({"event": "all"}, user_id=None)

        ws1.send_text.assert_awaited_once()
        ws2.send_text.assert_awaited_once()


class TestBroadcastWithRedis:
    """Test that broadcast(user_id="test-user") publishes to Redis when available."""

    async def test_broadcast_publishes_to_redis(self) -> None:
        mgr = ConnectionManager()
        mock_redis = AsyncMock()
        mock_redis.publish = AsyncMock(return_value=1)

        with patch.object(ws_mod, "_get_redis", return_value=mock_redis):
            await mgr.broadcast({"event": "test"}, user_id="u1")

        mock_redis.publish.assert_awaited_once()
        call_args = mock_redis.publish.call_args
        assert call_args[0][0] == "wikimind:ws:broadcast"
        payload = json.loads(call_args[0][1])
        assert payload["event"]["event"] == "test"
        assert payload["user_id"] == "u1"

    async def test_broadcast_falls_back_to_local_without_redis(self) -> None:
        mgr = ConnectionManager()
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.send_text = AsyncMock()
        await mgr.connect(ws, user_id="user-1")

        with patch.object(ws_mod, "_get_redis", return_value=None):
            await mgr.broadcast({"event": "fallback"}, user_id="user-1")

        ws.send_text.assert_awaited_once()
        payload = json.loads(ws.send_text.call_args[0][0])
        assert payload["event"] == "fallback"


class TestPublishToRedis:
    """Test _publish_to_redis helper."""

    async def test_returns_true_on_success(self) -> None:
        mock_redis = AsyncMock()
        mock_redis.publish = AsyncMock(return_value=1)

        with patch.object(ws_mod, "_get_redis", return_value=mock_redis):
            result = await _publish_to_redis({"event": "test"}, "u1")

        assert result is True

    async def test_returns_false_when_no_redis(self) -> None:
        with patch.object(ws_mod, "_get_redis", return_value=None):
            result = await _publish_to_redis({"event": "test"}, "u1")

        assert result is False

    async def test_returns_false_on_publish_error(self) -> None:
        mock_redis = AsyncMock()
        mock_redis.publish = AsyncMock(side_effect=ConnectionError("gone"))

        with patch.object(ws_mod, "_get_redis", return_value=mock_redis):
            result = await _publish_to_redis({"event": "test"}, "u1")

        assert result is False


# ---------------------------------------------------------------------------
# Budget flag dedup — Redis-backed
# ---------------------------------------------------------------------------


def _make_router(budget_usd=50.0, warning_pct=0.8, cache_seconds=60):
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
    )
    settings = SimpleNamespace(llm=llm_settings)
    with patch.object(llm_router_mod, "get_settings", return_value=settings):
        return LLMRouter()


def _mock_session_factory(spend: float):
    scalar_result = MagicMock()
    scalar_result.scalar = MagicMock(return_value=spend)
    session = MagicMock()
    session.execute = AsyncMock(return_value=scalar_result)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    session_factory = MagicMock(return_value=ctx)
    return session_factory


class TestBudgetFlagRedisDedup:
    """Test that budget flags use Redis for cross-replica dedup."""

    async def test_set_budget_flag_writes_to_redis(self) -> None:
        router = _make_router()
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()

        with patch.object(llm_router_mod, "_get_budget_redis", return_value=mock_redis):
            await router._set_budget_flag("_budget_warning_sent", (2026, 4))

        mock_redis.set.assert_awaited_once()
        call_args = mock_redis.set.call_args
        assert "2026:4" in call_args[0][0]
        assert call_args[1]["ex"] == 35 * 86400

    async def test_budget_flag_is_set_checks_redis(self) -> None:
        router = _make_router()
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=1)

        with patch.object(llm_router_mod, "_get_budget_redis", return_value=mock_redis):
            result = await router._budget_flag_is_set("_budget_warning_sent", (2026, 4))

        assert result is True
        mock_redis.exists.assert_awaited_once()

    async def test_budget_flag_falls_back_to_local(self) -> None:
        router = _make_router()

        with patch.object(llm_router_mod, "_get_budget_redis", return_value=None):
            result = await router._budget_flag_is_set("_budget_warning_sent", (2026, 4))

        # No local flag set, no Redis — should be False
        assert result is False

    async def test_budget_flag_local_cache_short_circuits(self) -> None:
        router = _make_router()
        router._budget_warning_sent = (2026, 4)

        # Should return True without even checking Redis
        with patch.object(llm_router_mod, "_get_budget_redis", return_value=None):
            result = await router._budget_flag_is_set("_budget_warning_sent", (2026, 4))

        assert result is True

    async def test_check_budget_uses_redis_flags(self) -> None:
        """When Redis says warning was already sent, skip emitting."""
        router = _make_router(budget_usd=100.0, warning_pct=0.8)
        factory = _mock_session_factory(spend=85.0)

        mock_redis = AsyncMock()
        # warning flag already set in Redis, exceeded not set
        mock_redis.exists = AsyncMock(side_effect=lambda k: 1 if "warning" in k else 0)
        mock_redis.set = AsyncMock()

        with (
            patch.object(llm_router_mod, "get_session_factory", return_value=factory),
            patch.object(llm_router_mod, "_get_budget_redis", return_value=mock_redis),
            patch("wikimind.engine.llm_router.emit_budget_warning", new_callable=AsyncMock) as mock_warn,
            patch("wikimind.engine.llm_router.emit_budget_exceeded", new_callable=AsyncMock) as mock_exceeded,
        ):
            await router._check_budget(user_id="test-user")

        # Warning should NOT fire — Redis says it was already sent
        mock_warn.assert_not_awaited()
        mock_exceeded.assert_not_awaited()


# ---------------------------------------------------------------------------
# BackgroundCompiler — verify ARQ safety
# ---------------------------------------------------------------------------


class TestBackgroundCompilerSafety:
    """Verify BackgroundCompiler is already safe for multi-replica."""

    def test_prod_mode_uses_arq_not_local(self) -> None:
        """In prod (redis_url set), BackgroundCompiler routes through ARQ."""
        from wikimind.jobs.background import BackgroundCompiler  # noqa: PLC0415

        settings = SimpleNamespace(redis_url="redis://localhost:6379/0")
        with patch.object(llm_router_mod, "get_settings", return_value=settings):
            # Manually create a BackgroundCompiler with redis_url set
            compiler = BackgroundCompiler.__new__(BackgroundCompiler)
            compiler._redis_url = "redis://localhost:6379/0"

        assert compiler.is_prod is True

    def test_dev_mode_uses_in_process(self) -> None:
        """In dev (no redis_url), BackgroundCompiler runs in-process."""
        from wikimind.jobs.background import BackgroundCompiler  # noqa: PLC0415

        compiler = BackgroundCompiler.__new__(BackgroundCompiler)
        compiler._redis_url = None

        assert compiler.is_prod is False


# ---------------------------------------------------------------------------
# ChromaDB — verify single-writer pattern
# ---------------------------------------------------------------------------


class TestChromaDBSingleWriter:
    """Verify embedding writes are only called from the worker (single-writer)."""

    def test_embed_article_only_called_from_worker(self) -> None:
        """Verify embed_article is only called from single-writer paths.

        embed_article is only called from worker.py, which runs as a single
        ARQ process. This test documents the single-writer contract.
        """
        import ast  # noqa: PLC0415
        from pathlib import Path  # noqa: PLC0415

        src_dir = Path(__file__).resolve().parent.parent.parent / "src" / "wikimind"
        callers = []

        for py_file in src_dir.rglob("*.py"):
            if py_file.name == "embedding.py":
                continue
            try:
                source = py_file.read_text()
                tree = ast.parse(source)
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr == "embed_article":
                    callers.append(str(py_file.relative_to(src_dir)))

        # embed_article should only be called from worker.py and wiki.py (delete path)
        for caller in callers:
            assert caller in (
                "jobs/worker.py",
                "services/wiki.py",
            ), f"Unexpected embed_article caller: {caller}"
