"""Backlink structural integrity enforcer (Phase 4, issue #143).

Runs structural checks on an article's backlink graph and auto-heals
symmetric link types (``contradicts``, ``related_to``) by creating
missing inverse links.

Usage:

    result = await enforce_backlinks(article_id, session)
    # result.violations is [] when all checks pass
    # result.warnings is [] when all checks pass (backward compat)
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass, field

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from wikimind.models import Article, Backlink, RelationType

log = structlog.get_logger()

# Symmetric relation types -- inverse must exist for graph consistency.
_SYMMETRIC_TYPES: frozenset[RelationType] = frozenset({RelationType.CONTRADICTS, RelationType.RELATED_TO})


@dataclass
class EnforcerViolation:
    """A single structural violation found by the enforcer."""

    article_id: str
    article_title: str
    violation_type: str
    detail: str
    auto_repaired: bool = False


@dataclass
class EnforcerResult:
    """Aggregated result of running the backlink enforcer on one article."""

    violations: list[EnforcerViolation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


async def ensure_bidirectional(backlink: Backlink, session: AsyncSession) -> bool:
    """Create the inverse link for a symmetric relation type if missing.

    Returns True if an inverse was created, False if it already existed
    or the relation type is not symmetric.
    """
    if backlink.relation_type not in _SYMMETRIC_TYPES:
        return False

    result = await session.execute(
        select(Backlink).where(
            Backlink.source_article_id == backlink.target_article_id,
            Backlink.target_article_id == backlink.source_article_id,
        )
    )
    existing = result.scalars().first()
    if existing is not None:
        return False

    session.add(
        Backlink(
            source_article_id=backlink.target_article_id,
            target_article_id=backlink.source_article_id,
            relation_type=backlink.relation_type,
            context=backlink.context,
        )
    )
    await session.flush()
    log.info(
        "Created inverse backlink",
        source=backlink.target_article_id,
        target=backlink.source_article_id,
        relation_type=backlink.relation_type,
    )
    return True


async def enforce_backlinks(article_id: str, session: AsyncSession) -> EnforcerResult:
    """Run structural integrity checks on an article's backlinks.

    Returns an EnforcerResult with violations and warnings.

    Checks performed:
        1. Source pages must have >= 1 concept in concept_ids.
        2. Concept pages must have >= 2 ``synthesizes`` outbound links.
        3. For ``contradicts`` / ``related_to`` links: auto-create inverse
           if missing (bidirectional enforcement).

    Note: orphan detection is handled separately by detect_orphans() in
    the linter pipeline and is NOT duplicated here.
    """
    result = EnforcerResult()

    # Load the article
    query_result = await session.execute(select(Article).where(Article.id == article_id))
    article = query_result.scalars().first()
    if article is None:
        msg = f"Article {article_id} not found"
        result.warnings.append(msg)
        return result

    # ---- Check 1: source pages need >= 1 concept ----
    if article.page_type == "source":
        concept_ids: list[str] = []
        if article.concept_ids:
            with contextlib.suppress(TypeError, ValueError):
                concept_ids = json.loads(article.concept_ids)
        if not concept_ids:
            msg = f"Source page '{article.title}' has no concepts in concept_ids"
            result.warnings.append(msg)
            result.violations.append(
                EnforcerViolation(
                    article_id=article_id,
                    article_title=article.title,
                    violation_type="source_no_concepts",
                    detail=msg,
                )
            )

    # ---- Check 2: concept pages need >= 2 synthesizes links ----
    if article.page_type == "concept":
        synth_result = await session.execute(
            select(Backlink).where(
                Backlink.source_article_id == article_id,
                Backlink.relation_type == RelationType.SYNTHESIZES,
            )
        )
        synth_count = len(list(synth_result.scalars().all()))
        if synth_count < 2:
            msg = f"Concept page '{article.title}' has {synth_count} synthesizes links (need >= 2)"
            result.warnings.append(msg)
            result.violations.append(
                EnforcerViolation(
                    article_id=article_id,
                    article_title=article.title,
                    violation_type="concept_insufficient_synthesizes",
                    detail=msg,
                )
            )

    # ---- Check 3: bidirectional enforcement for symmetric types ----
    out_result = await session.execute(select(Backlink).where(Backlink.source_article_id == article_id))
    outbound = list(out_result.scalars().all())

    in_result = await session.execute(select(Backlink).where(Backlink.target_article_id == article_id))
    inbound = list(in_result.scalars().all())

    all_links = outbound + inbound
    for bl in all_links:
        created = await ensure_bidirectional(bl, session)
        if created:
            msg = (
                f"Missing inverse link created: {bl.source_article_id} <-> {bl.target_article_id} ({bl.relation_type})"
            )
            result.warnings.append(msg)
            result.violations.append(
                EnforcerViolation(
                    article_id=article_id,
                    article_title=article.title,
                    violation_type="missing_inverse_link",
                    detail=msg,
                    auto_repaired=True,
                )
            )
            log.info(
                "Auto-created inverse for symmetric link",
                source=bl.source_article_id,
                target=bl.target_article_id,
                relation_type=bl.relation_type,
            )

    return result
