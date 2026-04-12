"""Orphan detection — pure SQL check for articles with no backlinks.

Identifies articles with zero inbound AND zero outbound backlinks.
Gated by ``settings.linter.enable_orphan_detection`` (default False)
until issue #95 populates the Backlink table.
"""

from __future__ import annotations

import hashlib

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from wikimind.config import Settings
from wikimind.models import (
    LintFindingKind,
    LintSeverity,
    OrphanFinding,
)

log = structlog.get_logger()


def _content_hash(article_id: str) -> str:
    """Compute a stable sha256 for cross-run dedup of dismissed findings.

    Keyed by article ID only — not the title, which may change.
    """
    raw = f"{LintFindingKind.ORPHAN}|{article_id}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def detect_orphans(
    session: AsyncSession,
    settings: Settings,
    report_id: str,
) -> list[OrphanFinding]:
    """Find articles with zero inbound AND zero outbound backlinks.

    This check is gated by ``settings.linter.enable_orphan_detection``.
    When disabled (default), returns an empty list immediately.

    Args:
        session: Async database session.
        settings: Application settings with linter config.
        report_id: The parent LintReport ID.

    Returns:
        List of OrphanFinding instances ready for persistence.
    """
    if not settings.linter.enable_orphan_detection:
        log.info("Orphan detection disabled (enable_orphan_detection=False)")
        return []

    result = await session.execute(
        text(
            "SELECT a.id, a.title FROM article a "
            "LEFT JOIN backlink bl_in ON bl_in.target_article_id = a.id "
            "LEFT JOIN backlink bl_out ON bl_out.source_article_id = a.id "
            "WHERE bl_in.target_article_id IS NULL "
            "AND bl_out.source_article_id IS NULL"
        )
    )
    rows = result.fetchall()

    findings: list[OrphanFinding] = []
    for row in rows:
        article_id, article_title = row
        findings.append(
            OrphanFinding(
                report_id=report_id,
                severity=LintSeverity.INFO,
                description=f"Article '{article_title}' has no inbound or outbound links",
                content_hash=_content_hash(article_id),
                article_id=article_id,
                article_title=article_title,
            )
        )

    log.info("Orphan detection complete", orphans_found=len(findings))
    return findings
