"""Tests for services/linter.py."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from tests.conftest import TEST_USER_ID
from wikimind.errors import NotFoundError
from wikimind.models import (
    ContradictionFinding,
    LintFindingKind,
    LintReport,
    LintReportStatus,
    OrphanFinding,
    StructuralFinding,
)
from wikimind.services.factories import get_linter_service
from wikimind.services.linter import LinterService

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession


def test_singleton():
    get_linter_service.cache_clear()
    assert get_linter_service() is get_linter_service()
    get_linter_service.cache_clear()


async def test_trigger_run():
    mock_bg = AsyncMock()
    mock_bg.schedule_lint = AsyncMock()
    with patch("wikimind.services.linter.get_background_compiler", return_value=mock_bg):
        r = await LinterService().trigger_run(user_id=TEST_USER_ID)
    assert r.status == "in_progress"


async def test_list_reports_empty(db_session: AsyncSession):
    assert await LinterService().list_reports(db_session, user_id=TEST_USER_ID) == []


async def test_get_report_not_found(db_session: AsyncSession):
    with pytest.raises(NotFoundError):
        await LinterService().get_report(db_session, "bad", user_id=TEST_USER_ID)


async def test_get_latest_no_reports(db_session: AsyncSession):
    with pytest.raises(NotFoundError):
        await LinterService().get_latest(db_session, user_id=TEST_USER_ID)


async def test_dismiss_contradiction(db_session: AsyncSession):
    report = LintReport(
        status=LintReportStatus.COMPLETE,
        contradictions_count=1,
        orphans_count=0,
        total_findings=1,
        dismissed_count=0,
        user_id=TEST_USER_ID,
    )
    db_session.add(report)
    await db_session.commit()
    await db_session.refresh(report)
    finding = ContradictionFinding(
        report_id=report.id,
        user_id=TEST_USER_ID,
        article_a_id="a",
        article_b_id="b",
        article_a_claim="X",
        article_b_claim="Y",
        llm_confidence="high",
        description="desc",
        content_hash="h1",
    )
    db_session.add(finding)
    await db_session.commit()
    await db_session.refresh(finding)
    r = await LinterService().dismiss_finding(
        db_session, LintFindingKind.CONTRADICTION, finding.id, user_id=TEST_USER_ID
    )
    assert r.dismissed is True


async def test_dismiss_orphan(db_session: AsyncSession):
    report = LintReport(
        status=LintReportStatus.COMPLETE,
        contradictions_count=0,
        orphans_count=1,
        total_findings=1,
        dismissed_count=0,
        user_id=TEST_USER_ID,
    )
    db_session.add(report)
    await db_session.commit()
    await db_session.refresh(report)
    finding = OrphanFinding(
        report_id=report.id,
        user_id=TEST_USER_ID,
        article_id="a",
        article_title="T",
        description="desc",
        content_hash="h2",
    )
    db_session.add(finding)
    await db_session.commit()
    await db_session.refresh(finding)
    r = await LinterService().dismiss_finding(db_session, LintFindingKind.ORPHAN, finding.id, user_id=TEST_USER_ID)
    assert r.dismissed is True


async def test_dismiss_structural(db_session: AsyncSession):
    report = LintReport(
        status=LintReportStatus.COMPLETE,
        contradictions_count=0,
        orphans_count=0,
        structural_count=1,
        total_findings=1,
        dismissed_count=0,
        user_id=TEST_USER_ID,
    )
    db_session.add(report)
    await db_session.commit()
    await db_session.refresh(report)
    finding = StructuralFinding(
        report_id=report.id,
        user_id=TEST_USER_ID,
        article_id="a",
        violation_type="missing",
        description="desc",
        content_hash="h3",
    )
    db_session.add(finding)
    await db_session.commit()
    await db_session.refresh(finding)
    r = await LinterService().dismiss_finding(db_session, LintFindingKind.STRUCTURAL, finding.id, user_id=TEST_USER_ID)
    assert r.dismissed is True


async def test_dismiss_not_found(db_session: AsyncSession):
    with pytest.raises(NotFoundError):
        await LinterService().dismiss_finding(db_session, LintFindingKind.CONTRADICTION, "bad", user_id=TEST_USER_ID)


async def test_get_report_with_findings(db_session: AsyncSession):
    """get_report should return grouped findings for a valid report."""
    report = LintReport(
        status=LintReportStatus.COMPLETE,
        contradictions_count=1,
        orphans_count=1,
        structural_count=1,
        total_findings=3,
        dismissed_count=0,
        user_id=TEST_USER_ID,
    )
    db_session.add(report)
    await db_session.commit()
    await db_session.refresh(report)

    c = ContradictionFinding(
        report_id=report.id,
        user_id=TEST_USER_ID,
        article_a_id="a1",
        article_b_id="b1",
        article_a_claim="X",
        article_b_claim="Y",
        llm_confidence="high",
        description="contradiction desc",
        content_hash="ch1",
    )
    o = OrphanFinding(
        report_id=report.id,
        user_id=TEST_USER_ID,
        article_id="a2",
        article_title="Orphan",
        description="orphan desc",
        content_hash="oh1",
    )
    s = StructuralFinding(
        report_id=report.id,
        user_id=TEST_USER_ID,
        article_id="a3",
        violation_type="missing_frontmatter",
        description="struct desc",
        content_hash="sh1",
    )
    db_session.add_all([c, o, s])
    await db_session.commit()

    detail = await LinterService().get_report(db_session, report.id, user_id=TEST_USER_ID)
    assert len(detail.contradictions) == 1
    assert len(detail.orphans) == 1
    assert len(detail.structurals) == 1


async def test_get_report_wrong_user(db_session: AsyncSession):
    """get_report should raise NotFoundError for wrong user."""
    report = LintReport(
        status=LintReportStatus.COMPLETE,
        contradictions_count=0,
        orphans_count=0,
        total_findings=0,
        dismissed_count=0,
        user_id=TEST_USER_ID,
    )
    db_session.add(report)
    await db_session.commit()
    await db_session.refresh(report)

    with pytest.raises(NotFoundError):
        await LinterService().get_report(db_session, report.id, user_id="other-user")


async def test_get_report_include_dismissed(db_session: AsyncSession):
    """get_report with include_dismissed=True should include dismissed findings."""
    report = LintReport(
        status=LintReportStatus.COMPLETE,
        contradictions_count=0,
        orphans_count=1,
        total_findings=1,
        dismissed_count=1,
        user_id=TEST_USER_ID,
    )
    db_session.add(report)
    await db_session.commit()
    await db_session.refresh(report)

    finding = OrphanFinding(
        report_id=report.id,
        user_id=TEST_USER_ID,
        article_id="a",
        article_title="T",
        description="dismissed finding",
        content_hash="dh1",
        dismissed=True,
    )
    db_session.add(finding)
    await db_session.commit()

    detail = await LinterService().get_report(db_session, report.id, user_id=TEST_USER_ID)
    assert len(detail.orphans) == 0

    detail = await LinterService().get_report(db_session, report.id, include_dismissed=True, user_id=TEST_USER_ID)
    assert len(detail.orphans) == 1


async def test_get_latest_returns_most_recent(db_session: AsyncSession):
    """get_latest should return the most recent report."""
    r1 = LintReport(
        status=LintReportStatus.COMPLETE,
        contradictions_count=0,
        orphans_count=0,
        total_findings=0,
        dismissed_count=0,
        user_id=TEST_USER_ID,
    )
    db_session.add(r1)
    await db_session.commit()
    await db_session.refresh(r1)

    r2 = LintReport(
        status=LintReportStatus.COMPLETE,
        contradictions_count=1,
        orphans_count=0,
        total_findings=1,
        dismissed_count=0,
        user_id=TEST_USER_ID,
    )
    db_session.add(r2)
    await db_session.commit()
    await db_session.refresh(r2)

    detail = await LinterService().get_latest(db_session, user_id=TEST_USER_ID)
    assert detail.report.id == r2.id


async def test_list_reports_with_user_filter(db_session: AsyncSession):
    """list_reports should filter by user_id."""
    r1 = LintReport(
        status=LintReportStatus.COMPLETE,
        contradictions_count=0,
        orphans_count=0,
        total_findings=0,
        dismissed_count=0,
        user_id=TEST_USER_ID,
    )
    db_session.add(r1)
    await db_session.commit()

    reports = await LinterService().list_reports(db_session, user_id=TEST_USER_ID)
    assert len(reports) == 1

    reports = await LinterService().list_reports(db_session, user_id="other-user")
    assert len(reports) == 0


async def test_dismiss_own_finding_succeeds(db_session: AsyncSession):
    """A user can dismiss a finding that belongs to them."""
    report = LintReport(
        status=LintReportStatus.COMPLETE,
        contradictions_count=0,
        orphans_count=1,
        total_findings=1,
        dismissed_count=0,
        user_id=TEST_USER_ID,
    )
    db_session.add(report)
    await db_session.commit()
    await db_session.refresh(report)

    finding = OrphanFinding(
        report_id=report.id,
        user_id=TEST_USER_ID,
        article_id="a",
        article_title="T",
        description="desc",
        content_hash="own-hash",
    )
    db_session.add(finding)
    await db_session.commit()
    await db_session.refresh(finding)

    result = await LinterService().dismiss_finding(db_session, LintFindingKind.ORPHAN, finding.id, user_id=TEST_USER_ID)
    assert result.dismissed is True
    assert result.finding_id == finding.id


async def test_dismiss_other_users_finding_raises_not_found(db_session: AsyncSession):
    """A user cannot dismiss another user's finding — returns NotFoundError."""
    report = LintReport(
        status=LintReportStatus.COMPLETE,
        contradictions_count=1,
        orphans_count=0,
        total_findings=1,
        dismissed_count=0,
        user_id=TEST_USER_ID,
    )
    db_session.add(report)
    await db_session.commit()
    await db_session.refresh(report)

    finding = ContradictionFinding(
        report_id=report.id,
        user_id=TEST_USER_ID,
        article_a_id="a",
        article_b_id="b",
        article_a_claim="X",
        article_b_claim="Y",
        llm_confidence="high",
        description="desc",
        content_hash="other-hash",
    )
    db_session.add(finding)
    await db_session.commit()
    await db_session.refresh(finding)

    with pytest.raises(NotFoundError):
        await LinterService().dismiss_finding(
            db_session,
            LintFindingKind.CONTRADICTION,
            finding.id,
            user_id="attacker-user",
        )
