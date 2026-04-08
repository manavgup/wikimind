"""Tests for ws, settings routes, middleware, database."""

from __future__ import annotations

import sqlite3
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select

from wikimind import database as db_mod
from wikimind._datetime import utcnow_naive
from wikimind.api.routes import ws as ws_mod
from wikimind.api.routes.ws import (
    ConnectionManager,
    emit_compilation_complete,
    emit_compilation_failed,
    emit_job_progress,
    emit_linter_alert,
    emit_sync_complete,
    get_connection_manager,
)
from wikimind.config import get_settings
from wikimind.database import close_db, get_db_path, get_session_factory, init_db
from wikimind.errors import WikiMindError
from wikimind.middleware import logging_config
from wikimind.middleware.error_handling import ErrorHandlingMiddleware
from wikimind.middleware.logging_config import _sanitize_event_dict
from wikimind.models import Conversation, Query

# ----- ws ConnectionManager -----


async def test_connection_manager_connect_and_disconnect() -> None:
    cm = ConnectionManager()
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.send_text = AsyncMock()
    await cm.connect(ws)
    assert ws in cm.active
    await cm.broadcast({"event": "x"})
    ws.send_text.assert_awaited()
    cm.disconnect(ws)
    assert ws not in cm.active


async def test_connection_manager_broadcast_drops_dead() -> None:
    cm = ConnectionManager()
    good = MagicMock()
    good.send_text = AsyncMock()
    bad = MagicMock()
    bad.send_text = AsyncMock(side_effect=RuntimeError("dead"))
    cm.active.update({good, bad})
    await cm.broadcast({"event": "x"})
    assert bad not in cm.active
    assert good in cm.active


async def test_connection_manager_broadcast_empty() -> None:
    cm = ConnectionManager()
    await cm.broadcast({"event": "x"})  # no-op


async def test_connection_manager_send_to_dead_disconnects() -> None:
    cm = ConnectionManager()
    ws = MagicMock()
    ws.send_text = AsyncMock(side_effect=RuntimeError("dead"))
    cm.active.add(ws)
    await cm.send_to(ws, {"e": "x"})
    assert ws not in cm.active


def test_get_connection_manager() -> None:
    assert get_connection_manager() is ws_mod.manager


async def test_emit_helpers() -> None:
    with patch.object(ws_mod.manager, "broadcast", AsyncMock()) as b:
        await emit_job_progress("j", 50)
        await emit_compilation_complete("s", "t")
        await emit_compilation_failed("s", "e")
        await emit_sync_complete(1, 2)
        await emit_linter_alert("contradiction", ["a"])
    assert b.await_count == 5


# ----- settings routes -----


async def test_settings_get_all(client) -> None:
    resp = await client.get("/settings")
    assert resp.status_code == 200
    assert "llm" in resp.json()


async def test_settings_set_api_key_invalid(client) -> None:
    resp = await client.post("/settings/llm/api-key", json={"provider": "bogus", "api_key": "x"})
    assert resp.status_code == 400


async def test_settings_set_api_key_ok(client) -> None:
    resp = await client.post("/settings/llm/api-key", json={"provider": "anthropic", "api_key": "k"})
    assert resp.status_code == 200


async def test_settings_test_llm_error(client) -> None:
    # No API key configured -> raises -> caught -> error status
    resp = await client.post("/settings/llm/test", params={"provider": "anthropic"})
    assert resp.status_code == 200
    assert resp.json()["status"] in ("ok", "error")


async def test_settings_get_cost(client, async_engine) -> None:
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    with patch("wikimind.api.routes.settings.get_session_factory", return_value=factory):
        resp = await client.get("/settings/llm/cost")
    assert resp.status_code == 200
    assert "cost_this_month_usd" in resp.json()


# ----- middleware error_handling -----


async def test_error_handling_wikimind_error() -> None:
    class _MyErr(WikiMindError):
        code = "my_err"
        status_code = 418

        def __init__(self):
            super().__init__("teapot")

    app = FastAPI()
    app.add_middleware(ErrorHandlingMiddleware)

    @app.get("/boom")
    async def boom():
        raise _MyErr()

    @app.get("/crash")
    async def crash():
        raise RuntimeError("oops")

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/boom")
        assert r.status_code == 418
        assert r.json()["error"]["code"] == "my_err"
        r = c.get("/crash")
        assert r.status_code == 500
        assert r.json()["error"]["code"] == "internal_error"


