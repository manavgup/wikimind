"""Staleness detection — surface articles with high staleness scores.

Identifies articles whose ``staleness_score`` exceeds the configured
threshold (default 0.5) and generates :class:`StructuralFinding` lint
warnings so users are prompted to review or refresh them.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import structlog
from sqlmodel import select

from wikimind._datetime import utcnow_naive
from wikimind.engine.confidence import compute_staleness
from wikimind.models import (
    Article,
    LintFindingKind,
    LintSeverity,
    StructuralFinding,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from wikimind.config import Settings

log = structlog.get_logger()

VIOLATION_TYPE = "stale_article"


def _content_hash(article_id: str) -> str:
    """Compute a stable sha256 for cross-run dedup of staleness findings."""
    raw = f"{LintFindingKind.STRUCTURAL}|{article_id}|{VIOLATION_TYPE}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def detect_stale_articles(
    session: AsyncSession,
    settings: Settings,
    report_id: str,
    user_id: str,
) -> list[StructuralFinding]:
    """Find articles with staleness score above the configured threshold.

    Args:
        session: Async database session.
        settings: Application settings with staleness config.
        report_id: The parent LintReport ID.
        user_id: User ID for data isolation.

    Returns:
        List of StructuralFinding instances for stale articles.
    """
    stmt = select(Article).where(Article.user_id == user_id)
    result = await session.execute(stmt)
    articles = list(result.scalars().all())

    now = utcnow_naive()
    threshold = settings.staleness.lint_threshold
    decay_rate = settings.staleness.decay_rate

    findings: list[StructuralFinding] = []
    for article in articles:
        if article.last_reinforced_at is None:
            score = 1.0
        else:
            days = (now - article.last_reinforced_at).total_seconds() / 86400
            score = compute_staleness(days, decay_rate=decay_rate)

        if score > threshold:
            findings.append(
                StructuralFinding(
                    report_id=report_id,
                    severity=LintSeverity.WARN,
                    description=(f"Article '{article.title}' is stale (staleness={score:.2f}, threshold={threshold})"),
                    content_hash=_content_hash(article.id),
                    article_id=article.id,
                    violation_type=VIOLATION_TYPE,
                    auto_repaired=False,
                    detail=(f"staleness_score={score:.4f}, last_reinforced_at={article.last_reinforced_at}"),
                    user_id=user_id,
                )
            )

    log.info("Staleness detection complete", stale_found=len(findings))
    return findings
