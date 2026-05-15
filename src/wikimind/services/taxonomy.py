"""Concept taxonomy management — upsert, article counts, and LLM hierarchy.

Normalizes concept names via ``slugify()`` for deduplication. The
human-readable label emitted by the compiler is stored in
``Concept.description`` so the UI can display "Machine Learning"
while the DB key is ``machine-learning``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import structlog
from slugify import slugify
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select

from wikimind.config import get_settings
from wikimind.database import _dialect_insert
from wikimind.engine.concept_compiler import ConceptCompiler, _collect_source_articles
from wikimind.engine.llm_router import get_llm_router
from wikimind.models import (
    Article,
    ArticleConcept,
    ArticleSource,
    CompletionRequest,
    Concept,
    PageType,
    TaskType,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

TAXONOMY_SYSTEM_PROMPT = """You are a knowledge taxonomy organizer. Given concept names from a personal wiki, organize them into a hierarchy of 2-3 levels.

Rules:
- Create 5-15 top-level categories (parent=null)
- Nest specific concepts under their most natural parent
- Maximum depth: {max_depth} levels
- Every concept in the input MUST appear exactly once in the output
- Do not invent new concepts — only organize what's given
- When in doubt, leave a concept at the root level

Input concepts:
{concept_names}

Return valid JSON only — an array of objects:
[{{"name": "concept-name", "parent": null}}, {{"name": "sub-concept", "parent": "concept-name"}}]"""


def _parse_concept_ids(raw: str | None) -> list[str]:
    """Parse JSON-encoded concept_ids field, returning empty list on failure."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if item]


async def upsert_concepts(
    concept_names: list[str],
    session: AsyncSession,
    user_id: str,
) -> list[Concept]:
    """Create or retrieve Concept rows for the given names.

    Names are normalized via ``slugify()`` for deduplication. The original
    LLM-emitted name is stored in ``Concept.description`` as a human-readable
    label.

    Args:
        concept_names: Raw concept names from the compiler.
        session: Async database session.
        user_id: Optional user ID for data isolation.

    Returns:
        List of Concept rows (one per unique normalized name).
    """
    if not concept_names:
        return []

    # Use dialect-aware INSERT ... ON CONFLICT to avoid TOCTOU races when
    # two concurrent compilations try to create the same concept (#637).
    conn = await session.connection()
    insert_fn = _dialect_insert(conn)

    normalized_names: list[str] = []
    for raw_name in concept_names:
        normalized = slugify(raw_name)
        if not normalized:
            continue
        normalized_names.append(normalized)
        stmt = (
            insert_fn(Concept)
            .values(
                name=normalized,
                description=raw_name,
                user_id=user_id,
            )
            .on_conflict_do_nothing(
                index_elements=["user_id", "name"],
            )
        )
        await session.execute(stmt)

    # Update description for any rows that were previously empty.
    for raw_name, normalized in zip(
        concept_names,
        [slugify(n) for n in concept_names],
        strict=True,
    ):
        if not normalized:
            continue
        update_stmt = select(Concept).where(
            Concept.name == normalized,
            Concept.user_id == user_id,
        )
        result = await session.execute(update_stmt)
        existing = result.scalar_one_or_none()
        if existing is not None and not existing.description:
            existing.description = raw_name
            session.add(existing)

    await session.commit()

    # Fetch all concepts that were upserted to return them.
    if not normalized_names:
        return []
    fetch_stmt = select(Concept).where(
        Concept.name.in_(normalized_names),  # type: ignore[attr-defined]
        Concept.user_id == user_id,
    )
    result = await session.execute(fetch_stmt)
    return list(result.scalars().all())


async def update_article_counts(
    session: AsyncSession,
    user_id: str,
) -> None:
    """Recalculate ``Concept.article_count`` from the ArticleConcept join table.

    Queries the join table for article counts per concept name, normalizes
    each name, and sets the count on the matching Concept row. Concepts
    not referenced by any article get their count reset to zero.

    Args:
        session: Async database session.
        user_id: Optional user ID for data isolation.
    """
    # Count references per normalized concept name from join table — only
    # source articles count toward the threshold for concept page generation (#155).
    counts: dict[str, int] = {}
    ac_stmt = (
        select(ArticleConcept)
        .join(Article, ArticleConcept.article_id == Article.id)  # type: ignore[arg-type]
        .where(Article.page_type == PageType.SOURCE, Article.user_id == user_id)
    )
    ac_result = await session.execute(ac_stmt)
    for ac in ac_result.scalars().all():
        normalized = slugify(ac.concept_name)
        if normalized:
            counts[normalized] = counts.get(normalized, 0) + 1

    # Apply counts to all concepts (scoped by user_id)
    concept_stmt = select(Concept).where(Concept.user_id == user_id)
    concepts_result = await session.execute(concept_stmt)
    for concept in concepts_result.scalars().all():
        concept.article_count = counts.get(concept.name, 0)
        session.add(concept)

    await session.commit()


