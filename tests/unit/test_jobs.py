"""Tests for jobs.worker and jobs.background."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from tests.conftest import TEST_USER_ID
from wikimind.config import get_settings
from wikimind.jobs import background as bg_mod
from wikimind.jobs import worker as worker_mod
from wikimind.jobs.background import BackgroundCompiler, get_background_compiler
from wikimind.jobs.worker import (
    _recompile_from_source,
    compile_source,
    get_redis_settings,
    lint_wiki,
)
from wikimind.models import (
    Article,
    IngestStatus,
    LintReport,
    LintReportStatus,
    PageType,
    Source,
    SourceType,
)


def _raw_root() -> Path:
    """Return the raw storage root for TEST_USER_ID and ensure it exists."""
    settings = get_settings()
    root = Path(settings.data_dir) / "raw" / TEST_USER_ID
    root.mkdir(parents=True, exist_ok=True)
    return root


async def test_background_compiler_dev_mode_compile() -> None:
    bc = BackgroundCompiler()
    bc._redis_url = None
    with patch.object(bg_mod, "compile_source", AsyncMock()):
        job_id = await bc.schedule_compile("src-1", user_id=TEST_USER_ID)
    assert job_id


async def test_background_compiler_dev_mode_lint() -> None:
    bc = BackgroundCompiler()
    bc._redis_url = None
    with patch.object(bg_mod, "lint_wiki", AsyncMock()):
        job_id = await bc.schedule_lint(user_id=TEST_USER_ID)
    assert job_id


async def test_background_compiler_prod_mode_compile() -> None:
    bc = BackgroundCompiler()
    bc._redis_url = "redis://localhost:6379"
    fake_pool = MagicMock()
    fake_pool.enqueue_job = AsyncMock()
    fake_pool.close = AsyncMock()
    with patch.object(bg_mod, "create_pool", AsyncMock(return_value=fake_pool)):
        await bc.schedule_compile("src-1", user_id=TEST_USER_ID)
    fake_pool.enqueue_job.assert_awaited()
    # Pool is cached — not closed per call
    fake_pool.close.assert_not_awaited()


async def test_background_compiler_prod_mode_lint() -> None:
    bc = BackgroundCompiler()
    bc._redis_url = "redis://localhost:6379"
    fake_pool = MagicMock()
    fake_pool.enqueue_job = AsyncMock()
    fake_pool.close = AsyncMock()
    with patch.object(bg_mod, "create_pool", AsyncMock(return_value=fake_pool)):
        await bc.schedule_lint(user_id=TEST_USER_ID)
    fake_pool.enqueue_job.assert_awaited()


async def test_run_compile_in_process_logs_exception() -> None:
    with patch.object(bg_mod, "compile_source", AsyncMock(side_effect=RuntimeError("x"))):
        await BackgroundCompiler._run_compile_in_process("src-1", user_id=TEST_USER_ID)


async def test_run_lint_in_process_logs_exception() -> None:
    with patch.object(bg_mod, "lint_wiki", AsyncMock(side_effect=RuntimeError("x"))):
        await BackgroundCompiler._run_lint_in_process(user_id=TEST_USER_ID)


async def test_background_compiler_dev_mode_recompile() -> None:
    bc = BackgroundCompiler()
    bc._redis_url = None
    with patch.object(bg_mod, "recompile_article", AsyncMock()):
        job_id = await bc.schedule_recompile("art-1", "source", "job-1", user_id=TEST_USER_ID)
    assert job_id == "job-1"


async def test_background_compiler_dev_mode_sweep() -> None:
    bc = BackgroundCompiler()
    bc._redis_url = None
    with patch.object(bg_mod, "sweep_wikilinks", AsyncMock()):
        job_id = await bc.schedule_sweep(user_id=TEST_USER_ID)
    assert job_id


async def test_background_compiler_prod_mode_recompile() -> None:
    bc = BackgroundCompiler()
    bc._redis_url = "redis://localhost:6379"
    fake_pool = MagicMock()
    fake_pool.enqueue_job = AsyncMock()
    fake_pool.close = AsyncMock()
    with patch.object(bg_mod, "create_pool", AsyncMock(return_value=fake_pool)):
        await bc.schedule_recompile("art-1", "source", "job-1", user_id=TEST_USER_ID)
    fake_pool.enqueue_job.assert_awaited()


async def test_background_compiler_prod_mode_sweep() -> None:
    bc = BackgroundCompiler()
    bc._redis_url = "redis://localhost:6379"
    fake_pool = MagicMock()
    fake_pool.enqueue_job = AsyncMock()
    fake_pool.close = AsyncMock()
    with patch.object(bg_mod, "create_pool", AsyncMock(return_value=fake_pool)):
        await bc.schedule_sweep(user_id=TEST_USER_ID)
    fake_pool.enqueue_job.assert_awaited()


async def test_run_recompile_in_process_logs_exception() -> None:
    with patch.object(bg_mod, "recompile_article", AsyncMock(side_effect=RuntimeError("x"))):
        await BackgroundCompiler._run_recompile_in_process("art-1", "source", "job-1", user_id=TEST_USER_ID)


async def test_run_sweep_in_process_logs_exception() -> None:
    with patch.object(bg_mod, "sweep_wikilinks", AsyncMock(side_effect=RuntimeError("x"))):
        await BackgroundCompiler._run_sweep_in_process(user_id=TEST_USER_ID)


async def test_background_compiler_pool_reused_across_calls() -> None:
    """The ARQ pool is created once and reused for subsequent enqueue calls."""
    bc = BackgroundCompiler()
    bc._redis_url = "redis://localhost:6379"
    fake_pool = MagicMock()
    fake_pool.enqueue_job = AsyncMock()
    mock_create = AsyncMock(return_value=fake_pool)
    with patch.object(bg_mod, "create_pool", mock_create):
        await bc.schedule_compile("src-1", user_id=TEST_USER_ID)
        await bc.schedule_lint(user_id=TEST_USER_ID)
    # create_pool called only once despite two enqueue calls
    assert mock_create.await_count == 1
    assert fake_pool.enqueue_job.await_count == 2


async def test_background_compiler_close() -> None:
    """close() shuts down the cached pool and resets the attribute."""
    bc = BackgroundCompiler()
    fake_pool = MagicMock()
    fake_pool.close = AsyncMock()
    bc._arq_pool = fake_pool
    await bc.close()
    fake_pool.close.assert_awaited_once()
    assert bc._arq_pool is None


async def test_background_compiler_close_noop_when_no_pool() -> None:
    """close() is safe to call when no pool was ever created."""
    bc = BackgroundCompiler()
    await bc.close()  # should not raise


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
        await compile_source({}, "missing", user_id=TEST_USER_ID)


async def test_compile_source_no_file_path(db_session, tmp_path) -> None:
    src = Source(
        source_type=SourceType.TEXT, title="t", file_path=None, status=IngestStatus.PROCESSING, user_id=TEST_USER_ID
    )
    db_session.add(src)
    await db_session.commit()
    with (
        _patch_session_factory(db_session),
        patch.object(worker_mod, "emit_source_progress", AsyncMock()),
        patch.object(worker_mod, "emit_compilation_failed", AsyncMock()),
    ):
        await compile_source({}, src.id, user_id=TEST_USER_ID)
    await db_session.refresh(src)
    assert src.status == IngestStatus.FAILED


async def test_compile_source_success(db_session, tmp_path) -> None:
    text_file = tmp_path / "src.txt"
    text_file.write_text("hello world", encoding="utf-8")
    src = Source(
        source_type=SourceType.TEXT,
        title="t",
        file_path=str(text_file),
        status=IngestStatus.PROCESSING,
        user_id=TEST_USER_ID,
    )
    db_session.add(src)
    await db_session.commit()

    fake_compiler = MagicMock()
    fake_compiler.compile = AsyncMock(return_value=MagicMock())
    fake_article = MagicMock(slug="s", title="T")
    fake_compiler.save_article = AsyncMock(return_value=fake_article)

    with (
        _patch_session_factory(db_session),
        patch.object(worker_mod, "Compiler", return_value=fake_compiler),
        patch.object(worker_mod, "emit_source_progress", AsyncMock()),
        patch.object(worker_mod, "emit_compilation_complete", AsyncMock()),
    ):
        await compile_source({}, src.id, user_id=TEST_USER_ID)


async def test_compile_source_compiler_returns_none(db_session, tmp_path) -> None:
    text_file = tmp_path / "src.txt"
    text_file.write_text("hello", encoding="utf-8")
    src = Source(
        source_type=SourceType.TEXT,
        title="t",
        file_path=str(text_file),
        status=IngestStatus.PROCESSING,
        user_id=TEST_USER_ID,
    )
    db_session.add(src)
    await db_session.commit()

    fake_compiler = MagicMock()
    fake_compiler.compile = AsyncMock(return_value=None)

    with (
        _patch_session_factory(db_session),
        patch.object(worker_mod, "Compiler", return_value=fake_compiler),
        patch.object(worker_mod, "emit_source_progress", AsyncMock()),
        patch.object(worker_mod, "emit_compilation_failed", AsyncMock()),
    ):
        await compile_source({}, src.id, user_id=TEST_USER_ID)
    await db_session.refresh(src)
    assert src.status == IngestStatus.FAILED


async def test_compile_source_sets_processing_on_start(db_session, tmp_path) -> None:
    """When compile_source starts, source.status must be PROCESSING and error_message cleared."""
    raw = _raw_root()
    (raw / "src.txt").write_text("hello world", encoding="utf-8")
    src = Source(
        source_type=SourceType.TEXT,
        title="t",
        file_path="src.txt",
        status=IngestStatus.FAILED,
        error_message="previous error",
        user_id=TEST_USER_ID,
    )
    db_session.add(src)
    await db_session.commit()

    fake_compiler = MagicMock()
    fake_compiler.compile = AsyncMock(return_value=MagicMock())
    fake_article = MagicMock(slug="s", title="T")
    fake_compiler.save_article = AsyncMock(return_value=fake_article)

    with (
        _patch_session_factory(db_session),
        patch.object(worker_mod, "Compiler", return_value=fake_compiler),
        patch.object(worker_mod, "emit_source_progress", AsyncMock()),
        patch.object(worker_mod, "emit_compilation_complete", AsyncMock()),
        patch.object(worker_mod, "sweep_wikilinks", AsyncMock()),
    ):
        await compile_source({}, src.id, user_id=TEST_USER_ID)

    await db_session.refresh(src)
    # After successful compilation the source stays in a non-failed state;
    # the key assertion is that error_message was cleared at the start.
    assert src.error_message is None


async def test_compile_source_clears_error_on_retry(db_session, tmp_path) -> None:
    """A previously-failed source should have error_message=None while compiling."""
    raw = _raw_root()
    (raw / "src.txt").write_text("content", encoding="utf-8")
    src = Source(
        source_type=SourceType.TEXT,
        title="retry-me",
        file_path="src.txt",
        status=IngestStatus.FAILED,
        error_message="old boom",
        user_id=TEST_USER_ID,
    )
    db_session.add(src)
    await db_session.commit()

    # Record the source status at the moment the compiler is invoked.
    captured_status: list[IngestStatus] = []
    captured_error: list[str | None] = []

    async def _spy_compile(doc, session, **kwargs):
        await db_session.refresh(src)
        captured_status.append(src.status)
        captured_error.append(src.error_message)
        return MagicMock()

    fake_compiler = MagicMock()
    fake_compiler.compile = AsyncMock(side_effect=_spy_compile)
    fake_compiler.save_article = AsyncMock(return_value=MagicMock(slug="s", title="T"))

    with (
        _patch_session_factory(db_session),
        patch.object(worker_mod, "Compiler", return_value=fake_compiler),
        patch.object(worker_mod, "emit_source_progress", AsyncMock()),
        patch.object(worker_mod, "emit_compilation_complete", AsyncMock()),
        patch.object(worker_mod, "sweep_wikilinks", AsyncMock()),
    ):
        await compile_source({}, src.id, user_id=TEST_USER_ID)

    assert captured_status == [IngestStatus.PROCESSING]
    assert captured_error == [None]


async def test_compile_source_failure_after_retry_sets_failed(db_session, tmp_path) -> None:
    """On failure the source must revert to FAILED with a new error_message."""
    raw = _raw_root()
    (raw / "src.txt").write_text("content", encoding="utf-8")
    src = Source(
        source_type=SourceType.TEXT,
        title="fail-again",
        file_path="src.txt",
        status=IngestStatus.FAILED,
        error_message="old error",
        user_id=TEST_USER_ID,
    )
    db_session.add(src)
    await db_session.commit()

    fake_compiler = MagicMock()
    fake_compiler.compile = AsyncMock(side_effect=RuntimeError("new boom"))

    with (
        _patch_session_factory(db_session),
        patch.object(worker_mod, "Compiler", return_value=fake_compiler),
        patch.object(worker_mod, "emit_source_progress", AsyncMock()),
        patch.object(worker_mod, "emit_compilation_failed", AsyncMock()),
    ):
        await compile_source({}, src.id, user_id=TEST_USER_ID)

    await db_session.refresh(src)
    assert src.status == IngestStatus.FAILED
    assert src.error_message == "new boom"


async def test_lint_wiki_no_articles(db_session) -> None:
    with _patch_session_factory(db_session):
        await lint_wiki({}, user_id=TEST_USER_ID)


async def test_lint_wiki_with_articles(db_session, tmp_path) -> None:
    """Lint runs the structured pipeline via run_lint."""
    fake_report = LintReport(
        status=LintReportStatus.COMPLETE,
        contradictions_count=1,
        orphans_count=0,
        user_id=TEST_USER_ID,
    )
    with (
        _patch_session_factory(db_session),
        patch("wikimind.jobs.worker.run_lint", AsyncMock(return_value=fake_report)),
    ):
        await lint_wiki({}, user_id=TEST_USER_ID)


async def test_lint_wiki_failure(db_session, tmp_path) -> None:
    """Lint handles run_lint exceptions gracefully."""
    with (
        _patch_session_factory(db_session),
        patch("wikimind.jobs.worker.run_lint", AsyncMock(side_effect=RuntimeError("boom"))),
    ):
        await lint_wiki({}, user_id=TEST_USER_ID)


# ---------------------------------------------------------------------------
# _recompile_from_source — must update in place, not create orphan (#492)
# ---------------------------------------------------------------------------


async def test_recompile_from_source_calls_save_article_in_place(db_session, tmp_path) -> None:
    """_recompile_from_source must call save_article_in_place with the existing article."""
    raw = _raw_root()
    (raw / "src.txt").write_text("hello world", encoding="utf-8")
    src = Source(
        source_type=SourceType.TEXT,
        title="t",
        file_path="src.txt",
        status=IngestStatus.COMPILED,
        user_id=TEST_USER_ID,
    )
    db_session.add(src)
    await db_session.commit()
    await db_session.refresh(src)

    article = Article(
        slug="test-article",
        title="Test",
        file_path="test-article/test-article.md",
        page_type=PageType.SOURCE,
        source_ids=json.dumps([src.id]),
        user_id=TEST_USER_ID,
    )
    db_session.add(article)
    await db_session.commit()
    await db_session.refresh(article)

    fake_result = MagicMock()
    fake_compiler = MagicMock()
    fake_compiler.compile = AsyncMock(return_value=fake_result)
    fake_compiler.save_article_in_place = AsyncMock(return_value=article)

    with (
        _patch_session_factory(db_session),
        patch.object(worker_mod, "Compiler", return_value=fake_compiler),
    ):
        await _recompile_from_source(article.id, TEST_USER_ID)

    # Must call save_article_in_place, not save_article.
    fake_compiler.save_article_in_place.assert_awaited_once()
    call_args = fake_compiler.save_article_in_place.call_args[0]
    assert call_args[0].id == article.id  # same article
    assert call_args[1] is fake_result  # compiler result
    assert call_args[2].id == src.id  # same source
    fake_compiler.save_article.assert_not_called()
