"""Full-text search service — FTS5 on SQLite, tsvector on Postgres.

Provides BM25-ranked full-text search across wiki article titles and content.
The FTS index is maintained in sync with article creates/updates/deletes via
explicit helper functions called from the compiler and delete paths.

Phase 1 focuses on keyword search only. Phase 2 will layer vector search on
top via the existing ``EmbeddingService``.
"""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import text as sa_text
from sqlmodel import select

from wikimind.config import get_settings
from wikimind.db_compat import is_postgres
from wikimind.models import Article
from wikimind.storage import get_wiki_storage

if TYPE_CHECKING:
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
) -> list[dict]:
    """Execute a full-text search and return ranked results.

    Returns a list of dicts with keys: article_id, title, slug, snippet, rank.

    Args:
        session: Active database session.
        query: User search query string.
        user_id: Scope results to this user.
        limit: Maximum results to return.
        offset: Pagination offset.

    Returns:
        List of search result dicts ordered by relevance.
    """
    if not _fts_ready:
        return []

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
) -> list[dict]:
    """FTS5 search with BM25 ranking and snippet extraction.

    Uses a two-step approach: query the FTS5 table first for rowids and
    snippets, then join against the article table in Python for user scoping.
    This avoids needing a custom SQL function in SQLite.
    """
    fts_query = _sanitize_fts5_query(query)
    if not fts_query:
        return []

    fts_sql = sa_text(
        "SELECT rowid, "
        "snippet(article_fts, 1, '<mark>', '</mark>', '...', 40) AS snippet, "
        "bm25(article_fts, 5.0, 1.0) AS rank "
        "FROM article_fts "
        "WHERE article_fts MATCH :query "
        "ORDER BY rank "
        "LIMIT :limit_padded"
    )

    # Fetch more than needed since we'll filter by user_id in Python
    limit_padded = limit + offset + 50
    fts_result = await session.execute(fts_sql, {"query": fts_query, "limit_padded": limit_padded})
    fts_rows = fts_result.all()

    if not fts_rows:
        return []

    # Build rowid -> (snippet, rank) map
    rowid_map: dict[int, tuple[str, float]] = {}
    for row in fts_rows:
        rowid_map[row[0]] = (row[1], row[2])

    # Fetch user's articles and match by rowid hash
    article_result = await session.execute(select(Article).where(Article.user_id == user_id))
    all_user_articles = list(article_result.scalars().all())

    results: list[dict] = []
    for article in all_user_articles:
        rowid = _article_id_to_rowid(article.id)
        if rowid in rowid_map:
            snippet, rank = rowid_map[rowid]
            results.append(
                {
                    "article_id": article.id,
                    "slug": article.slug,
                    "title": article.title,
                    "snippet": snippet,
                    "rank": rank,
                }
            )

    # Sort by BM25 rank (lower is better in FTS5)
    results.sort(key=lambda r: r["rank"])
    return results[offset : offset + limit]


async def _search_postgres(
    session: AsyncSession,
    query: str,
    user_id: str,
    limit: int,
    offset: int,
) -> list[dict]:
    """Postgres full-text search with ts_rank and ts_headline."""
    tsquery = _sanitize_postgres_query(query)
    if not tsquery:
        return []

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

    return [
        {
            "article_id": row[0],
            "slug": row[1],
            "title": row[2],
            "snippet": row[3],
            "rank": row[4],
        }
        for row in result.all()
    ]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _article_id_to_rowid(article_id: str) -> int:
    """Convert a UUID string to a positive 64-bit integer for FTS5 rowid.

    FTS5 requires integer rowids. We hash the UUID and mask to 63 bits
    to stay within SQLite's signed 64-bit integer range.
    """
    return hash(article_id) & 0x7FFFFFFFFFFFFFFF


def _sanitize_fts5_query(query: str) -> str:
    """Sanitize user input for safe use in an FTS5 MATCH expression.

    Wraps each word in double quotes to disable FTS5 query operators
    (AND, OR, NOT, NEAR, etc.) and appends ``*`` for prefix matching.
    """
    words = query.strip().split()
    if not words:
        return ""
    # Quote each word and add prefix wildcard for partial matching
    parts = [f'"{w}"*' for w in words if w]
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
    ) -> list[dict]:
        """Execute full-text search, returning ranked result dicts."""
        return await search_articles(session, query, user_id, limit, offset)


@functools.lru_cache(maxsize=1)
def get_search_service() -> SearchService:
    """Return a singleton SearchService for FastAPI dependency injection."""
    return SearchService()
