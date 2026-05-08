"""Full-text search service — FTS5 on SQLite, tsvector on Postgres.

Provides BM25-ranked full-text search across wiki article titles and content.
The FTS index is maintained in sync with article creates/updates/deletes via
explicit helper functions called from the compiler and delete paths.

Phase 1 focuses on keyword search only. Phase 2 will layer vector search on
top via the existing ``EmbeddingService``.
"""

from __future__ import annotations

import functools
import hashlib
from collections import Counter
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import text as sa_text
from sqlmodel import select

from wikimind._datetime import utcnow_naive
from wikimind.config import get_settings
from wikimind.db_compat import is_postgres
from wikimind.engine.confidence import compute_staleness
from wikimind.models import (
    Article,
    ArticleConcept,
    ArticleSource,
    ArticleTag,
    FacetBucket,
    FacetGroup,
    FacetResponse,
    FTSResponse,
    FTSResultItem,
    Source,
    Tag,
)
from wikimind.storage import get_wiki_storage

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

# Module-level flag set by ``create_fts_table``.  When False, all FTS
# write helpers (``index_article``, ``remove_article``) silently no-op.
# This avoids OperationalError crashes in tests that create in-memory
# SQLite databases without calling ``init_db``.
_fts_ready = False


# ---------------------------------------------------------------------------
# FTS table management — called from init_db() at startup
# ---------------------------------------------------------------------------


