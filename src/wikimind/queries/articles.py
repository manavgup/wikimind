"""Shared query helpers for article source and concept resolution.

Every function in this module is a pure data-access helper with no
business logic.  The join-table-first-then-JSON-fallback pattern is
encoded once here and re-used by ``services.wiki``, ``services.query``,
``jobs.worker``, and ``api.routes.export``.
"""

import json

import structlog
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.models import Article, ArticleConcept, ArticleSource, Source

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# JSON-column parsing (legacy fallback)
# ---------------------------------------------------------------------------


def parse_json_column(raw: str | None) -> list[str]:
    """Parse a JSON-encoded list column into a Python list of strings.

    Used for the legacy ``Article.source_ids`` and ``Article.concept_ids``
    JSON columns.  Returns an empty list when the field is missing, empty,
    or malformed.  Malformed values are logged but never raised so a single
    broken record cannot break listing or search responses.

    Args:
        raw: Raw JSON string (e.g. from ``Article.source_ids``).

    Returns:
        List of strings (possibly empty).
    """
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        log.warning("Failed to parse JSON column", raw=raw)
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if item]


# ---------------------------------------------------------------------------
# Source-ID resolution (join table + JSON fallback)
# ---------------------------------------------------------------------------


async def fetch_source_ids_for_article(
    session: AsyncSession,
    article_id: str,
) -> list[str]:
    """Fetch source IDs for an article from the ``ArticleSource`` join table.

    Falls back to parsing the legacy ``Article.source_ids`` JSON column
    when no join-table rows exist (pre-migration data).

    Args:
        session: Async database session.
        article_id: The article UUID.

    Returns:
        List of source UUID strings (possibly empty).
    """
    result = await session.exec(select(ArticleSource.source_id).where(ArticleSource.article_id == article_id))
    ids = list(result.all())
    if ids:
        return ids
    # Fallback: read from legacy JSON column
    art_result = await session.exec(select(Article.source_ids).where(Article.id == article_id))
    val = art_result.first()
    return parse_json_column(val)


# ---------------------------------------------------------------------------
# Concept-name resolution (join table + JSON fallback)
# ---------------------------------------------------------------------------


async def fetch_concept_names_for_article(
    session: AsyncSession,
    article_id: str,
) -> list[str]:
    """Fetch concept names for an article from the ``ArticleConcept`` join table.

    Falls back to parsing the legacy ``Article.concept_ids`` JSON column
    when no join-table rows exist (pre-migration data).

    Args:
        session: Async database session.
        article_id: The article UUID.

    Returns:
        List of concept name strings (possibly empty).
    """
    result = await session.exec(select(ArticleConcept.concept_name).where(ArticleConcept.article_id == article_id))
    names = list(result.all())
    if names:
        return names
    # Fallback: read from legacy JSON column
    art_result = await session.exec(select(Article.concept_ids).where(Article.id == article_id))
    val = art_result.first()
    return parse_json_column(val)


# ---------------------------------------------------------------------------
# Batch helpers
# ---------------------------------------------------------------------------


async def fetch_concepts_for_articles(
    session: AsyncSession,
    article_ids: list[str],
) -> dict[str, list[str]]:
    """Batch-fetch concept names for multiple articles from the join table.

    Args:
        session: Async database session.
        article_ids: List of article UUIDs.

    Returns:
        Dict mapping each article ID to its list of concept names.
        Every requested ID appears as a key (empty list if no concepts).
    """
    result: dict[str, list[str]] = {aid: [] for aid in article_ids}
    if not article_ids:
        return result
    ac_result = await session.execute(
        select(ArticleConcept.article_id, ArticleConcept.concept_name).where(
            ArticleConcept.article_id.in_(article_ids)  # type: ignore[attr-defined]
        )
    )
    for row in ac_result.all():
        result[row[0]].append(row[1])
    return result


# ---------------------------------------------------------------------------
# Source-record fetching
# ---------------------------------------------------------------------------


async def fetch_sources(
    session: AsyncSession,
    source_ids: list[str],
) -> list[Source]:
    """Fetch :class:`Source` records for a list of source IDs, preserving order.

    Missing rows (e.g. a source was deleted after the article was compiled)
    are silently dropped -- callers receive only the sources that still
    exist in the database.

    Args:
        session: Async database session.
        source_ids: List of source UUIDs to fetch.

    Returns:
        Source records in the same order as *source_ids*, with any
        missing IDs omitted.
    """
    if not source_ids:
        return []
    result = await session.exec(
        select(Source).where(Source.id.in_(source_ids))  # type: ignore[attr-defined]
    )
    by_id = {s.id: s for s in result.all()}
    return [by_id[sid] for sid in source_ids if sid in by_id]