# ----- middleware logging_config -----


def test_sanitize_event_dict_redacts_sensitive_keys() -> None:
    out = _sanitize_event_dict(None, "info", {"api_key": "secret", "ok": "value"})
    assert out["api_key"] == "***REDACTED***"


def test_sanitize_event_dict_redacts_patterns() -> None:
    out = _sanitize_event_dict(None, "info", {"msg": "Bearer abc123"})
    assert "REDACTED" in out["msg"]


def test_configure_logging_dev(monkeypatch) -> None:
    monkeypatch.setenv("WIKIMIND_ENV", "development")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    logging_config.configure_logging()


def test_configure_logging_prod(monkeypatch) -> None:
    monkeypatch.setenv("WIKIMIND_ENV", "production")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    logging_config.configure_logging()


# ----- database -----


def test_get_db_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    p = db_mod.get_db_path()
    assert str(p).endswith("wikimind.db")


def test_get_engine_and_factory_singleton(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    db_mod._engine = None
    db_mod._session_factory = None
    e1 = db_mod.get_async_engine()
    e2 = db_mod.get_async_engine()
    assert e1 is e2
    f1 = db_mod.get_session_factory()
    f2 = db_mod.get_session_factory()
    assert f1 is f2


async def test_init_and_close_db(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    db_mod._engine = None
    db_mod._session_factory = None
    await db_mod.init_db()
    await db_mod.close_db()
    assert db_mod._engine is None


async def test_get_session_yields_and_commits(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    db_mod._engine = None
    db_mod._session_factory = None
    await db_mod.init_db()
    gen = db_mod.get_session()
    sess = await gen.__anext__()
    assert sess is not None
    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()
    await db_mod.close_db()


async def test_get_session_rolls_back_on_error(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    db_mod._engine = None
    db_mod._session_factory = None
    await db_mod.init_db()
    gen = db_mod.get_session()
    await gen.__anext__()
    with pytest.raises(RuntimeError):
        await gen.athrow(RuntimeError("boom"))
    await db_mod.close_db()


async def test_init_db_adds_conversation_id_and_turn_index_to_query(tmp_path, monkeypatch) -> None:
    """The lightweight migration helper adds the new query columns on a fresh DB."""
    # Point at a fresh tmp data dir
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    db_mod._engine = None
    db_mod._session_factory = None

    await init_db()

    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(query)").fetchall()}
    finally:
        conn.close()

    assert "conversation_id" in cols
    assert "turn_index" in cols

    await close_db()
    get_settings.cache_clear()


async def test_backfill_creates_conversation_for_legacy_query(tmp_path, monkeypatch):
    """Legacy Query rows with NULL conversation_id get a Conversation row backfilled."""
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    db_mod._engine = None
    db_mod._session_factory = None

    await init_db()

    # Insert a Query row directly without conversation_id (simulating a legacy row)
    factory = get_session_factory()
    async with factory() as session:
        legacy = Query(
            id=str(uuid.uuid4()),
            question="What is the legacy question?",
            answer="Legacy answer.",
            confidence="high",
            created_at=utcnow_naive(),
        )
        session.add(legacy)
        await session.commit()
        legacy_id = legacy.id

    # Run init_db again — backfill should kick in
    await init_db()

    async with factory() as session:
        result = await session.get(Query, legacy_id)
        assert result is not None
        assert result.conversation_id is not None
        assert result.turn_index == 0

        conv = await session.get(Conversation, result.conversation_id)
        assert conv is not None
        assert conv.title == "What is the legacy question?"

    # Idempotency: a third init_db should be a no-op (no duplicate Conversation rows)
    await init_db()
    async with factory() as session:
        rows_result = await session.execute(select(Conversation).where(Conversation.id == result.conversation_id))
        rows = list(rows_result.scalars().all())
        assert len(rows) == 1, "backfill is not idempotent — it duplicated the conversation row"

    await close_db()
    get_settings.cache_clear()
