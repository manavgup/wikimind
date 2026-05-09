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
from wikimind.services.linter import LinterService, get_linter_service

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
