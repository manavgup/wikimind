"""Resolve LLM-suggested wikilink candidates against the Article table.

Given a list of candidate title strings (as produced by the compiler
LLM in ``CompilationResult.backlink_suggestions``) and an async DB
session, return two lists:

    - ``resolved``: :class:`ResolvedBacklink` rows, each pointing at a
      real :class:`Article` by ID.
    - ``unresolved``: candidate strings that matched no article.

The algorithm is deterministic and has exactly two stages:

    1. Exact case-insensitive match against ``Article.title``.
    2. Normalized match using :func:`normalize_title` on both sides.

There is NO fuzzy matching. See the design spec for rationale
(docs/superpowers/specs/2026-04-08-wikilink-resolution-design.md).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from wikimind.engine.title_normalizer import normalize_title
from wikimind.models import Article


@dataclass(frozen=True)
class ResolvedBacklink:
    """A successfully resolved wikilink candidate.

    Attributes:
        candidate_text: The raw string the LLM produced. Preserved
            verbatim so the rendered markdown can show the LLM's
            wording if it differs from the canonical title.
        target_id: The :class:`Article.id` this candidate resolved to.
        target_title: The canonical :class:`Article.title` of the
            resolved article. Used by the compiler's markdown writer.
    """

    candidate_text: str
    target_id: str
    target_title: str
    relation_type: str = "references"


async def resolve_backlink_candidates(
    candidates: list[str],
    session: AsyncSession,
    exclude_article_id: str | None = None,
    relation_types: dict[str, str] | None = None,
) -> tuple[list[ResolvedBacklink], list[str]]:
    """Resolve wikilink candidates against the Article table.

    Args:
        candidates: Raw title strings from
            :attr:`CompilationResult.backlink_suggestions`. Empty
            strings and whitespace-only strings are silently dropped.
        session: Async DB session.
        exclude_article_id: If set, any candidate that would resolve
            to this article ID is treated as unresolved. Used by the
            compiler to prevent self-references when an article is
            suggested to link to itself.
        relation_types: Optional mapping of candidate text (lowered) to
            relation type string. When provided, resolved backlinks
            carry the relation type through. Defaults to references.

    Returns:
        A tuple ``(resolved, unresolved)``. Resolved contains one
        :class:`ResolvedBacklink` per unique target article (so two
        candidates pointing at the same article produce one row).
        Unresolved is the list of candidate strings that matched no
        article, in input order.
    """
    rel_map = relation_types or {}

    # Drop empty / whitespace-only candidates up front.
    cleaned = [c.strip() for c in candidates if c and c.strip()]
    if not cleaned:
        return [], []

    # Load every Article once. For a single-user personal wiki this is
    # fine — we expect O(hundreds) of articles at most. If this ever
    # becomes a bottleneck, narrow the SELECT to (id, title, created_at).
    result = await session.execute(select(Article).order_by(Article.created_at))  # type: ignore[arg-type]
    all_articles: list[Article] = list(result.scalars().all())
    if exclude_article_id is not None:
        all_articles = [a for a in all_articles if a.id != exclude_article_id]

    # Build lookup dicts once per call. Both map canonical form → first article.
    by_lower: dict[str, Article] = {}
    by_normalized: dict[str, Article] = {}
    for article in all_articles:
        lower_key = article.title.lower()
        if lower_key not in by_lower:
            by_lower[lower_key] = article
        norm_key = normalize_title(article.title)
        if norm_key and norm_key not in by_normalized:
            by_normalized[norm_key] = article

    resolved_by_target: dict[str, ResolvedBacklink] = {}
    unresolved: list[str] = []
    for candidate in cleaned:
        target = by_lower.get(candidate.lower())
        if target is None:
            norm = normalize_title(candidate)
            if norm:
                target = by_normalized.get(norm)
        if target is None:
            unresolved.append(candidate)
            continue
        # Dedup: two candidates resolving to the same target → one entry.
        if target.id not in resolved_by_target:
            resolved_by_target[target.id] = ResolvedBacklink(
                candidate_text=candidate,
                target_id=target.id,
                target_title=target.title,
                relation_type=rel_map.get(candidate.lower(), "references"),
            )

    return list(resolved_by_target.values()), unresolved
