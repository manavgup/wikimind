"""Tests for the wiki linter engine, service, and API routes."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from wikimind._datetime import utcnow_naive
from wikimind.config import get_settings
from wikimind.engine.linter.contradictions import detect_contradictions
from wikimind.engine.linter.orphans import detect_orphans
from wikimind.engine.linter.runner import run_lint
from wikimind.models import (
    Article,
    Backlink,
    Concept,
    ContradictionFinding,
    DismissedFinding,
    LintFindingKind,
    LintReport,
    LintReportStatus,
    LintSeverity,
)
from wikimind.services.linter import LinterService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_article(
    tmp_path: Path,
    *,
    article_id: str = "a1",
    slug: str = "test-article",
    title: str = "Test Article",
    concept_ids: list[str] | None = None,
    claims: list[str] | None = None,
) -> Article:
    """Create an Article with a real .md file containing claims."""
    file_path = tmp_path / f"{slug}.md"
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
        file_path=str(file_path),
        concept_ids=json.dumps(concept_ids) if concept_ids else None,
    )


# ---------------------------------------------------------------------------
# detect_contradictions tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_contradictions_single_concept(db_session, _isolated_data_dir, tmp_path) -> None:
    """Two articles with contradictory claims produce a ContradictionFinding."""
    concept = Concept(id="c1", name="testing", article_count=2)
    db_session.add(concept)

    art_a = _make_article(
        tmp_path,
        article_id="a1",
        slug="article-a",
        title="Article A",
        concept_ids=["testing"],
        claims=["The sky is blue"],
    )
    art_b = _make_article(
        tmp_path,
        article_id="a2",
        slug="article-b",
        title="Article B",
        concept_ids=["testing"],
        claims=["The sky is green"],
    )
    db_session.add(art_a)
    db_session.add(art_b)
    await db_session.commit()

    # Mock the LLM router
    mock_response = MagicMock()
    mock_router = MagicMock()
    mock_router.complete = AsyncMock(return_value=mock_response)
    mock_router.parse_json_response = MagicMock(
        return_value={
            "contradictions": [
                {
                    "description": "Sky color contradiction",
                    "article_a_claim": "The sky is blue",
                    "article_b_claim": "The sky is green",
                    "confidence": "high",
                }
            ]
        }
    )

    settings = get_settings()
    report = LintReport(id="r1")
    db_session.add(report)
    await db_session.flush()
    findings = await detect_contradictions(db_session, mock_router, settings, report)

    assert len(findings) == 1
    assert findings[0].description == "Sky color contradiction"
    assert findings[0].article_a_id == "a1"
    assert findings[0].article_b_id == "a2"
    assert findings[0].llm_confidence == "high"
    assert findings[0].report_id == "r1"
    assert findings[0].content_hash  # non-empty


@pytest.mark.asyncio
async def test_detect_contradictions_no_contradictions(db_session, _isolated_data_dir, tmp_path) -> None:
    """Two articles with no contradictions produce zero findings."""
    concept = Concept(id="c1", name="testing", article_count=2)
    db_session.add(concept)

    art_a = _make_article(
        tmp_path,
        article_id="a1",
        slug="article-a",
        title="Article A",
        concept_ids=["testing"],
        claims=["The sky is blue"],
    )
    art_b = _make_article(
        tmp_path,
        article_id="a2",
        slug="article-b",
        title="Article B",
        concept_ids=["testing"],
        claims=["Water is wet"],
    )
    db_session.add(art_a)
    db_session.add(art_b)
    await db_session.commit()

    mock_router = MagicMock()
    mock_router.complete = AsyncMock(return_value=MagicMock())
    mock_router.parse_json_response = MagicMock(return_value={"contradictions": []})

    settings = get_settings()
    report = LintReport(id="r1")
    db_session.add(report)
    await db_session.flush()
    findings = await detect_contradictions(db_session, mock_router, settings, report)

    assert len(findings) == 0


@pytest.mark.asyncio
async def test_detect_contradictions_respects_pair_cap(db_session, _isolated_data_dir, tmp_path) -> None:
    """Pair cap limits the number of LLM calls."""
    concept = Concept(id="c1", name="testing", article_count=5)
    db_session.add(concept)

    for i in range(5):
        art = _make_article(
            tmp_path,
            article_id=f"a{i}",
            slug=f"article-{i}",
            title=f"Article {i}",
            concept_ids=["testing"],
            claims=[f"Claim {i}"],
        )
        db_session.add(art)
    await db_session.commit()

    mock_router = MagicMock()
    mock_router.complete = AsyncMock(return_value=MagicMock())
    mock_router.parse_json_response = MagicMock(return_value={"contradictions": []})

    settings = get_settings()
    # Set cap very low
    settings.linter.max_contradiction_pairs_per_concept = 2
    # Disable batching so each pair = one LLM call
    settings.linter.contradiction_batch_enabled = False

    report = LintReport(id="r1")
    db_session.add(report)
    await db_session.flush()
    await detect_contradictions(db_session, mock_router, settings, report)

    # 5 articles = 10 pairs, capped at 2
    assert mock_router.complete.call_count <= 2


# ---------------------------------------------------------------------------
# detect_orphans tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_orphans_returns_empty_when_disabled(db_session, _isolated_data_dir) -> None:
    """Orphan detection returns empty when enable_orphan_detection=False."""
    settings = get_settings()
    settings.linter.enable_orphan_detection = False

    findings = await detect_orphans(db_session, settings, report_id="r1")

    assert len(findings) == 0


@pytest.mark.asyncio
async def test_detect_orphans_finds_unlinked_article(db_session, _isolated_data_dir, tmp_path) -> None:
    """An article with no backlinks is detected as an orphan."""
    # Create one linked article and one orphan
    art_linked = _make_article(tmp_path, article_id="linked", slug="linked", title="Linked")
    art_orphan = _make_article(tmp_path, article_id="orphan", slug="orphan", title="Orphan")
    db_session.add(art_linked)
    db_session.add(art_orphan)

    # Create a backlink for the linked article
    backlink = Backlink(
        source_article_id="linked",
        target_article_id="linked",
        context="self-link",
    )
    db_session.add(backlink)
    await db_session.commit()

    settings = get_settings()
    settings.linter.enable_orphan_detection = True

    findings = await detect_orphans(db_session, settings, report_id="r1")

    assert len(findings) == 1
    assert findings[0].article_id == "orphan"
    assert findings[0].article_title == "Orphan"


# ---------------------------------------------------------------------------
# run_lint integration test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_lint_creates_report_with_correct_counts(db_session, _isolated_data_dir, tmp_path) -> None:
    """Full lint run creates a report with correct finding counts."""
    concept = Concept(id="c1", name="testing", article_count=2)
    db_session.add(concept)

    art_a = _make_article(
        tmp_path,
        article_id="a1",
        slug="article-a",
        title="Article A",
        concept_ids=["testing"],
        claims=["Claim A"],
    )
    art_b = _make_article(
        tmp_path,
        article_id="a2",
        slug="article-b",
        title="Article B",
        concept_ids=["testing"],
        claims=["Claim B"],
    )
    db_session.add(art_a)
    db_session.add(art_b)
    await db_session.commit()

    mock_response = MagicMock()
    mock_router = MagicMock()
    mock_router.complete = AsyncMock(return_value=mock_response)
    mock_router.parse_json_response = MagicMock(
        return_value={
            "contradictions": [
                {
                    "description": "A vs B",
                    "article_a_claim": "Claim A",
                    "article_b_claim": "Claim B",
                    "confidence": "medium",
                }
            ]
        }
    )

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
        report = await run_lint(db_session)

    assert report.status == LintReportStatus.COMPLETE
    assert report.contradictions_count == 1
    assert report.orphans_count == 0  # Phase 4: contradiction detection now creates backlinks
    assert report.total_findings == 1  # 1 contradiction (articles no longer orphaned)
    assert report.article_count == 2


@pytest.mark.asyncio
async def test_run_lint_sets_status_failed_on_exception(db_session, _isolated_data_dir) -> None:
    """A failing check sets the report to FAILED with error_message."""
    with (
        patch(
            "wikimind.engine.linter.runner.get_llm_router",
            return_value=MagicMock(),
        ),
        patch(
            "wikimind.engine.linter.runner.detect_contradictions",
            new_callable=AsyncMock,
            side_effect=RuntimeError("LLM exploded"),
        ),
        patch(
            "wikimind.engine.linter.runner.emit_linter_alert",
            new_callable=AsyncMock,
        ),
    ):
        report = await run_lint(db_session)

    assert report.status == LintReportStatus.FAILED
    assert "LLM exploded" in (report.error_message or "")


# ---------------------------------------------------------------------------
# Dismiss semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dismiss_finding_persists_and_suppresses_on_next_run(db_session, _isolated_data_dir, tmp_path) -> None:
    """Dismissing a finding records a DismissedFinding that suppresses it on the next run."""
    # Create a report and a contradiction finding
    report = LintReport(
        id="r1",
        status=LintReportStatus.COMPLETE,
        article_count=2,
    )
    db_session.add(report)

    art_a = _make_article(tmp_path, article_id="a1", slug="art-a", title="Art A")
    art_b = _make_article(tmp_path, article_id="a2", slug="art-b", title="Art B")
    db_session.add(art_a)
    db_session.add(art_b)

    finding = ContradictionFinding(
        id="f1",
        report_id="r1",
        severity=LintSeverity.WARN,
        description="Test contradiction",
        content_hash="hash123",
        article_a_id="a1",
        article_b_id="a2",
        article_a_claim="claim a",
        article_b_claim="claim b",
        llm_confidence="high",
    )
    db_session.add(finding)
    await db_session.commit()

    # Dismiss the finding
    svc = LinterService()
    result = await svc.dismiss_finding(db_session, LintFindingKind.CONTRADICTION, "f1")

    assert result["dismissed"] is True

    # Check DismissedFinding was created
    dismissed = await db_session.get(DismissedFinding, "hash123")
    assert dismissed is not None
    assert dismissed.kind == LintFindingKind.CONTRADICTION


# ---------------------------------------------------------------------------
# LinterService tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_linter_service_list_reports(db_session, _isolated_data_dir) -> None:
    """list_reports returns reports ordered by generated_at DESC."""
    r1 = LintReport(id="r1", status=LintReportStatus.COMPLETE, article_count=5)
    r2 = LintReport(id="r2", status=LintReportStatus.COMPLETE, article_count=10)
    db_session.add(r1)
    db_session.add(r2)
    await db_session.commit()

    svc = LinterService()
    reports = await svc.list_reports(db_session, limit=10)

    assert len(reports) == 2


@pytest.mark.asyncio
async def test_linter_service_get_latest_returns_404_when_empty(db_session, _isolated_data_dir) -> None:
    """get_latest raises 404 when no reports exist."""
    svc = LinterService()
    with pytest.raises(HTTPException) as exc_info:
        await svc.get_latest(db_session)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_linter_service_get_report_filters_dismissed(db_session, _isolated_data_dir, tmp_path) -> None:
    """get_report with include_dismissed=False filters out dismissed findings."""
    report = LintReport(id="r1", status=LintReportStatus.COMPLETE, article_count=2)
    db_session.add(report)

    art_a = _make_article(tmp_path, article_id="a1", slug="art-a", title="Art A")
    art_b = _make_article(tmp_path, article_id="a2", slug="art-b", title="Art B")
    db_session.add(art_a)
    db_session.add(art_b)

    f1 = ContradictionFinding(
        id="f1",
        report_id="r1",
        description="Active finding",
        content_hash="h1",
        article_a_id="a1",
        article_b_id="a2",
        article_a_claim="c1",
        article_b_claim="c2",
        llm_confidence="high",
        dismissed=False,
    )
    f2 = ContradictionFinding(
        id="f2",
        report_id="r1",
        description="Dismissed finding",
        content_hash="h2",
        article_a_id="a1",
        article_b_id="a2",
        article_a_claim="c3",
        article_b_claim="c4",
        llm_confidence="low",
        dismissed=True,
        dismissed_at=utcnow_naive(),
    )
    db_session.add(f1)
    db_session.add(f2)
    await db_session.commit()

    svc = LinterService()

    # Default: exclude dismissed
    detail = await svc.get_report(db_session, "r1")
    assert len(detail.contradictions) == 1
    assert detail.contradictions[0].id == "f1"

    # Include dismissed
    detail_all = await svc.get_report(db_session, "r1", include_dismissed=True)
    assert len(detail_all.contradictions) == 2


# ---------------------------------------------------------------------------
# API route tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lint_run_endpoint_returns_in_progress(client) -> None:
    """POST /lint/run returns status in_progress."""
    with patch("wikimind.services.linter.get_background_compiler") as mock_bg:
        mock_bg.return_value.schedule_lint = AsyncMock(return_value="job-1")
        response = await client.post("/lint/run")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "in_progress"


@pytest.mark.asyncio
async def test_lint_reports_endpoint(client) -> None:
    """GET /lint/reports returns an empty list when no reports exist."""
    response = await client.get("/lint/reports")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_lint_latest_endpoint_returns_404_when_empty(client) -> None:
    """GET /lint/reports/latest returns 404 when no reports exist."""
    response = await client.get("/lint/reports/latest")
    assert response.status_code == 404
