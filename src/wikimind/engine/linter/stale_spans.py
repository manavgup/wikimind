"""Stale-span detection — surface articles with claims pointing to stale source spans.

When a source is re-ingested and some paragraphs no longer match, the
corresponding ``SourceSpan`` rows are marked ``stale=True``.  Claims that
still reference those stale spans lose their citation anchor.  This check
generates :class:`StructuralFinding` lint warnings so users know which
articles need attention.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

import structlog
from sqlmodel import select

from wikimind.models import (
    Article,
    CompiledClaim,
    LintFindingKind,
    LintSeverity,
    SourceSpan,
    StructuralFinding,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

VIOLATION_TYPE = "stale_source_spans"


def _content_hash(article_id: str) -> str:
    """Compute a stable sha256 for cross-run dedup of stale-span findings."""
    raw = f"{LintFindingKind.STRUCTURAL}|{article_id}|{VIOLATION_TYPE}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def detect_stale_spans(
    session: AsyncSession,
    report_id: str,
    user_id: str,
) -> list[StructuralFinding]:
    """Find articles with claims pointing to stale source spans.

    For each article, loads its compiled claims and checks whether any
    ``source_span_ids`` reference a span whose ``stale`` flag is True.

    Args:
        session: Async database session.
        report_id: The parent LintReport ID.
        user_id: User ID for data isolation.

    Returns:
        List of StructuralFinding instances for articles with stale span refs.
    """
    # Load all stale span IDs for this user in one query
    stale_stmt = select(SourceSpan.id).where(
        SourceSpan.user_id == user_id,
        SourceSpan.stale.is_(True),  # type: ignore[attr-defined]
    )
    stale_result = await session.execute(stale_stmt)
    stale_span_ids: set[str] = {row[0] for row in stale_result.all()}

    if not stale_span_ids:
        log.info("Stale-span detection: no stale spans found")
        return []

    # Load all claims for this user that have span references
    claim_stmt = (
        select(CompiledClaim.article_id, CompiledClaim.source_span_ids)
        .where(CompiledClaim.user_id == user_id)
        .where(CompiledClaim.source_span_ids != "[]")
    )
    claim_result = await session.execute(claim_stmt)
    claim_rows = claim_result.all()

    # Group stale-span-referencing claims by article
    articles_with_stale: dict[str, int] = {}
    for article_id, span_ids_json in claim_rows:
        try:
            span_ids = json.loads(span_ids_json)
        except (json.JSONDecodeError, TypeError):
            continue
        stale_count = sum(1 for sid in span_ids if sid in stale_span_ids)
        if stale_count > 0:
            articles_with_stale[article_id] = articles_with_stale.get(article_id, 0) + stale_count

    if not articles_with_stale:
        log.info("Stale-span detection: no claims reference stale spans")
        return []

    # Look up article titles for readable descriptions
    article_stmt = select(Article.id, Article.title).where(
        Article.id.in_(list(articles_with_stale.keys())),  # type: ignore[attr-defined]
    )
    article_result = await session.execute(article_stmt)
    article_titles: dict[str, str] = {row[0]: row[1] for row in article_result.all()}

    findings: list[StructuralFinding] = []
    for article_id, stale_count in articles_with_stale.items():
        title = article_titles.get(article_id, article_id)
        desc = f"Article '{title}' has {stale_count} claim(s) referencing stale source spans"
        findings.append(
            StructuralFinding(
                report_id=report_id,
                severity=LintSeverity.WARN,
                description=desc,
                content_hash=_content_hash(article_id),
                article_id=article_id,
                violation_type=VIOLATION_TYPE,
                auto_repaired=False,
                detail=f"stale_span_references={stale_count}",
                user_id=user_id,
            )
        )

    log.info("Stale-span detection complete", articles_affected=len(findings))
    return findings