async def _concept_source_set_changed(concept: Concept, session: AsyncSession, user_id: str) -> bool:
    """Return True if the concept's current source articles differ from the last compilation.

    Compares sorted source article IDs from the database against the
    source IDs stored in the ``ArticleSource`` join table for the existing
    concept page article. Returns True (needs recompilation) when no
    existing concept page exists or when the sorted ID lists do not match.

    This avoids expensive LLM calls when the source set is unchanged
    (issue #162).
    """
    source_articles = await _collect_source_articles(concept.name, session, user_id=user_id)
    current_ids = sorted(a.id for a in source_articles)

    # Look up existing concept page.
    slug = f"concept-{slugify(concept.name)}"
    existing_result = await session.execute(
        select(Article).where(
            Article.slug == slug,
            Article.page_type == PageType.CONCEPT,
            Article.user_id == user_id,
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing is None:
        return True

    prev_result = await session.execute(select(ArticleSource.source_id).where(ArticleSource.article_id == existing.id))
    previous_ids = sorted(row[0] for row in prev_result.all())

    # Fallback to JSON if join table is empty (pre-migration data)
    if not previous_ids:
        try:
            previous_ids = sorted(json.loads(existing.source_ids or "[]"))
        except (TypeError, ValueError):
            return True

    return current_ids != previous_ids


async def maybe_trigger_concept_pages(
    session: AsyncSession,
    user_id: str,
) -> list[str]:
    """Generate concept pages for concepts with enough source articles.

    Skips concepts whose source set has not changed since the last
    compilation, avoiding unnecessary LLM calls (issue #162).

    Args:
        session: Async database session.
        user_id: Optional user ID for data isolation.
    """
    settings = get_settings()
    min_sources = settings.taxonomy.concept_page_min_sources
    stmt = select(Concept).where(Concept.article_count >= min_sources, Concept.user_id == user_id)
    result = await session.execute(stmt)  # AsyncSession, not SQLModel Session
    eligible = list(result.scalars().all())
    if not eligible:
        return []

    compiler = ConceptCompiler(user_id=user_id)
    compiled: list[str] = []
    for concept in eligible:
        try:
            if not await _concept_source_set_changed(concept, session, user_id=user_id):
                log.debug(
                    "Concept page source set unchanged, skipping recompilation",
                    concept=concept.name,
                )
                continue
            article = await compiler.compile_concept_page(concept, session)
            if article is not None:
                compiled.append(concept.name)
        except (RuntimeError, ValueError, SQLAlchemyError):
            log.warning("Concept page compilation failed", concept=concept.name, exc_info=True)
    return compiled


async def maybe_trigger_taxonomy_rebuild(
    session: AsyncSession,
    user_id: str,
) -> bool:
    """Trigger a taxonomy rebuild if unparented concepts exceed the threshold.

    Args:
        session: Async database session.
        user_id: Optional user ID for data isolation.

    Returns:
        True if a rebuild was triggered, False otherwise.
    """
    settings = get_settings()
    threshold = settings.taxonomy.rebuild_threshold

    stmt = select(Concept).where(
        Concept.parent_id.is_(None),  # type: ignore[union-attr]
        Concept.user_id == user_id,
    )
    result = await session.execute(stmt)
    unparented = list(result.scalars().all())

    if len(unparented) >= threshold:
        await rebuild_taxonomy(session, user_id=user_id)
        return True
    return False


async def rebuild_taxonomy(
    session: AsyncSession,
    user_id: str,
) -> None:
    """Use LLM to infer concept hierarchy and rewrite all parent_ids.

    Fetches all concepts, asks the LLM to organize them, validates
    the response for cycles, then applies the new parent assignments.

    Args:
        session: Async database session.
        user_id: Optional user ID for data isolation.
    """
    settings = get_settings()
    max_depth = settings.taxonomy.max_hierarchy_depth

    concept_stmt = select(Concept).where(Concept.user_id == user_id)
    result = await session.execute(concept_stmt)
    all_concepts = list(result.scalars().all())

    if not all_concepts:
        return

    concept_names = [c.name for c in all_concepts]
    concept_map = {c.name: c for c in all_concepts}

    prompt = TAXONOMY_SYSTEM_PROMPT.format(
        max_depth=max_depth,
        concept_names="\n".join(f"- {name}" for name in concept_names),
    )

    router = get_llm_router()
    request = CompletionRequest(
        system=prompt,
        messages=[{"role": "user", "content": "Organize these concepts."}],
        max_tokens=4096,
        temperature=0.2,
        response_format="json",
        task_type=TaskType.INDEX,
    )

    response = await router.complete(request, user_id=user_id)
    hierarchy = router.parse_json_response(response)

    if not isinstance(hierarchy, list):
        log.warning("Taxonomy LLM returned non-list response, skipping")
        return

    parent_mapping = _build_parent_mapping(hierarchy, concept_map)

    if _has_cycles(parent_mapping):
        log.warning("Taxonomy LLM response contains cycles, skipping")
        return

    if _exceeds_max_depth(parent_mapping, max_depth):
        log.warning(
            "Taxonomy LLM response exceeds max depth, skipping",
            max_depth=max_depth,
        )
        return

    _apply_parent_mapping(all_concepts, parent_mapping, concept_map, session)

    await session.commit()
    log.info("Taxonomy rebuilt", total_concepts=len(all_concepts))


def _build_parent_mapping(
    hierarchy: list,
    concept_map: dict[str, Concept],
) -> dict[str, str | None]:
    """Build a parent mapping from the LLM hierarchy response.

    Only includes concepts that exist in the concept_map. Parent references
    to unknown concepts are treated as root-level.

    Args:
        hierarchy: List of dicts with ``name`` and ``parent`` keys.
        concept_map: Mapping of concept name to Concept row.

    Returns:
        Mapping of concept name to parent name (or None for root).
    """
    parent_mapping: dict[str, str | None] = {}
    for entry in hierarchy:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        parent = entry.get("parent")
        if not name or name not in concept_map:
            continue
        if parent and parent in concept_map:
            parent_mapping[name] = parent
        else:
            parent_mapping[name] = None
    return parent_mapping


def _apply_parent_mapping(
    all_concepts: list[Concept],
    parent_mapping: dict[str, str | None],
    concept_map: dict[str, Concept],
    session: AsyncSession,
) -> None:
    """Apply a validated parent mapping to concept rows.

    Concepts not present in the mapping are set to root (parent_id=None).

    Args:
        all_concepts: All Concept rows from the database.
        parent_mapping: Validated mapping of concept name to parent name.
        concept_map: Mapping of concept name to Concept row.
        session: Async database session (rows are added but not committed).
    """
    for concept in all_concepts:
        parent_name = parent_mapping.get(concept.name)
        if parent_name is not None:
            concept.parent_id = concept_map[parent_name].id
        else:
            concept.parent_id = None
        session.add(concept)


def _has_cycles(parent_mapping: dict[str, str | None]) -> bool:
    """Check if the parent mapping contains any cycles.

    Args:
        parent_mapping: Mapping of concept name to parent name (or None).

    Returns:
        True if a cycle is detected.
    """
    for name in parent_mapping:
        visited: set[str] = set()
        current: str | None = name
        while current is not None:
            if current in visited:
                return True
            visited.add(current)
            current = parent_mapping.get(current)
    return False


def _exceeds_max_depth(
    parent_mapping: dict[str, str | None],
    max_depth: int,
) -> bool:
    """Check if any chain in the parent mapping exceeds max_depth.

    Args:
        parent_mapping: Mapping of concept name to parent name (or None).
        max_depth: Maximum allowed hierarchy depth.

    Returns:
        True if any chain exceeds max_depth levels.
    """
    for name in parent_mapping:
        depth = 0
        current: str | None = name
        while current is not None:
            current = parent_mapping.get(current)
            depth += 1
            if depth > max_depth:
                return True
    return False
