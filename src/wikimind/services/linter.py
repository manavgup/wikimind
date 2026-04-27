"""Linter service — thin persistence/query layer for lint reports and findings.

All check logic lives in ``engine/linter/``. This service handles report
retrieval, finding dismissal, and triggering lint runs via the background
job system.
"""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING

from fastapi import HTTPException
from sqlmodel import select

from wikimind._datetime import utcnow_naive
from wikimind.jobs.background import get_background_compiler
from wikimind.models import (
    Backlink,
    ContradictionFinding,
    DismissedFinding,
    DismissFindingResponse,
    LintFindingKind,
    LintReport,
    LintReportDetail,
    LintRunResponse,
    OrphanFinding,
    RelationType,
    StructuralFinding,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class LinterService:
    """Coordinate lint report queries, finding dismissal, and run triggers."""

    async def trigger_run(self, user_id: str | None = None) -> LintRunResponse:
        """Schedule a lint run via the background job system.

        Returns:
            LintRunResponse with status indicating the run was scheduled.
        """
        bg = get_background_compiler()
        await bg.schedule_lint(user_id=user_id)
        return LintRunResponse(status="in_progress")

    async def list_reports(
        self, session: AsyncSession, limit: int = 20, user_id: str | None = None
    ) -> list[LintReport]:
        """List lint reports ordered by generated_at DESC.

        Args:
            session: Async database session.
            limit: Maximum number of reports to return.
            user_id: Optional user ID filter.

        Returns:
            List of LintReport records.
        """
        stmt = (
            select(LintReport)
            .order_by(LintReport.generated_at.desc())  # type: ignore[attr-defined]
            .limit(limit)
        )
        if user_id:
            stmt = stmt.where(LintReport.user_id == user_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_report(
        self,
        session: AsyncSession,
        report_id: str,
        *,
        include_dismissed: bool = False,
        user_id: str | None = None,
    ) -> LintReportDetail:
        """Get a single report with all its findings.

        Args:
            session: Async database session.
            report_id: The report UUID.
            include_dismissed: If True, include dismissed findings.
            user_id: Optional user ID for ownership verification.

        Returns:
            LintReportDetail with report metadata and grouped findings.

        Raises:
            HTTPException: 404 if report not found or not owned by user.
        """
        report = await session.get(LintReport, report_id)
        if not report:
            raise HTTPException(status_code=404, detail="Lint report not found")
        if user_id and report.user_id != user_id:
            raise HTTPException(status_code=404, detail="Lint report not found")

        contradiction_query = select(ContradictionFinding).where(ContradictionFinding.report_id == report_id)
        orphan_query = select(OrphanFinding).where(OrphanFinding.report_id == report_id)
        structural_query = select(StructuralFinding).where(StructuralFinding.report_id == report_id)

        if not include_dismissed:
            contradiction_query = contradiction_query.where(
                ContradictionFinding.dismissed == False  # noqa: E712
            )
            orphan_query = orphan_query.where(
                OrphanFinding.dismissed == False  # noqa: E712
            )
            structural_query = structural_query.where(
                StructuralFinding.dismissed == False  # noqa: E712
            )

        contradictions_result = await session.execute(contradiction_query)
        orphans_result = await session.execute(orphan_query)
        structurals_result = await session.execute(structural_query)

        contradictions = list(contradictions_result.scalars().all())
        resolutions = await self._get_resolutions(session, contradictions)

        return LintReportDetail(
            report=report,
            contradictions=contradictions,
            orphans=list(orphans_result.scalars().all()),
            resolutions=resolutions,
            structurals=list(structurals_result.scalars().all()),
        )

    async def _get_resolutions(
        self,
        session: AsyncSession,
        contradictions: list[ContradictionFinding],
    ) -> dict[str, str]:
        """Look up contradiction resolutions from the Backlink table.

        Returns a dict keyed by "article_a_id|article_b_id" → resolution string.
        """
        resolutions: dict[str, str] = {}
        for finding in contradictions:
            a_id, b_id = finding.article_a_id, finding.article_b_id
            for src, tgt in [(a_id, b_id), (b_id, a_id)]:
                result = await session.execute(
                    select(Backlink).where(
                        Backlink.source_article_id == src,
                        Backlink.target_article_id == tgt,
                        Backlink.relation_type == RelationType.CONTRADICTS,
                    )
                )
                bl = result.scalars().first()
                if bl and bl.resolution:
                    resolutions[f"{a_id}|{b_id}"] = bl.resolution
                    break
        return resolutions

    async def get_latest(self, session: AsyncSession, user_id: str | None = None) -> LintReportDetail:
        """Get the most recent lint report with findings.

        Args:
            session: Async database session.
            user_id: Optional user ID filter.

        Returns:
            LintReportDetail for the latest report.

        Raises:
            HTTPException: 404 if no reports exist.
        """
        latest_stmt = (
            select(LintReport)
            .order_by(LintReport.generated_at.desc())  # type: ignore[attr-defined]
            .limit(1)
        )
        if user_id:
            latest_stmt = latest_stmt.where(LintReport.user_id == user_id)
        result = await session.execute(latest_stmt)
        report = result.scalars().first()
        if not report:
            raise HTTPException(status_code=404, detail="No lint reports exist yet")

        return await self.get_report(session, report.id, user_id=user_id)

    async def dismiss_finding(
        self,
        session: AsyncSession,
        kind: LintFindingKind,
        finding_id: str,
        *,
        user_id: str | None = None,
    ) -> DismissFindingResponse:
        """Dismiss a finding and record it for cross-run suppression.

        Args:
            session: Async database session.
            kind: The finding kind (determines which table to query).
            finding_id: The finding UUID.
            user_id: Optional user ID for auth enforcement (ownership
                verification deferred to Issue #344).

        Returns:
            DismissFindingResponse confirming dismissal.

        Raises:
            HTTPException: 404 if finding not found.
        """
        _ = user_id  # TODO(#344): add finding ownership check

        now = utcnow_naive()

        finding: ContradictionFinding | OrphanFinding | StructuralFinding | None
        if kind == LintFindingKind.CONTRADICTION:
            finding = await session.get(ContradictionFinding, finding_id)
        elif kind == LintFindingKind.ORPHAN:
            finding = await session.get(OrphanFinding, finding_id)
        elif kind == LintFindingKind.STRUCTURAL:
            finding = await session.get(StructuralFinding, finding_id)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown finding kind: {kind}")

        if not finding:
            raise HTTPException(status_code=404, detail="Finding not found")

        finding.dismissed = True
        finding.dismissed_at = now
        session.add(finding)

        # Update parent report counts
        report = await session.get(LintReport, finding.report_id)
        if report:
            if kind == LintFindingKind.CONTRADICTION:
                report.contradictions_count = max(0, report.contradictions_count - 1)
            elif kind == LintFindingKind.ORPHAN:
                report.orphans_count = max(0, report.orphans_count - 1)
            elif kind == LintFindingKind.STRUCTURAL:
                report.structural_count = max(0, report.structural_count - 1)
            report.total_findings = max(0, report.total_findings - 1)
            report.dismissed_count += 1
            session.add(report)

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

        return DismissFindingResponse(
            dismissed=True,
            kind=kind.value,
            finding_id=finding_id,
        )


@functools.lru_cache(maxsize=1)
def get_linter_service() -> LinterService:
    """Return a singleton LinterService instance."""
    return LinterService()
