"""Lint runner — orchestrates all checks and persists results.

The top-level ``run_lint`` function creates a ``LintReport``, dispatches
each check, persists findings, updates the report, and emits a WebSocket
event on completion.
"""

from __future__ import annotations

import hashlib

import structlog
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from wikimind._datetime import utcnow_naive
from wikimind.api.routes.ws import emit_linter_alert
from wikimind.config import get_settings
from wikimind.engine.backlink_enforcer import enforce_backlinks
from wikimind.engine.linter.contradictions import detect_contradictions
from wikimind.engine.linter.orphans import detect_orphans
from wikimind.engine.llm_router import get_llm_router
from wikimind.models import (
    Article,
    ContradictionFinding,
    DismissedFinding,
    LintFindingKind,
    LintReport,
    LintReportStatus,
    LintSeverity,
    OrphanFinding,
    StructuralFinding,
)

log = structlog.get_logger()


def _structural_content_hash(article_id: str, violation_type: str) -> str:
    """Compute a stable sha256 for cross-run dedup of structural findings."""
    raw = f"{LintFindingKind.STRUCTURAL}|{article_id}|{violation_type}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def run_enforcer_checks(session: AsyncSession, report: LintReport) -> list[StructuralFinding]:
    """Run the backlink enforcer on all articles and return StructuralFinding rows.

    Phase 3 of the lint pipeline — runs after contradictions and orphans.
    """
    result = await session.execute(select(Article))
    articles = list(result.scalars().all())

    findings: list[StructuralFinding] = []
    checked = 0

    for article in articles:
        enforcer_result = await enforce_backlinks(article.id, session)
        checked += 1

        for violation in enforcer_result.violations:
            finding = StructuralFinding(
                report_id=report.id,
                severity=LintSeverity.WARN,
                description=violation.detail,
                content_hash=_structural_content_hash(violation.article_id, violation.violation_type),
                article_id=violation.article_id,
                violation_type=violation.violation_type,
                auto_repaired=violation.auto_repaired,
                detail=violation.detail,
            )
            findings.append(finding)

    report.checked_articles = checked
    return findings


async def _apply_dismiss_suppression(
    session: AsyncSession,
    contradictions: list[ContradictionFinding],
    orphans: list[OrphanFinding],
    structurals: list[StructuralFinding] | None = None,
) -> None:
    """Mark findings as dismissed if their content_hash exists in DismissedFinding."""
    all_findings: list[ContradictionFinding | OrphanFinding | StructuralFinding] = [
        *contradictions,
        *orphans,
        *(structurals or []),
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
    existing = await session.execute(select(LintReport).where(LintReport.status == LintReportStatus.IN_PROGRESS))
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
        # Phase 1: Contradictions
        contradictions = await detect_contradictions(session, router, settings, report)

        # Phase 2: Orphans
        orphans = await detect_orphans(session, settings, report.id)

        # Phase 3: Structural integrity (backlink enforcer)
        structurals = await run_enforcer_checks(session, report)

        # Apply dismiss suppression
        await _apply_dismiss_suppression(session, contradictions, orphans, structurals)

        # Persist findings
        for cf in contradictions:
            session.add(cf)
        for of in orphans:
            session.add(of)
        for sf in structurals:
            session.add(sf)

        # Update report — count only active (non-dismissed) findings
        active_contradictions = [c for c in contradictions if not c.dismissed]
        active_orphans = [o for o in orphans if not o.dismissed]
        active_structurals = [s for s in structurals if not s.dismissed]
        dismissed = (
            (len(contradictions) - len(active_contradictions))
            + (len(orphans) - len(active_orphans))
            + (len(structurals) - len(active_structurals))
        )

        report.status = LintReportStatus.COMPLETE
        report.completed_at = utcnow_naive()
        report.contradictions_count = len(active_contradictions)
        report.orphans_count = len(active_orphans)
        report.structural_count = len(active_structurals)
        report.total_findings = len(active_contradictions) + len(active_orphans) + len(active_structurals)
        report.dismissed_count = dismissed
        session.add(report)
        await session.commit()

        log.info(
            "Lint run complete",
            report_id=report.id,
            contradictions=len(contradictions),
            orphans=len(orphans),
            structurals=len(structurals),
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
