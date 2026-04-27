"""Orphan detection — find articles with no backlinks.

Identifies articles with zero inbound AND zero outbound backlinks.
Gated by ``settings.linter.enable_orphan_detection`` (default False)
until issue #95 populates the Backlink table.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import structlog
from sqlmodel import select

from wikimind.models import (
    Article,
    Backlink,
    LintFindingKind,
    LintSeverity,
    OrphanFinding,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from wikimind.config import Settings

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
    user_id: str | None = None,
) -> list[OrphanFinding]:
    """Find articles with zero inbound AND zero outbound backlinks.

    This check is gated by ``settings.linter.enable_orphan_detection``.
    When disabled (default), returns an empty list immediately.

    Args:
        session: Async database session.
        settings: Application settings with linter config.
        report_id: The parent LintReport ID.
        user_id: Optional user ID to scope the check to a single user's articles.

    Returns:
        List of OrphanFinding instances ready for persistence.
    """
    if not settings.linter.enable_orphan_detection:
        log.info("Orphan detection disabled (enable_orphan_detection=False)")
        return []

    # Build LEFT JOINs for inbound/outbound backlinks, scoped by user_id
    # when provided so another user's backlinks don't mask orphans.
    inbound_join = Backlink.target_article_id == Article.id  # type: ignore[arg-type]
    outbound_join = Backlink.source_article_id == Article.id  # type: ignore[arg-type]
    if user_id is not None:
        inbound_join = inbound_join & (Backlink.user_id == user_id)  # type: ignore[assignment]
        outbound_join = outbound_join & (Backlink.user_id == user_id)  # type: ignore[assignment]

    bl_in = select(Backlink.target_article_id).where(inbound_join).correlate(Article)
    bl_out = select(Backlink.source_article_id).where(outbound_join).correlate(Article)

    stmt = select(Article.id, Article.title).where(
        ~bl_in.exists(),  # type: ignore[union-attr]
        ~bl_out.exists(),  # type: ignore[union-attr]
    )
    if user_id is not None:
        stmt = stmt.where(Article.user_id == user_id)

    result = await session.execute(stmt)
    rows = result.all()

    findings: list[OrphanFinding] = []
    for article_id, article_title in rows:
        findings.append(
            OrphanFinding(
                report_id=report_id,
                severity=LintSeverity.INFO,
                description=f"Article '{article_title}' has no inbound or outbound links",
                content_hash=_content_hash(article_id),
                article_id=article_id,
                article_title=article_title,
                user_id=user_id,
            )
        )

    log.info("Orphan detection complete", orphans_found=len(findings))
    return findings