async def create_fts_table(engine) -> None:
    """Create the full-text search virtual table if it does not exist.

    SQLite: FTS5 virtual table with porter + unicode61 tokenizer.
    Postgres: GIN index on a generated tsvector column.

    Idempotent — safe to call on every startup.  Sets the module-level
    ``_fts_ready`` flag so that sync helpers know the table is available.
    """
    global _fts_ready

    url = get_settings().database_url

    async with engine.begin() as conn:
        if is_postgres(url):
            await conn.execute(
                sa_text(
                    "CREATE INDEX IF NOT EXISTS idx_article_fts ON article "
                    "USING gin (to_tsvector('english', coalesce(title, '') "
                    "|| ' ' || coalesce(summary, '')))"
                )
            )
        else:
            # SQLite FTS5 — standalone table (not external content) to store
            # title + article body so we can use snippet() and bm25().
            await conn.execute(
                sa_text(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS article_fts USING fts5("
                    "title, content, tokenize='porter unicode61')"
                )
            )

    _fts_ready = True


async def rebuild_fts_index(session: AsyncSession) -> int:
    """Rebuild the FTS index from scratch by scanning all articles.

    Used at startup if the FTS table is empty and articles exist, and
    by the admin reindex endpoint.

    Returns the number of articles indexed.
    """
    url = get_settings().database_url

    result = await session.execute(select(Article))
    articles = list(result.scalars().all())

    if not articles:
        return 0

    if is_postgres(url):
        # Postgres FTS uses the GIN index on the table itself — no separate
        # table to populate. The index is maintained automatically.
        return len(articles)

    # SQLite: clear and repopulate the FTS5 table
    await session.execute(sa_text("DELETE FROM article_fts"))

    count = 0
    for article in articles:
        content = await _read_content(article.file_path, article.user_id)
        await session.execute(
            sa_text("INSERT INTO article_fts(rowid, title, content) VALUES (:rowid, :title, :content)"),
            {
                "rowid": _article_id_to_rowid(article.id),
                "title": article.title,
                "content": content,
            },
        )
        count += 1

    await session.commit()
    log.info("FTS index rebuilt", articles_indexed=count)
    return count


# ---------------------------------------------------------------------------
# FTS sync helpers — called when articles are created/updated/deleted
# ---------------------------------------------------------------------------


async def index_article(
    session: AsyncSession,
    article_id: str,
    title: str,
    content: str,
) -> None:
    """Insert or replace an article in the FTS index.

    No-ops when the FTS table has not been created (e.g. in test fixtures
    that skip ``init_db``) or when running on Postgres (GIN index is
    maintained automatically by the database).

    Args:
        session: Active database session.
        article_id: The article UUID.
        title: Article title.
        content: Full article markdown content.
    """
    if not _fts_ready:
        return

    url = get_settings().database_url
    if is_postgres(url):
        return

    rowid = _article_id_to_rowid(article_id)

    # Delete any existing entry first (upsert pattern for FTS5)
    await session.execute(
        sa_text("DELETE FROM article_fts WHERE rowid = :rowid"),
        {"rowid": rowid},
    )
    await session.execute(
        sa_text("INSERT INTO article_fts(rowid, title, content) VALUES (:rowid, :title, :content)"),
        {"rowid": rowid, "title": title, "content": content},
    )


async def remove_article(session: AsyncSession, article_id: str) -> None:
    """Remove an article from the FTS index.

    No-ops when the FTS table has not been created or on Postgres.

    Args:
        session: Active database session.
        article_id: The article UUID.
    """
    if not _fts_ready:
        return

    url = get_settings().database_url
    if is_postgres(url):
        return

    rowid = _article_id_to_rowid(article_id)
    await session.execute(
        sa_text("DELETE FROM article_fts WHERE rowid = :rowid"),
        {"rowid": rowid},
    )


# ---------------------------------------------------------------------------
# Search query execution
# ---------------------------------------------------------------------------


async def search_articles(
    session: AsyncSession,
    query: str,
    user_id: str,
    limit: int = 20,
    offset: int = 0,
) -> FTSResponse:
    """Execute a full-text search and return ranked results with total count.

    Returns an :class:`FTSResponse` NamedTuple of (results, total) where
    results is a list of :class:`FTSResultItem` and total is the count of
    all matches before pagination.

    Args:
        session: Active database session.
        query: User search query string.
        user_id: Scope results to this user.
        limit: Maximum results to return.
        offset: Pagination offset.

    Returns:
        FTSResponse with typed result items ordered by relevance and total count.
    """
    if not _fts_ready:
        return FTSResponse(results=[], total=0)

    url = get_settings().database_url

    if is_postgres(url):
        return await _search_postgres(session, query, user_id, limit, offset)
    return await _search_sqlite(session, query, user_id, limit, offset)


async def _search_sqlite(
    session: AsyncSession,
    query: str,
    user_id: str,
    limit: int,
    offset: int,
) -> FTSResponse:
    """FTS5 search with BM25 ranking and snippet extraction.

    Uses a two-step approach: query the FTS5 table first for rowids and
    snippets, then join against the article table for user scoping.
    Returns an FTSResponse with typed results and total count.
    """
    fts_query = _sanitize_fts5_query(query)
    if not fts_query:
        return FTSResponse(results=[], total=0)

    # Fetch all FTS matches (no LIMIT) so we can compute accurate total
    # after user-scoping.  The FTS5 query itself is fast; the bottleneck
    # was loading all user Article ORM objects, which is fixed below.
    fts_sql = sa_text(
        "SELECT rowid, "
        "snippet(article_fts, 1, '<mark>', '</mark>', '...', 40) AS snippet, "
        "bm25(article_fts, 5.0, 1.0) AS rank "
        "FROM article_fts "
        "WHERE article_fts MATCH :query "
        "ORDER BY rank"
    )

    fts_result = await session.execute(fts_sql, {"query": fts_query})
    fts_rows = fts_result.all()

    if not fts_rows:
        return FTSResponse(results=[], total=0)

    # Build rowid -> (snippet, rank) map
    rowid_map: dict[int, tuple[str, float]] = {}
    for row in fts_rows:
        rowid_map[row[0]] = (row[1], row[2])

    # Map FTS rowids back to article IDs: fetch only the user's article IDs
    # (lightweight — no ORM hydration), compute their rowid hashes, and
    # select only the ones that matched the FTS query.
    id_result = await session.execute(select(Article.id).where(Article.user_id == user_id))
    user_article_ids = [row[0] for row in id_result.all()]

    matched_ids: list[str] = []
    id_to_rowid: dict[str, int] = {}
    for aid in user_article_ids:
        rowid = _article_id_to_rowid(aid)
        if rowid in rowid_map:
            matched_ids.append(aid)
            id_to_rowid[aid] = rowid

    if not matched_ids:
        return FTSResponse(results=[], total=0)

    # Load only the matched articles from the database
    article_result = await session.execute(
        select(Article).where(
            Article.id.in_(matched_ids),  # type: ignore[attr-defined]
            Article.user_id == user_id,
        )
    )
    matched_articles = list(article_result.scalars().all())

    results: list[FTSResultItem] = []
    for article in matched_articles:
        rowid = id_to_rowid[article.id]
        snippet, rank = rowid_map[rowid]
        results.append(
            FTSResultItem(
                article_id=article.id,
                slug=article.slug,
                title=article.title,
                snippet=snippet,
                rank=rank,
            )
        )

    # Sort by BM25 rank (lower is better in FTS5)
    results.sort(key=lambda r: r.rank)
    total = len(results)
    return FTSResponse(results=results[offset : offset + limit], total=total)


async def _search_postgres(
    session: AsyncSession,
    query: str,
    user_id: str,
    limit: int,
    offset: int,
) -> FTSResponse:
    """Postgres full-text search with ts_rank and ts_headline."""
    tsquery = _sanitize_postgres_query(query)
    if not tsquery:
        return FTSResponse(results=[], total=0)

    # Count total matches before pagination
    count_sql = sa_text(
        "SELECT count(*) "
        "FROM article "
        "WHERE to_tsvector('english', coalesce(title, '') "
        "  || ' ' || coalesce(summary, '')) "
        "  @@ to_tsquery('english', :query) "
        "AND user_id = :user_id"
    )
    count_result = await session.execute(count_sql, {"query": tsquery, "user_id": user_id})
    total = count_result.scalar() or 0

    sql = sa_text(
        "SELECT id, slug, title, "
        "ts_headline('english', coalesce(summary, ''), "
        "  to_tsquery('english', :query), "
        "  'StartSel=<mark>, StopSel=</mark>, MaxWords=40, MinWords=20'"
        ") AS snippet, "
        "ts_rank(to_tsvector('english', coalesce(title, '') "
        "  || ' ' || coalesce(summary, '')), "
        "  to_tsquery('english', :query)) AS rank "
        "FROM article "
        "WHERE to_tsvector('english', coalesce(title, '') "
        "  || ' ' || coalesce(summary, '')) "
        "  @@ to_tsquery('english', :query) "
        "AND user_id = :user_id "
        "ORDER BY rank DESC "
        "LIMIT :limit OFFSET :offset"
    )

    result = await session.execute(
        sql,
        {
            "query": tsquery,
            "user_id": user_id,
            "limit": limit,
            "offset": offset,
        },
    )

    results = [
        FTSResultItem(
            article_id=row[0],
            slug=row[1],
            title=row[2],
            snippet=row[3],
            rank=row[4],
        )
        for row in result.all()
    ]
    return FTSResponse(results=results, total=total)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _article_id_to_rowid(article_id: str) -> int:
    """Deterministic 63-bit positive integer from article ID.

    FTS5 requires integer rowids. We use MD5 (not security-sensitive) and
    mask to 63 bits to stay within SQLite's signed 64-bit integer range.

    Unlike Python's built-in ``hash()``, this is deterministic across
    process restarts regardless of PYTHONHASHSEED.
    """
    digest = hashlib.md5(article_id.encode(), usedforsecurity=False).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF


def _sanitize_fts5_query(query: str) -> str:
    """Sanitize user input for safe use in an FTS5 MATCH expression.

    Wraps each word in double quotes to disable FTS5 query operators
    (AND, OR, NOT, NEAR, etc.) and appends ``*`` for prefix matching.
    """
    words = query.strip().split()
    if not words:
        return ""
    # Strip double-quotes to avoid malformed FTS5 expressions, then
    # quote each word and add prefix wildcard for partial matching.
    parts = []
    for w in words:
        cleaned = w.replace('"', "")
        if cleaned:
            parts.append(f'"{cleaned}"*')
    return " ".join(parts)


def _sanitize_postgres_query(query: str) -> str:
    """Sanitize user input for safe use in a Postgres tsquery.

    Joins words with ``&`` (AND) and appends ``:*`` for prefix matching.
    """
    words = query.strip().split()
    if not words:
        return ""
    # Escape special characters and join with AND
    safe_words = []
    for w in words:
        # Remove characters that could break tsquery syntax
        cleaned = "".join(c for c in w if c.isalnum() or c in "-_")
        if cleaned:
            safe_words.append(f"{cleaned}:*")
    return " & ".join(safe_words)


async def _read_content(file_path: str, user_id: str) -> str:
    """Read article content from disk for indexing."""
    try:
        storage = get_wiki_storage(user_id)
        return await storage.read(file_path)
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------


class SearchService:
    """Thin wrapper providing a DI-friendly interface for FastAPI routes."""

    async def search(
        self,
        query: str,
        session: AsyncSession,
        user_id: str,
        limit: int = 20,
        offset: int = 0,
        source_kind: str | None = None,
        page_type: str | None = None,
        concept: str | None = None,
        tag: str | None = None,
        date_range: str | None = None,
        staleness: str | None = None,
        sort: str | None = None,
    ) -> FTSResponse:
        """Execute full-text search with optional facet filters.

        Args:
            query: Search query string.
            session: Database session.
            user_id: Current user.
            limit: Max results per page.
            offset: Pagination offset.
            source_kind: Filter by source type (pdf, url, text, etc.).
            page_type: Filter by article page type.
            concept: Filter by concept name.
            tag: Filter by tag ID.
            date_range: Filter by date range (7d, 30d, 365d).
            staleness: Filter by staleness bucket (low, medium, high).
            sort: Sort order (relevance, recency).
        """
        fts_response = await search_articles(
            session,
            query,
            user_id,
            limit=1000,
            offset=0,
        )
        if not fts_response.results:
            return FTSResponse(results=[], total=0)

        article_ids = [r.article_id for r in fts_response.results]

        # Apply facet filters to narrow the matched set
        filtered_ids = await _apply_facet_filters(
            session,
            article_ids=article_ids,
            user_id=user_id,
            source_kind=source_kind,
            page_type=page_type,
            concept=concept,
            tag=tag,
            date_range=date_range,
            staleness=staleness,
        )

        filtered_results = [r for r in fts_response.results if r.article_id in filtered_ids]

        # Apply sort
        if sort == "recency":
            article_dates = await _get_article_dates(session, filtered_ids)
            filtered_results.sort(
                key=lambda r: article_dates.get(r.article_id, utcnow_naive()),
                reverse=True,
            )
        # Default is relevance (already sorted by rank from FTS)

        total = len(filtered_results)
        return FTSResponse(
            results=filtered_results[offset : offset + limit],
            total=total,
        )

    async def get_facets(
        self,
        query: str,
        session: AsyncSession,
        user_id: str,
    ) -> FacetResponse:
        """Compute facet counts for the current query.

        Returns counts for: source_kind, page_type, concept, tag,
        date_range, and staleness.

        Args:
            query: Search query string.
            session: Database session.
            user_id: Current user.
        """
        fts_response = await search_articles(
            session,
            query,
            user_id,
            limit=1000,
            offset=0,
        )
        if not fts_response.results:
            return FacetResponse(facets=[], total=0, query=query)

        article_ids = [r.article_id for r in fts_response.results]

        facets = await _compute_facets(session, article_ids, user_id)
        return FacetResponse(facets=facets, total=len(article_ids), query=query)


async def _apply_facet_filters(
    session: AsyncSession,
    article_ids: list[str],
    user_id: str,
    source_kind: str | None = None,
    page_type: str | None = None,
    concept: str | None = None,
    tag: str | None = None,
    date_range: str | None = None,
    staleness: str | None = None,
) -> set[str]:
    """Narrow a set of article IDs by facet filter criteria."""
    remaining = set(article_ids)

    if page_type:
        result = await session.execute(
            select(Article.id).where(
                Article.id.in_(article_ids),  # type: ignore[attr-defined]
                Article.user_id == user_id,
                Article.page_type == page_type,
            )
        )
        remaining &= {r[0] for r in result.all()}

    if source_kind:
        # Filter articles whose sources include the given type
        result = await session.execute(
            select(ArticleSource.article_id).where(
                ArticleSource.article_id.in_(article_ids),  # type: ignore[attr-defined]
                ArticleSource.source_id.in_(  # type: ignore[attr-defined]
                    select(Source.id).where(
                        Source.user_id == user_id,
                        Source.source_type == source_kind,
                    )
                ),
            )
        )
        remaining &= {r[0] for r in result.all()}

    if concept:
        result = await session.execute(
            select(ArticleConcept.article_id).where(
                ArticleConcept.article_id.in_(  # type: ignore[attr-defined]
                    article_ids,
                ),
                ArticleConcept.concept_name == concept,
            )
        )
        remaining &= {r[0] for r in result.all()}

    if tag:
        result = await session.execute(
            select(ArticleTag.article_id).where(
                ArticleTag.article_id.in_(article_ids),  # type: ignore[attr-defined]
                ArticleTag.tag_id == tag,
            )
        )
        remaining &= {r[0] for r in result.all()}

    if date_range:
        now = utcnow_naive()
        days = {"7d": 7, "30d": 30, "365d": 365}.get(date_range)
        if days is not None:
            from datetime import timedelta  # noqa: PLC0415

            cutoff = now - timedelta(days=days)
            result = await session.execute(
                select(Article.id).where(
                    Article.id.in_(article_ids),  # type: ignore[attr-defined]
                    Article.user_id == user_id,
                    Article.updated_at >= cutoff,
                )
            )
            remaining &= {r[0] for r in result.all()}

    if staleness:
        # Load articles and compute staleness
        staleness_stmt = select(Article).where(
            Article.id.in_(list(remaining)),  # type: ignore[attr-defined]
            Article.user_id == user_id,
        )
        staleness_result = await session.execute(staleness_stmt)
        articles = list(staleness_result.scalars().all())
        settings = get_settings()
        staleness_ids: set[str] = set()
        for a in articles:
            score = _compute_article_staleness(a, settings.staleness.decay_rate)
            if _matches_staleness_bucket(staleness, score):
                staleness_ids.add(a.id)
        remaining &= staleness_ids

    return remaining


async def _get_article_dates(
    session: AsyncSession,
    article_ids: set[str],
) -> dict[str, datetime]:
    """Fetch updated_at dates for articles."""
    if not article_ids:
        return {}
    result = await session.execute(
        select(Article.id, Article.updated_at).where(
            Article.id.in_(list(article_ids)),  # type: ignore[attr-defined]
        )
    )
    return {r[0]: r[1] for r in result.all()}


def _compute_article_staleness(article: Article, decay_rate: float) -> float:
    """Compute staleness score for an article."""
    if article.last_reinforced_at is None:
        return 1.0
    days = (utcnow_naive() - article.last_reinforced_at).total_seconds() / 86400
    return compute_staleness(days, decay_rate=decay_rate)


def _matches_staleness_bucket(bucket: str, score: float) -> bool:
    """Check whether a staleness score falls in the named bucket."""
    if bucket == "low":
        return score < 0.3
    if bucket == "medium":
        return 0.3 <= score <= 0.7
    if bucket == "high":
        return score > 0.7
    return False


async def _compute_facets(
    session: AsyncSession,
    article_ids: list[str],
    user_id: str,
) -> list[FacetGroup]:
    """Compute all facet groups for a set of matched article IDs."""
    facets: list[FacetGroup] = []

    facets += await _facet_page_type(session, article_ids, user_id)
    facets += await _facet_source_kind(session, article_ids, user_id)
    facets += await _facet_concept(session, article_ids)
    facets += await _facet_tag(session, article_ids, user_id)
    facets += await _facet_date(session, article_ids, user_id)
    facets += await _facet_staleness(session, article_ids, user_id)

    return facets


def _counter_to_group(name: str, counts: Counter[str]) -> list[FacetGroup]:
    """Build a FacetGroup from a Counter, returning empty list if no counts."""
    if not counts:
        return []
    return [
        FacetGroup(
            name=name,
            buckets=[FacetBucket(value=k, count=v) for k, v in sorted(counts.items(), key=lambda x: -x[1])],
        )
    ]


async def _facet_page_type(
    session: AsyncSession,
    article_ids: list[str],
    user_id: str,
) -> list[FacetGroup]:
    result = await session.execute(
        select(Article.page_type).where(
            Article.id.in_(article_ids),  # type: ignore[attr-defined]
            Article.user_id == user_id,
        )
    )
    counts: Counter[str] = Counter(row[0] for row in result.all())
    return _counter_to_group("page_type", counts)


async def _facet_source_kind(
    session: AsyncSession,
    article_ids: list[str],
    user_id: str,
) -> list[FacetGroup]:
    result = await session.execute(
        select(Source.source_type).where(
            Source.id.in_(  # type: ignore[attr-defined]
                select(ArticleSource.source_id).where(
                    ArticleSource.article_id.in_(  # type: ignore[attr-defined]
                        article_ids,
                    )
                )
            ),
            Source.user_id == user_id,
        )
    )
    counts: Counter[str] = Counter(row[0] for row in result.all())
    return _counter_to_group("source_kind", counts)


async def _facet_concept(
    session: AsyncSession,
    article_ids: list[str],
) -> list[FacetGroup]:
    result = await session.execute(
        select(ArticleConcept.concept_name).where(
            ArticleConcept.article_id.in_(article_ids),  # type: ignore[attr-defined]
        )
    )
    counts: Counter[str] = Counter(row[0] for row in result.all())
    return _counter_to_group("concept", counts)


async def _facet_tag(
    session: AsyncSession,
    article_ids: list[str],
    user_id: str,
) -> list[FacetGroup]:
    tag_stmt = (
        select(Tag.name, Tag.id)
        .join(
            ArticleTag,
            ArticleTag.tag_id == Tag.id,  # type: ignore[arg-type]
        )
        .where(
            ArticleTag.article_id.in_(article_ids),  # type: ignore[attr-defined]
            Tag.user_id == user_id,
        )
    )
    result = await session.execute(tag_stmt)
    counts: Counter[str] = Counter(row[0] for row in result.all())
    return _counter_to_group("tag", counts)


async def _facet_date(
    session: AsyncSession,
    article_ids: list[str],
    user_id: str,
) -> list[FacetGroup]:
    from datetime import timedelta  # noqa: PLC0415

    now = utcnow_naive()
    result = await session.execute(
        select(Article.updated_at).where(
            Article.id.in_(article_ids),  # type: ignore[attr-defined]
            Article.user_id == user_id,
        )
    )
    buckets: dict[str, int] = {"7d": 0, "30d": 0, "365d": 0}
    for row in result.all():
        updated = row[0]
        if updated >= now - timedelta(days=7):
            buckets["7d"] += 1
        if updated >= now - timedelta(days=30):
            buckets["30d"] += 1
        if updated >= now - timedelta(days=365):
            buckets["365d"] += 1
    return [
        FacetGroup(
            name="date",
            buckets=[FacetBucket(value=k, count=v) for k, v in buckets.items() if v > 0],
        )
    ]


async def _facet_staleness(
    session: AsyncSession,
    article_ids: list[str],
    user_id: str,
) -> list[FacetGroup]:
    result = await session.execute(
        select(Article).where(
            Article.id.in_(article_ids),  # type: ignore[attr-defined]
            Article.user_id == user_id,
        )
    )
    buckets: dict[str, int] = {"low": 0, "medium": 0, "high": 0}
    settings = get_settings()
    for a in result.scalars().all():
        score = _compute_article_staleness(a, settings.staleness.decay_rate)
        if score < 0.3:
            buckets["low"] += 1
        elif score <= 0.7:
            buckets["medium"] += 1
        else:
            buckets["high"] += 1
    return [
        FacetGroup(
            name="staleness",
            buckets=[FacetBucket(value=k, count=v) for k, v in buckets.items() if v > 0],
        )
    ]


@functools.lru_cache(maxsize=1)
def get_search_service() -> SearchService:
    """Return a singleton SearchService for FastAPI dependency injection."""
    return SearchService()
