"""Lint runner — orchestrates all checks and persists results.

The top-level ``run_lint`` function creates a ``LintReport``, dispatches
each check, persists findings, updates the report, and emits a WebSocket
event on completion.
"""

from __future__ import annotations

import structlog
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from wikimind._datetime import utcnow_naive
from wikimind.api.routes.ws import emit_linter_alert
from wikimind.config import get_settings
from wikimind.engine.linter.contradictions import detect_contradictions
from wikimind.engine.linter.orphans import detect_orphans
from wikimind.engine.llm_router import get_llm_router
from wikimind.models import (
    Article,
    ContradictionFinding,
    DismissedFinding,
    LintReport,
    LintReportStatus,
    OrphanFinding,
)

log = structlog.get_logger()


async def _apply_dismiss_suppression(
    session: AsyncSession,
    contradictions: list[ContradictionFinding],
    orphans: list[OrphanFinding],
) -> None:
    """Mark findings as dismissed if their content_hash exists in DismissedFinding."""
    all_findings: list[ContradictionFinding | OrphanFinding] = [
        *contradictions,
        *orphans,
    ]
    all_hashes = {f.content_hash for f in all_findings}

    if not all_hashes:
        return

    result = await session.execute(
        select(DismissedFinding.content_hash).where(
            DismissedFinding.content_hash.in_(all_hashes)  # type: ignore[attr-defined]
        )
    )
    dismissed_hashes = {row[0] for row in result.fetchall()}

    now = utcnow_naive()
    for finding in all_findings:
        if finding.content_hash in dismissed_hashes:
            finding.dismissed = True
            finding.dismissed_at = now


async def run_lint(session: AsyncSession, job_id: str | None = None) -> LintReport:
    """Run the full lint pipeline: create report, run checks, persist, emit events.

    Args:
        session: Async database session.
        job_id: Optional Job ID to link the report to.

    Returns:
        The completed LintReport.
    """
    settings = get_settings()
    router = get_llm_router()

    # Guard against concurrent runs
    existing = await session.execute(
        select(LintReport).where(LintReport.status == LintReportStatus.IN_PROGRESS)
    )
    in_progress = existing.scalars().first()
    if in_progress:
        log.info("Lint run already in progress", report_id=in_progress.id)
        return in_progress

    # Snapshot article count
    count_result = await session.execute(select(func.count()).select_from(Article))
    article_count = count_result.scalar() or 0

    # Create report
    report = LintReport(
        status=LintReportStatus.IN_PROGRESS,
        article_count=article_count,
        job_id=job_id,
    )
    session.add(report)
    await session.flush()

    try:
        # Run checks
        contradictions = await detect_contradictions(session, router, settings, report)
        orphans = await detect_orphans(session, settings, report.id)

        # Apply dismiss suppression
        await _apply_dismiss_suppression(session, contradictions, orphans)

        # Persist findings
        for cf in contradictions:
            session.add(cf)
        for of in orphans:
            session.add(of)

        # Update report — count only active (non-dismissed) findings
        active_contradictions = [c for c in contradictions if not c.dismissed]
        active_orphans = [o for o in orphans if not o.dismissed]
        dismissed = (len(contradictions) - len(active_contradictions)) + (len(orphans) - len(active_orphans))

        report.status = LintReportStatus.COMPLETE
        report.completed_at = utcnow_naive()
        report.contradictions_count = len(active_contradictions)
        report.orphans_count = len(active_orphans)
        report.total_findings = len(active_contradictions) + len(active_orphans)
        report.dismissed_count = dismissed
        session.add(report)
        await session.commit()

        log.info(
            "Lint run complete",
            report_id=report.id,
            contradictions=len(contradictions),
            orphans=len(orphans),
        )

        # Emit WebSocket alert
        if contradictions:
            article_titles: list[str] = []
            for c in contradictions:
                if not c.dismissed:
                    article_titles.append(c.description)
            if article_titles:
                await emit_linter_alert("contradiction", article_titles)

    except Exception as e:
        log.error("Lint run failed", error=str(e), exc_info=True)
        report.status = LintReportStatus.FAILED
        report.error_message = str(e)
        report.completed_at = utcnow_naive()
        session.add(report)
        await session.commit()

    return report
