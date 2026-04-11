"""Linter service — thin persistence/query layer for lint reports and findings.

All check logic lives in ``engine/linter/``. This service handles report
retrieval, finding dismissal, and triggering lint runs via the background
job system.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind._datetime import utcnow_naive
from wikimind.jobs.background import get_background_compiler
from wikimind.models import (
    ContradictionFinding,
    DismissedFinding,
    LintFindingKind,
    LintReport,
    LintReportDetail,
    OrphanFinding,
)


class LinterService:
    """Coordinate lint report queries, finding dismissal, and run triggers."""

    async def trigger_run(self) -> dict[str, str]:
        """Schedule a lint run via the background job system.

        Returns:
            Dict with status indicating the run was scheduled.
        """
        bg = get_background_compiler()
        await bg.schedule_lint()
        return {"status": "in_progress"}

    async def list_reports(self, session: AsyncSession, limit: int = 20) -> list[LintReport]:
        """List lint reports ordered by generated_at DESC.

        Args:
            session: Async database session.
            limit: Maximum number of reports to return.

        Returns:
            List of LintReport records.
        """
        result = await session.execute(
            select(LintReport)
            .order_by(LintReport.generated_at.desc())  # type: ignore[attr-defined]
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_report(
        self,
        session: AsyncSession,
        report_id: str,
        *,
        include_dismissed: bool = False,
    ) -> LintReportDetail:
        """Get a single report with all its findings.

        Args:
            session: Async database session.
            report_id: The report UUID.
            include_dismissed: If True, include dismissed findings.

        Returns:
            LintReportDetail with report metadata and grouped findings.

        Raises:
            HTTPException: 404 if report not found.
        """
        report = await session.get(LintReport, report_id)
        if not report:
            raise HTTPException(status_code=404, detail="Lint report not found")

        contradiction_query = select(ContradictionFinding).where(ContradictionFinding.report_id == report_id)
        orphan_query = select(OrphanFinding).where(OrphanFinding.report_id == report_id)

        if not include_dismissed:
            contradiction_query = contradiction_query.where(
                ContradictionFinding.dismissed == False  # noqa: E712
            )
            orphan_query = orphan_query.where(
                OrphanFinding.dismissed == False  # noqa: E712
            )

        contradictions_result = await session.execute(contradiction_query)
        orphans_result = await session.execute(orphan_query)

        return LintReportDetail(
            report=report,
            contradictions=list(contradictions_result.scalars().all()),
            orphans=list(orphans_result.scalars().all()),
        )

    async def get_latest(self, session: AsyncSession) -> LintReportDetail:
        """Get the most recent lint report with findings.

        Returns:
            LintReportDetail for the latest report.

        Raises:
            HTTPException: 404 if no reports exist.
        """
        result = await session.execute(
            select(LintReport)
            .order_by(LintReport.generated_at.desc())  # type: ignore[attr-defined]
            .limit(1)
        )
        report = result.scalars().first()
        if not report:
            raise HTTPException(status_code=404, detail="No lint reports exist yet")

        return await self.get_report(session, report.id)

    async def dismiss_finding(
        self,
        session: AsyncSession,
        kind: LintFindingKind,
        finding_id: str,
    ) -> dict[str, object]:
        """Dismiss a finding and record it for cross-run suppression.

        Args:
            session: Async database session.
            kind: The finding kind (determines which table to query).
            finding_id: The finding UUID.

        Returns:
            Dict confirming dismissal.

        Raises:
            HTTPException: 404 if finding not found.
        """
        now = utcnow_naive()

        if kind == LintFindingKind.CONTRADICTION:
            finding = await session.get(ContradictionFinding, finding_id)
        elif kind == LintFindingKind.ORPHAN:
            finding = await session.get(OrphanFinding, finding_id)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown finding kind: {kind}")

        if not finding:
            raise HTTPException(status_code=404, detail="Finding not found")

        finding.dismissed = True
        finding.dismissed_at = now
        session.add(finding)

        # Record in DismissedFinding for cross-run suppression
        existing = await session.get(DismissedFinding, finding.content_hash)
        if not existing:
            dismissed_record = DismissedFinding(
                content_hash=finding.content_hash,
                kind=kind,
                dismissed_at=now,
            )
            session.add(dismissed_record)

        await session.commit()

        return {
            "dismissed": True,
            "kind": kind,
            "finding_id": finding_id,
        }


_linter_service: LinterService | None = None


def get_linter_service() -> LinterService:
    """Return a singleton LinterService instance."""
    global _linter_service
    if _linter_service is None:
        _linter_service = LinterService()
    return _linter_service
