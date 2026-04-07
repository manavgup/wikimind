"""Tests for jobs.worker and jobs.background."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from wikimind.jobs import background as bg_mod
from wikimind.jobs import worker as worker_mod
from wikimind.jobs.background import BackgroundCompiler, get_background_compiler
from wikimind.jobs.worker import compile_source, get_redis_settings, lint_wiki
from wikimind.models import Article, IngestStatus, Source, SourceType


async def test_background_compiler_dev_mode_compile() -> None:
    bc = BackgroundCompiler()
    bc._redis_url = None
    with patch.object(bg_mod, "compile_source", AsyncMock()):
        job_id = await bc.schedule_compile("src-1")
    assert job_id


async def test_background_compiler_dev_mode_lint() -> None:
    bc = BackgroundCompiler()
    bc._redis_url = None
    with patch.object(bg_mod, "lint_wiki", AsyncMock()):
        job_id = await bc.schedule_lint()
    assert job_id


async def test_background_compiler_prod_mode_compile() -> None:
    bc = BackgroundCompiler()
    bc._redis_url = "redis://localhost:6379"
    fake_pool = MagicMock()
    fake_pool.enqueue_job = AsyncMock()
    fake_pool.close = AsyncMock()
    with patch.object(bg_mod, "create_pool", AsyncMock(return_value=fake_pool)):
        await bc.schedule_compile("src-1")
    fake_pool.enqueue_job.assert_awaited()
    fake_pool.close.assert_awaited()


async def test_background_compiler_prod_mode_lint() -> None:
    bc = BackgroundCompiler()
    bc._redis_url = "redis://localhost:6379"
    fake_pool = MagicMock()
    fake_pool.enqueue_job = AsyncMock()
    fake_pool.close = AsyncMock()
    with patch.object(bg_mod, "create_pool", AsyncMock(return_value=fake_pool)):
        await bc.schedule_lint()
    fake_pool.enqueue_job.assert_awaited()


async def test_run_compile_in_process_logs_exception() -> None:
    with patch.object(bg_mod, "compile_source", AsyncMock(side_effect=RuntimeError("x"))):
        await BackgroundCompiler._run_compile_in_process("src-1")


async def test_run_lint_in_process_logs_exception() -> None:
    with patch.object(bg_mod, "lint_wiki", AsyncMock(side_effect=RuntimeError("x"))):
        await BackgroundCompiler._run_lint_in_process()


def test_background_compiler_singleton() -> None:
    bg_mod._background_compiler = None
    a = get_background_compiler()
    b = get_background_compiler()
    assert a is b


def test_get_redis_settings_default(monkeypatch) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)
    s = get_redis_settings()
    assert s.host == "localhost"


def test_get_redis_settings_from_url(monkeypatch) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://example.com:1234")
    s = get_redis_settings()
    assert s.host == "example.com"


# ---------------------------------------------------------------------------
# Worker job functions
# ---------------------------------------------------------------------------


class _SessionFactoryCtx:
    """Async context manager wrapping a real db_session for test."""

    def __init__(self, session) -> None:
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *a):
        return False


def _patch_session_factory(session):
    factory = MagicMock(return_value=_SessionFactoryCtx(session))
    return patch.object(worker_mod, "get_session_factory", return_value=factory)


async def test_compile_source_no_source(db_session) -> None:
    with _patch_session_factory(db_session):
        await compile_source({}, "missing")


async def test_compile_source_no_file_path(db_session, tmp_path) -> None:
    src = Source(source_type=SourceType.TEXT, title="t", file_path=None, status=IngestStatus.PROCESSING)
    db_session.add(src)
    await db_session.commit()
    with (
        _patch_session_factory(db_session),
        patch.object(worker_mod, "emit_job_progress", AsyncMock()),
        patch.object(worker_mod, "emit_compilation_failed", AsyncMock()),
    ):
        await compile_source({}, src.id)
    await db_session.refresh(src)
    assert src.status == IngestStatus.FAILED


async def test_compile_source_success(db_session, tmp_path) -> None:
    text_file = tmp_path / "src.txt"
    text_file.write_text("hello world", encoding="utf-8")
    src = Source(source_type=SourceType.TEXT, title="t", file_path=str(text_file), status=IngestStatus.PROCESSING)
    db_session.add(src)
    await db_session.commit()

    fake_compiler = MagicMock()
    fake_compiler.compile = AsyncMock(return_value=MagicMock())
    fake_article = MagicMock(slug="s", title="T")
    fake_compiler.save_article = AsyncMock(return_value=fake_article)

    with (
        _patch_session_factory(db_session),
        patch.object(worker_mod, "Compiler", return_value=fake_compiler),
        patch.object(worker_mod, "emit_job_progress", AsyncMock()),
        patch.object(worker_mod, "emit_compilation_complete", AsyncMock()),
    ):
        await compile_source({}, src.id)


async def test_compile_source_compiler_returns_none(db_session, tmp_path) -> None:
    text_file = tmp_path / "src.txt"
    text_file.write_text("hello", encoding="utf-8")
    src = Source(source_type=SourceType.TEXT, title="t", file_path=str(text_file), status=IngestStatus.PROCESSING)
    db_session.add(src)
    await db_session.commit()

    fake_compiler = MagicMock()
    fake_compiler.compile = AsyncMock(return_value=None)

    with (
        _patch_session_factory(db_session),
        patch.object(worker_mod, "Compiler", return_value=fake_compiler),
        patch.object(worker_mod, "emit_job_progress", AsyncMock()),
        patch.object(worker_mod, "emit_compilation_failed", AsyncMock()),
    ):
        await compile_source({}, src.id)
    await db_session.refresh(src)
    assert src.status == IngestStatus.FAILED


async def test_lint_wiki_no_articles(db_session) -> None:
    with _patch_session_factory(db_session):
        await lint_wiki({})


async def test_lint_wiki_with_articles(db_session, tmp_path) -> None:
    f = tmp_path / "a.md"
    f.write_text("body", encoding="utf-8")
    art = Article(slug="a", title="A", file_path=str(f))
    db_session.add(art)
    await db_session.commit()

    fake_router = MagicMock()
    fake_router.complete = AsyncMock(return_value=MagicMock(content="{}"))
    fake_router.parse_json_response = MagicMock(
        return_value={
            "contradictions": [{"claim_a": "x", "claim_b": "y", "articles": ["A"]}],
            "orphaned_articles": [],
            "stale_articles": [],
            "gap_suggestions": ["new"],
            "coverage_scores": {},
        }
    )
    with (
        _patch_session_factory(db_session),
        patch.object(worker_mod, "get_llm_router", return_value=fake_router),
        patch.object(worker_mod, "emit_linter_alert", AsyncMock()),
        patch.object(worker_mod, "get_settings", return_value=SimpleNamespace(data_dir=str(tmp_path))),
    ):
        await lint_wiki({})


async def test_lint_wiki_failure(db_session, tmp_path) -> None:
    f = tmp_path / "a.md"
    f.write_text("body", encoding="utf-8")
    art = Article(slug="a", title="A", file_path=str(f))
    db_session.add(art)
    await db_session.commit()

    fake_router = MagicMock()
    fake_router.complete = AsyncMock(side_effect=RuntimeError("boom"))
    with (
        _patch_session_factory(db_session),
        patch.object(worker_mod, "get_llm_router", return_value=fake_router),
        patch.object(worker_mod, "get_settings", return_value=SimpleNamespace(data_dir=str(tmp_path))),
    ):
        await lint_wiki({})
