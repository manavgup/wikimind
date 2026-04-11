"""Endpoints for the wiki linter — structured health audit reports and findings."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.database import get_session
from wikimind.models import LintFindingKind, LintReport, LintReportDetail
from wikimind.services.linter import LinterService, get_linter_service

router = APIRouter()


@router.post("/run")
async def run_lint(
    service: LinterService = Depends(get_linter_service),
):
    """Trigger a new lint run. Returns immediately with status."""
    return await service.trigger_run()


@router.get("/reports", response_model=list[LintReport])
async def list_reports(
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    service: LinterService = Depends(get_linter_service),
):
    """List lint reports ordered by most recent first."""
    return await service.list_reports(session, limit=limit)


@router.get("/reports/latest", response_model=LintReportDetail)
async def get_latest_report(
    session: AsyncSession = Depends(get_session),
    service: LinterService = Depends(get_linter_service),
):
    """Get the most recent lint report with all non-dismissed findings."""
    return await service.get_latest(session)


@router.get("/reports/{report_id}", response_model=LintReportDetail)
async def get_report(
    report_id: str,
    include_dismissed: bool = False,
    session: AsyncSession = Depends(get_session),
    service: LinterService = Depends(get_linter_service),
):
    """Get a specific lint report with findings."""
    return await service.get_report(session, report_id, include_dismissed=include_dismissed)


@router.post("/findings/{kind}/{finding_id}/dismiss")
async def dismiss_finding(
    kind: LintFindingKind,
    finding_id: str,
    session: AsyncSession = Depends(get_session),
    service: LinterService = Depends(get_linter_service),
):
    """Dismiss a finding. Persists across future lint runs via content hash."""
    return await service.dismiss_finding(session, kind, finding_id)
