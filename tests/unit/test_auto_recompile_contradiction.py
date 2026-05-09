"""Tests for auto-recompile on new contradiction detection (issue #417)."""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import TEST_USER_ID
from wikimind.engine.linter.runner import (
    _queue_recompile_for_new_contradictions,
    _snapshot_existing_contradiction_hashes,
    run_lint,
)
from wikimind.models import (
    ContradictionFinding,
    LintFindingKind,
    LintSeverity,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_finding(
    *,
    article_a_id: str = "art-a",
    article_b_id: str = "art-b",
    content_hash: str | None = None,
) -> ContradictionFinding:
    """Create a ContradictionFinding for testing."""
    ids = sorted([article_a_id, article_b_id])
    if content_hash is None:
        content_hash = hashlib.sha256(f"{LintFindingKind.CONTRADICTION}|{ids[0]}|{ids[1]}".encode()).hexdigest()
    return ContradictionFinding(
        report_id="report-1",
        severity=LintSeverity.WARN,
        description="Test contradiction",
        content_hash=content_hash,
        article_a_id=article_a_id,
        article_b_id=article_b_id,
        article_a_claim="Claim A",
        article_b_claim="Claim B",
        llm_confidence="high",
        user_id=TEST_USER_ID,
    )


def _mock_session_factory() -> tuple[MagicMock, AsyncMock]:
    """Build a mock get_session_factory that yields a mock async session.

    Returns (factory_fn, mock_session) so tests can inspect the session.
    ``get_session_factory()()`` is a sync call chain producing an async
    context manager, matching ``async_sessionmaker`` behavior.
    """
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.refresh = AsyncMock()

    @asynccontextmanager
    async def _session_cm():
        yield mock_session

    # get_session_factory() returns a callable factory; calling factory()
    # returns the async context manager, matching async_sessionmaker().
    factory = MagicMock(side_effect=_session_cm)

    def _get_factory():
        return factory

    return _get_factory, mock_session


# ---------------------------------------------------------------------------
# _snapshot_existing_contradiction_hashes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_snapshot_empty_db(db_session: AsyncSession) -> None:
    """Empty database returns an empty set of hashes."""
    hashes = await _snapshot_existing_contradiction_hashes(db_session, TEST_USER_ID)
    assert hashes == set()


@pytest.mark.asyncio
async def test_snapshot_returns_existing_hashes(db_session: AsyncSession) -> None:
    """Persisted findings' content_hashes are returned by the snapshot."""
    f1 = _make_finding(article_a_id="a1", article_b_id="b1", content_hash="hash-1")
    f2 = _make_finding(article_a_id="a2", article_b_id="b2", content_hash="hash-2")
    db_session.add(f1)
    db_session.add(f2)
    await db_session.commit()

    hashes = await _snapshot_existing_contradiction_hashes(db_session, TEST_USER_ID)
    assert hashes == {"hash-1", "hash-2"}


# ---------------------------------------------------------------------------
# _queue_recompile_for_new_contradictions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_contradiction_triggers_recompile() -> None:
    """A finding with a hash NOT in existing_hashes queues recompile jobs."""
    finding = _make_finding(
        article_a_id="art-a",
        article_b_id="art-b",
        content_hash="brand-new-hash",
    )
    existing_hashes: set[str] = set()

    mock_bg = AsyncMock()
    mock_bg.schedule_recompile = AsyncMock(return_value="job-id")
    get_factory, _ = _mock_session_factory()

    with (
        patch(
            "wikimind.jobs.background.get_background_compiler",
            return_value=mock_bg,
        ),
        patch(
            "wikimind.engine.linter.runner.get_session_factory",
            get_factory,
        ),
    ):
        queued = await _queue_recompile_for_new_contradictions(
            [finding],
            existing_hashes,
            user_id=TEST_USER_ID,
        )

    assert queued == 2  # Both article_a and article_b
    assert mock_bg.schedule_recompile.await_count == 2
    scheduled_article_ids = {call.kwargs["article_id"] for call in mock_bg.schedule_recompile.call_args_list}
    assert scheduled_article_ids == {"art-a", "art-b"}


@pytest.mark.asyncio
async def test_existing_contradiction_does_not_trigger_recompile() -> None:
    """A finding whose hash IS in existing_hashes does NOT queue recompile."""
    finding = _make_finding(content_hash="already-known-hash")
    existing_hashes = {"already-known-hash"}

    mock_bg = AsyncMock()
    get_factory, _ = _mock_session_factory()

    with (
        patch(
            "wikimind.jobs.background.get_background_compiler",
            return_value=mock_bg,
        ),
        patch(
            "wikimind.engine.linter.runner.get_session_factory",
            get_factory,
        ),
    ):
        queued = await _queue_recompile_for_new_contradictions(
            [finding],
            existing_hashes,
            user_id=TEST_USER_ID,
        )

    assert queued == 0
    mock_bg.schedule_recompile.assert_not_awaited()


@pytest.mark.asyncio
async def test_mixed_new_and_existing_contradictions() -> None:
    """Only genuinely new contradictions trigger recompile, not existing ones."""
    new_finding = _make_finding(
        article_a_id="new-a",
        article_b_id="new-b",
        content_hash="new-hash",
    )
    old_finding = _make_finding(
        article_a_id="old-a",
        article_b_id="old-b",
        content_hash="old-hash",
    )
    existing_hashes = {"old-hash"}

    mock_bg = AsyncMock()
    mock_bg.schedule_recompile = AsyncMock(return_value="job-id")
    get_factory, _ = _mock_session_factory()

    with (
        patch(
            "wikimind.jobs.background.get_background_compiler",
            return_value=mock_bg,
        ),
        patch(
            "wikimind.engine.linter.runner.get_session_factory",
            get_factory,
        ),
    ):
        queued = await _queue_recompile_for_new_contradictions(
            [new_finding, old_finding],
            existing_hashes,
            user_id=TEST_USER_ID,
        )

    # Only the new contradiction's articles (new-a, new-b) should be queued
    assert queued == 2
    scheduled_article_ids = {call.kwargs["article_id"] for call in mock_bg.schedule_recompile.call_args_list}
    assert scheduled_article_ids == {"new-a", "new-b"}


@pytest.mark.asyncio
async def test_auto_recompile_disabled_by_setting() -> None:
    """When auto_recompile_on_contradiction=False, run_lint skips recompile queuing."""
    with patch("wikimind.engine.linter.runner.get_settings") as mock_settings:
        settings = mock_settings.return_value
        settings.linter.auto_recompile_on_contradiction = False
        settings.linter.enable_orphan_detection = True
        settings.linter.max_concepts_per_run = 25

        with (
            patch(
                "wikimind.engine.linter.runner.get_llm_router",
            ),
            patch(
                "wikimind.engine.linter.runner._check_in_progress",
                return_value=None,
            ),
            patch(
                "wikimind.engine.linter.runner._snapshot_existing_contradiction_hashes",
                return_value=set(),
            ),
            patch(
                "wikimind.engine.linter.runner.detect_contradictions",
                return_value=[
                    _make_finding(content_hash="new-hash"),
                ],
            ),
            patch(
                "wikimind.engine.linter.runner.detect_orphans",
                return_value=[],
            ),
            patch(
                "wikimind.engine.linter.runner.run_enforcer_checks",
                return_value=[],
            ),
            patch(
                "wikimind.engine.linter.runner._apply_dismiss_suppression",
            ),
            patch(
                "wikimind.engine.linter.runner.emit_linter_alert",
            ),
            patch(
                "wikimind.engine.linter.runner._queue_recompile_for_new_contradictions",
            ) as mock_queue,
        ):
            mock_session = AsyncMock()
            mock_session.add = MagicMock()  # add() is sync
            mock_session.execute = AsyncMock()
            # Return 0 for article count
            mock_result = AsyncMock()
            mock_result.scalar.return_value = 0
            mock_session.execute.return_value = mock_result

            await run_lint(mock_session, user_id=TEST_USER_ID)

            # The queue function should NOT be called when setting is False
            mock_queue.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_recompile_when_no_contradictions() -> None:
    """When no contradictions are found, no recompile is queued."""
    finding = _make_finding(content_hash="some-hash")
    # All findings are in existing hashes = no new contradictions
    existing_hashes = {"some-hash"}

    mock_bg = AsyncMock()
    get_factory, _ = _mock_session_factory()

    with (
        patch(
            "wikimind.jobs.background.get_background_compiler",
            return_value=mock_bg,
        ),
        patch(
            "wikimind.engine.linter.runner.get_session_factory",
            get_factory,
        ),
    ):
        queued = await _queue_recompile_for_new_contradictions(
            [finding],
            existing_hashes,
            user_id=TEST_USER_ID,
        )

    assert queued == 0


@pytest.mark.asyncio
async def test_recompile_deduplicates_article_ids() -> None:
    """If the same article appears in multiple new contradictions, recompile once."""
    # art-shared appears in both findings
    finding1 = _make_finding(
        article_a_id="art-shared",
        article_b_id="art-b1",
        content_hash="hash-1",
    )
    finding2 = _make_finding(
        article_a_id="art-shared",
        article_b_id="art-b2",
        content_hash="hash-2",
    )
    existing_hashes: set[str] = set()

    mock_bg = AsyncMock()
    mock_bg.schedule_recompile = AsyncMock(return_value="job-id")
    get_factory, _ = _mock_session_factory()

    with (
        patch(
            "wikimind.jobs.background.get_background_compiler",
            return_value=mock_bg,
        ),
        patch(
            "wikimind.engine.linter.runner.get_session_factory",
            get_factory,
        ),
    ):
        queued = await _queue_recompile_for_new_contradictions(
            [finding1, finding2],
            existing_hashes,
            user_id=TEST_USER_ID,
        )

    # art-shared, art-b1, art-b2 = 3 unique articles
    assert queued == 3
    scheduled_article_ids = {call.kwargs["article_id"] for call in mock_bg.schedule_recompile.call_args_list}
    assert scheduled_article_ids == {"art-shared", "art-b1", "art-b2"}
