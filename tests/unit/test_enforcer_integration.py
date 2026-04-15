"""Tests for the backlink enforcer integration with the lint pipeline (PR 2)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlmodel import select

from wikimind.engine.linter.runner import run_lint
from wikimind.models import Article, Backlink, LintReportStatus, PageType, RelationType, StructuralFinding
from wikimind.services.linter import LinterService


def _make_article(
    tmp_path: Path,
    *,
    article_id: str = "a1",
    slug: str = "test-article",
    title: str = "Test Article",
    concept_ids: list[str] | None = None,
    page_type: PageType = PageType.SOURCE,
    claims: list[str] | None = None,
) -> Article:
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
        page_type=page_type,
    )


@pytest.mark.asyncio
async def test_lint_run_includes_structural_findings(db_session, _isolated_data_dir, tmp_path) -> None:
    """A source article with no concepts produces a structural violation in the report."""
    art = _make_article(
        tmp_path,
        article_id="s1",
        slug="no-concepts",
        title="No Concepts Source",
        concept_ids=None,
        page_type=PageType.SOURCE,
    )
    db_session.add(art)
    await db_session.commit()
    mock_router = MagicMock()
    mock_router.complete = AsyncMock(return_value=MagicMock())
    mock_router.parse_json_response = MagicMock(return_value={"contradictions": []})
    with (
        patch("wikimind.engine.linter.runner.get_llm_router", return_value=mock_router),
        patch("wikimind.engine.linter.runner.emit_linter_alert", new_callable=AsyncMock),
    ):
        report = await run_lint(db_session)
    assert report.status == LintReportStatus.COMPLETE
    assert report.structural_count >= 1
    assert report.checked_articles == 1
    result = await db_session.execute(select(StructuralFinding).where(StructuralFinding.report_id == report.id))
    findings = list(result.scalars().all())
    assert len(findings) >= 1
    assert any(f.violation_type == "source_no_concepts" for f in findings)


@pytest.mark.asyncio
async def test_lint_run_auto_repairs_missing_inverse(db_session, _isolated_data_dir, tmp_path) -> None:
    """A one-directional contradicts link gets auto-repaired with auto_repaired=True."""
    art_a = _make_article(tmp_path, article_id="a1", slug="art-a", title="Art A", concept_ids=["c1"])
    art_b = _make_article(tmp_path, article_id="a2", slug="art-b", title="Art B", concept_ids=["c1"])
    db_session.add(art_a)
    db_session.add(art_b)
    bl = Backlink(
        source_article_id="a1", target_article_id="a2", relation_type=RelationType.CONTRADICTS, context="claim conflict"
    )
    db_session.add(bl)
    await db_session.commit()
    mock_router = MagicMock()
    mock_router.complete = AsyncMock(return_value=MagicMock())
    mock_router.parse_json_response = MagicMock(return_value={"contradictions": []})
    with (
        patch("wikimind.engine.linter.runner.get_llm_router", return_value=mock_router),
        patch("wikimind.engine.linter.runner.emit_linter_alert", new_callable=AsyncMock),
    ):
        report = await run_lint(db_session)
    assert report.status == LintReportStatus.COMPLETE
    result = await db_session.execute(
        select(StructuralFinding).where(
            StructuralFinding.report_id == report.id, StructuralFinding.violation_type == "missing_inverse_link"
        )
    )
    findings = list(result.scalars().all())
    assert len(findings) >= 1
    assert findings[0].auto_repaired is True
    bl_result = await db_session.execute(
        select(Backlink).where(Backlink.source_article_id == "a2", Backlink.target_article_id == "a1")
    )
    inverse = bl_result.scalars().first()
    assert inverse is not None
    assert inverse.relation_type == RelationType.CONTRADICTS


@pytest.mark.asyncio
async def test_structural_findings_in_report_detail(db_session, _isolated_data_dir, tmp_path) -> None:
    """LintReportDetail includes structurals when queried via the service."""
    art = _make_article(
        tmp_path,
        article_id="s1",
        slug="no-concepts",
        title="No Concepts Source",
        concept_ids=None,
        page_type=PageType.SOURCE,
    )
    db_session.add(art)
    await db_session.commit()
    mock_router = MagicMock()
    mock_router.complete = AsyncMock(return_value=MagicMock())
    mock_router.parse_json_response = MagicMock(return_value={"contradictions": []})
    with (
        patch("wikimind.engine.linter.runner.get_llm_router", return_value=mock_router),
        patch("wikimind.engine.linter.runner.emit_linter_alert", new_callable=AsyncMock),
    ):
        report = await run_lint(db_session)
    svc = LinterService()
    detail = await svc.get_report(db_session, report.id)
    assert hasattr(detail, "structurals")
    assert len(detail.structurals) >= 1
    assert detail.structurals[0].violation_type == "source_no_concepts"
    assert detail.report.structural_count >= 1
