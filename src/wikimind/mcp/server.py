"""WikiMind MCP server — Phase 1 read-only tools over stdio transport.

Exposes four tools to MCP clients (Claude Desktop, Cursor, etc.):
  - wiki_search:       full-text search across wiki articles
  - wiki_get_article:  retrieve a full article by ID or slug
  - wiki_ask:          ask a question against the wiki (Q&A agent)
  - wiki_list_sources: list ingested sources

The server runs in stdio mode for local use. A config snippet for
Claude Desktop is printed on startup.

Usage:
    wikimind mcp serve
    python -m wikimind.mcp.server
"""

from __future__ import annotations

import contextlib
import json
from typing import TYPE_CHECKING, Any

import structlog
from mcp.server.fastmcp import FastMCP

from wikimind.api.deps import ANONYMOUS_USER_ID
from wikimind.config import get_settings
from wikimind.database import get_session_factory, init_db
from wikimind.models import QueryRequest
from wikimind.services.ingest import IngestService
from wikimind.services.query import QueryService
from wikimind.services.wiki import WikiService

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

log = structlog.get_logger()

# MCP spec version pinned for stability (see issue #447 risk: spec churn).
MCP_SPEC_VERSION = "2025-03-26"


@contextlib.asynccontextmanager
async def _lifespan(_server: FastMCP) -> AsyncGenerator[dict[str, Any], None]:
    """Initialize the database on server startup."""
    settings = get_settings()
    settings.ensure_dirs()
    await init_db()
    log.info(
        "WikiMind MCP server started",
        mcp_spec_version=MCP_SPEC_VERSION,
        data_dir=settings.data_dir,
    )
    yield {}


mcp = FastMCP(
    name="wikimind",
    instructions=(
        "WikiMind is a personal LLM-powered knowledge OS. "
        "Use these tools to search the wiki, read articles, "
        "ask questions, and browse ingested sources."
    ),
    lifespan=_lifespan,
)


# ---------------------------------------------------------------------------
# Session helper — standalone (not FastAPI DI)
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def _get_session():
    """Yield an async database session for MCP tool handlers."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ---------------------------------------------------------------------------
# Tool: wiki_search
# ---------------------------------------------------------------------------


@mcp.tool(
    name="wiki_search",
    description=(
        "Search wiki articles by keyword. Returns article titles, "
        "summaries, and IDs ranked by relevance. Use this to find "
        "articles on a topic before reading the full content."
    ),
)
async def wiki_search(query: str, limit: int = 10) -> str:
    """Search wiki articles by keyword query.

    Args:
        query: Search query string (minimum 2 characters).
        limit: Maximum number of results to return (default 10, max 50).

    Returns:
        JSON array of matching articles with id, slug, title, and summary.
    """
    limit = min(max(1, limit), 50)
    if len(query.strip()) < 2:
        return json.dumps({"error": "Query must be at least 2 characters"})

    wiki_service = WikiService()
    async with _get_session() as session:
        results = await wiki_service.search(
            q=query,
            session=session,
            user_id=ANONYMOUS_USER_ID,
            limit=limit,
        )

    return json.dumps(
        [
            {
                "id": r.id,
                "slug": r.slug,
                "title": r.title,
                "summary": r.summary,
                "confidence": r.confidence,
                "source_count": r.source_count,
            }
            for r in results
        ],
        default=str,
    )


# ---------------------------------------------------------------------------
# Tool: wiki_get_article
# ---------------------------------------------------------------------------


@mcp.tool(
    name="wiki_get_article",
    description=(
        "Retrieve the full content of a wiki article by its ID or slug. "
        "Returns the article title, markdown content, sources, and metadata. "
        "Use wiki_search first to find the article ID."
    ),
)
async def wiki_get_article(id_or_slug: str) -> str:
    """Retrieve a full wiki article by ID or slug.

    Args:
        id_or_slug: Article UUID or URL slug.

    Returns:
        JSON object with article title, content (markdown), sources, and metadata.
    """
    wiki_service = WikiService()
    async with _get_session() as session:
        try:
            article = await wiki_service.get_article(
                id_or_slug=id_or_slug,
                session=session,
                user_id=ANONYMOUS_USER_ID,
            )
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    return json.dumps(
        {
            "id": article.id,
            "slug": article.slug,
            "title": article.title,
            "summary": article.summary,
            "content": article.content,
            "confidence": article.confidence,
            "page_type": article.page_type,
            "sources": [
                {
                    "id": s.id,
                    "source_type": s.source_type,
                    "title": s.title,
                    "source_url": s.source_url,
                }
                for s in (article.sources or [])
            ],
            "created_at": article.created_at,
            "updated_at": article.updated_at,
        },
        default=str,
    )


# ---------------------------------------------------------------------------
# Tool: wiki_ask
# ---------------------------------------------------------------------------


@mcp.tool(
    name="wiki_ask",
    description=(
        "Ask a question against the WikiMind knowledge base. "
        "The Q&A agent searches relevant articles and synthesizes "
        "an answer with citations. Use this for complex questions "
        "that span multiple articles."
    ),
)
async def wiki_ask(question: str) -> str:
    """Ask a question and get an answer from the wiki.

    Args:
        question: The question to ask against the wiki knowledge base.

    Returns:
        JSON object with the answer, confidence, and cited article titles.
    """
    if not question.strip():
        return json.dumps({"error": "Question cannot be empty"})

    query_service = QueryService()
    request = QueryRequest(question=question)

    async with _get_session() as session:
        try:
            result = await query_service.ask(
                request=request,
                session=session,
                user_id=ANONYMOUS_USER_ID,
            )
        except Exception as exc:
            log.warning("wiki_ask failed", error=str(exc))
            return json.dumps({"error": f"Q&A failed: {exc}"})

    return json.dumps(
        {
            "answer": result.query.answer,
            "confidence": result.query.confidence,
            "citations": [
                {
                    "article_title": c.article.title,
                    "article_slug": c.article.slug,
                    "confidence_score": c.confidence_score,
                }
                for c in (result.query.citations or [])
            ],
        },
        default=str,
    )


# ---------------------------------------------------------------------------
# Tool: wiki_list_sources
# ---------------------------------------------------------------------------


@mcp.tool(
    name="wiki_list_sources",
    description=(
        "List ingested sources in the WikiMind knowledge base. "
        "Shows what content has been fed into the wiki (URLs, PDFs, "
        "text, YouTube). Optionally filter by status."
    ),
)
async def wiki_list_sources(
    status: str | None = None,
    limit: int = 20,
) -> str:
    """List ingested sources with optional status filtering.

    Args:
        status: Optional status filter (e.g. 'compiled', 'pending').
        limit: Maximum number of results (default 20, max 100).

    Returns:
        JSON array of sources with id, type, title, URL, and ingestion date.
    """
    limit = min(max(1, limit), 100)
    ingest_service = IngestService()

    async with _get_session() as session:
        sources = await ingest_service.list_sources(
            session=session,
            user_id=ANONYMOUS_USER_ID,
            status=status,
            limit=limit,
        )

    return json.dumps(
        [
            {
                "id": s.id,
                "source_type": s.source_type,
                "title": s.title,
                "source_url": s.source_url,
                "ingested_at": s.ingested_at,
                "compiled_at": s.compiled_at,
            }
            for s in sources
        ],
        default=str,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_server() -> None:
    """Run the WikiMind MCP server over stdio transport."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    run_server()
