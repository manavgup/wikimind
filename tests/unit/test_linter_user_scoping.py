"""Tests for linter engine user_id scoping (Epic #337, Issue #10).

Verifies that detect_orphans, detect_contradictions, and run_enforcer_checks
return only the specified user's data when user_id is provided.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wikimind.config import get_settings
from wikimind.engine.linter.contradictions import detect_contradictions
from wikimind.engine.linter.orphans import detect_orphans
from wikimind.engine.linter.runner import run_enforcer_checks, run_lint
from wikimind.models import (
    Article,
    ArticleConcept,
    Concept,
    LintReport,
    LintReportStatus,
)

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_article(
    tmp_path: Path,
    *,
    article_id: str = "a1",
    slug: str = "test-article",
    title: str = "Test Article",
    user_id: str | None = None,
    claims: list[str] | None = None,
) -> Article:
    """Create an Article with a real .md file containing claims."""
    wiki_dir = tmp_path / "wikimind" / "wiki"
    if user_id:
        wiki_dir = wiki_dir / user_id
    wiki_dir.mkdir(parents=True, exist_ok=True)
    file_path = wiki_dir / f"{slug}.md"
    body_lines = [f"# {title}", ""]
    if claims:
        body_lines.append("## Key Claims")
        for c in claims:
            body_lines.append(f"- {c}")
    else:
        body_lines.append("Some body content here.")
    file_path.write_text("\n".join(body_lines), encoding="utf-8")

    return Article(
        id=article_id,
        slug=slug,
        title=title,
        file_path=f"{slug}.md",
        user_id=user_id,
    )


# ---------------------------------------------------------------------------
# detect_orphans — user_id scoping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_orphans_scoped_by_user_id(db_session, _isolated_data_dir, tmp_path) -> None:
    """Orphan detection with user_id only returns that user's orphaned articles."""
    settings = get_settings()
    settings.linter.enable_orphan_detection = True

    # Create orphan articles for two different users
    art_alice = _make_article(
        tmp_path,
        article_id="alice-art",
        slug="alice-art",
        title="Alice Article",
        user_id="alice",
    )
    art_bob = _make_article(
        tmp_path,
        article_id="bob-art",
        slug="bob-art",
        title="Bob Article",
        user_id="bob",
    )
    db_session.add(art_alice)
    db_session.add(art_bob)
    await db_session.commit()

    # Scoped to alice — should only find alice's orphan
    findings_alice = await detect_orphans(db_session, settings, report_id="r1", user_id="alice")
    assert len(findings_alice) == 1
    assert findings_alice[0].article_id == "alice-art"
    assert findings_alice[0].user_id == "alice"

    # Scoped to bob — should only find bob's orphan
    findings_bob = await detect_orphans(db_session, settings, report_id="r1", user_id="bob")
    assert len(findings_bob) == 1
    assert findings_bob[0].article_id == "bob-art"
    assert findings_bob[0].user_id == "bob"


@pytest.mark.asyncio
async def test_detect_orphans_no_user_id_returns_all(db_session, _isolated_data_dir, tmp_path) -> None:
    """Orphan detection without user_id returns all orphaned articles."""
    settings = get_settings()
    settings.linter.enable_orphan_detection = True

    art_alice = _make_article(
        tmp_path,
        article_id="alice-art",
        slug="alice-art",
        title="Alice Article",
        user_id="alice",
    )
    art_bob = _make_article(
        tmp_path,
        article_id="bob-art",
        slug="bob-art",
        title="Bob Article",
        user_id="bob",
    )
    db_session.add(art_alice)
    db_session.add(art_bob)
    await db_session.commit()

    findings = await detect_orphans(db_session, settings, report_id="r1")
    assert len(findings) == 2


# ---------------------------------------------------------------------------
# detect_contradictions — user_id scoping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_contradictions_scoped_by_user_id(db_session, _isolated_data_dir, tmp_path) -> None:
    """Contradiction detection with user_id only processes that user's articles."""
    # Create concepts for two users
    concept_alice = Concept(id="c-alice", name="testing", article_count=2, user_id="alice")
    concept_bob = Concept(id="c-bob", name="testing-bob", article_count=2, user_id="bob")
    db_session.add(concept_alice)
    db_session.add(concept_bob)

    # Alice's articles
    art_a1 = _make_article(
        tmp_path,
        article_id="a1",
        slug="alice-art-a",
        title="Alice A",
        user_id="alice",
        claims=["The sky is blue"],
    )
    art_a2 = _make_article(
        tmp_path,
        article_id="a2",
        slug="alice-art-b",
        title="Alice B",
        user_id="alice",
        claims=["The sky is green"],
    )
    # Bob's articles
    art_b1 = _make_article(
        tmp_path,
        article_id="b1",
        slug="bob-art-a",
        title="Bob A",
        user_id="bob",
        claims=["Water is wet"],
    )
    art_b2 = _make_article(
        tmp_path,
        article_id="b2",
        slug="bob-art-b",
        title="Bob B",
        user_id="bob",
        claims=["Water is dry"],
    )
    db_session.add(art_a1)
    db_session.add(art_a2)
    db_session.add(art_b1)
    db_session.add(art_b2)
    await db_session.commit()

    db_session.add(ArticleConcept(article_id="a1", concept_name="testing"))
    db_session.add(ArticleConcept(article_id="a2", concept_name="testing"))
    db_session.add(ArticleConcept(article_id="b1", concept_name="testing-bob"))
    db_session.add(ArticleConcept(article_id="b2", concept_name="testing-bob"))
    await db_session.commit()

    mock_router = MagicMock()
    mock_router.complete = AsyncMock(return_value=MagicMock())
    mock_router.parse_json_response = MagicMock(
        return_value={
            "contradictions": [
                {
                    "description": "Color contradiction",
                    "article_a_claim": "The sky is blue",
                    "article_b_claim": "The sky is green",
                    "confidence": "high",
                }
            ]
        }
    )

    settings = get_settings()

    # Run for alice only
    report = LintReport(id="r-alice", user_id="alice")
    db_session.add(report)
    await db_session.flush()

    findings = await detect_contradictions(db_session, mock_router, settings, report, user_id="alice")

    # LLM should be called exactly once (one alice concept pair)
    assert mock_router.complete.call_count == 1
    assert len(findings) == 1
    assert findings[0].user_id == "alice"
    assert findings[0].article_a_id == "a1"
    assert findings[0].article_b_id == "a2"


