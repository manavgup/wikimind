"""Lint runner — orchestrates all checks and persists results.

The top-level ``run_lint`` function creates a ``LintReport``, dispatches
each check, persists findings, updates the report, and emits a WebSocket
event on completion.
"""

from __future__ import annotations

import structlog
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

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
    all_hashes: set[str] = set()
    for f in contradictions:
        all_hashes.add(f.content_hash)
    for f in orphans:
        all_hashes.add(f.content_hash)

    if not all_hashes:
        return

    result = await session.execute(
        select(DismissedFinding.content_hash).where(
            DismissedFinding.content_hash.in_(all_hashes)  # type: ignore[union-attr]
        )
    )
    dismissed_hashes = {row[0] for row in result.fetchall()}

    now = utcnow_naive()
    for f in contradictions:
        if f.content_hash in dismissed_hashes:
            f.dismissed = True
            f.dismissed_at = now
    for f in orphans:
        if f.content_hash in dismissed_hashes:
            f.dismissed = True
            f.dismissed_at = now


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
        contradictions = await detect_contradictions(session, router, settings, report.id)
        orphans = await detect_orphans(session, settings, report.id)

        # Apply dismiss suppression
        await _apply_dismiss_suppression(session, contradictions, orphans)

        # Persist findings
        for f in contradictions:
            session.add(f)
        for f in orphans:
            session.add(f)

        # Update report
        report.status = LintReportStatus.COMPLETE
        report.completed_at = utcnow_naive()
        report.contradictions_count = len(contradictions)
        report.orphans_count = len(orphans)
        report.total_findings = len(contradictions) + len(orphans)
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