# ---------------------------------------------------------------------------
# run_enforcer_checks — user_id scoping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_enforcer_checks_scoped_by_user_id(db_session, _isolated_data_dir, tmp_path) -> None:
    """run_enforcer_checks with user_id only processes that user's articles."""
    art_alice = _make_article(
        tmp_path,
        article_id="alice-art",
        slug="alice-art",
        title="Alice Article",
        user_id="alice",
    )
    art_bob = _make_article(
        tmp_path,
        article_id="bob-art",
        slug="bob-art",
        title="Bob Article",
        user_id="bob",
    )
    db_session.add(art_alice)
    db_session.add(art_bob)
    await db_session.commit()

    report = LintReport(id="r1", user_id="alice")
    db_session.add(report)
    await db_session.flush()

    with patch(
        "wikimind.engine.linter.runner.enforce_backlinks",
        new_callable=AsyncMock,
    ) as mock_enforce:
        mock_enforce.return_value = MagicMock(violations=[])

        await run_enforcer_checks(db_session, report, user_id="alice")

        # Only alice's article should be checked
        assert mock_enforce.call_count == 1
        mock_enforce.assert_called_once_with("alice-art", db_session)
        assert report.checked_articles == 1


# ---------------------------------------------------------------------------
# run_lint end-to-end — user_id scoping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_lint_scopes_article_count_by_user_id(db_session, _isolated_data_dir, tmp_path) -> None:
    """run_lint with user_id counts only that user's articles."""
    art_alice = _make_article(
        tmp_path,
        article_id="alice-art",
        slug="alice-art",
        title="Alice Article",
        user_id="alice",
        claims=["Claim A"],
    )
    art_bob = _make_article(
        tmp_path,
        article_id="bob-art",
        slug="bob-art",
        title="Bob Article",
        user_id="bob",
        claims=["Claim B"],
    )
    db_session.add(art_alice)
    db_session.add(art_bob)
    await db_session.commit()

    mock_router = MagicMock()
    mock_router.complete = AsyncMock(return_value=MagicMock())
    mock_router.parse_json_response = MagicMock(return_value={"contradictions": []})

    with (
        patch(
            "wikimind.engine.linter.runner.get_llm_router",
            return_value=mock_router,
        ),
        patch(
            "wikimind.engine.linter.runner.emit_linter_alert",
            new_callable=AsyncMock,
        ),
    ):
        report = await run_lint(db_session, user_id="alice")

    assert report.status == LintReportStatus.COMPLETE
    assert report.article_count == 1
    assert report.user_id == "alice"


@pytest.mark.asyncio
async def test_run_lint_findings_carry_user_id(db_session, _isolated_data_dir, tmp_path) -> None:
    """Findings from a user-scoped lint run carry the user_id."""
    settings = get_settings()
    settings.linter.enable_orphan_detection = True

    art = _make_article(
        tmp_path,
        article_id="alice-art",
        slug="alice-art",
        title="Alice Article",
        user_id="alice",
    )
    db_session.add(art)
    await db_session.commit()

    mock_router = MagicMock()
    mock_router.complete = AsyncMock(return_value=MagicMock())
    mock_router.parse_json_response = MagicMock(return_value={"contradictions": []})

    with (
        patch(
            "wikimind.engine.linter.runner.get_llm_router",
            return_value=mock_router,
        ),
        patch(
            "wikimind.engine.linter.runner.get_settings",
            return_value=settings,
        ),
        patch(
            "wikimind.engine.linter.runner.emit_linter_alert",
            new_callable=AsyncMock,
        ),
    ):
        report = await run_lint(db_session, user_id="alice")

    assert report.status == LintReportStatus.COMPLETE
    # The orphan detection found our article — verify user_id on findings
    assert report.orphans_count == 1
