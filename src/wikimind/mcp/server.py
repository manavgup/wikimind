"""WikiMind MCP server — read and write tools over stdio transport.

Exposes tools to MCP clients (Claude Desktop, Cursor, etc.):

Read tools:
  - wiki_search:       full-text search across wiki articles
  - wiki_get_article:  retrieve a full article by ID or slug
  - wiki_ask:          ask a question against the wiki (Q&A agent)
  - wiki_list_sources: list ingested sources

Write tools:
  - wiki_ingest_url:   ingest a URL source into the wiki
  - wiki_ingest_text:  ingest raw text into the wiki
  - wiki_list_articles: list all articles with summaries
  - wiki_recompile:    trigger recompilation of an article

The server supports stdio (default) and HTTP transports.

Usage:
    wikimind mcp serve
    wikimind mcp serve --transport http --port 9100
    python -m wikimind.mcp.server
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import sys
from typing import TYPE_CHECKING, Any

import structlog
from fastmcp import FastMCP
from pydantic import Field

from wikimind.config import get_settings
from wikimind.database import get_dev_user_id, get_session_factory, init_db
from wikimind.models import QueryRequest
from wikimind.services.ingest import IngestService
from wikimind.services.query import QueryService
from wikimind.services.wiki import WikiService

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

# ---------------------------------------------------------------------------
# Logging — stderr so it does not interfere with stdio transport
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)

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
        "ask questions, browse ingested sources, ingest new content, "
        "and trigger recompilation."
    ),
    lifespan=_lifespan,
)


# ---------------------------------------------------------------------------
# Session helper — standalone (not FastAPI DI)
# ---------------------------------------------------------------------------


async def _get_mcp_user_id() -> str:
    """Return the user ID for MCP operations.

    In dev mode, uses the auto-provisioned dev user. MCP is a local
    tool — it always runs in the same environment as the server.
    """
    return await get_dev_user_id()


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
async def wiki_search(
    query: str = Field(..., description="Search query string (minimum 2 characters)"),
    limit: int = Field(10, description="Maximum results to return (max 50)"),
) -> str:
    """Search wiki articles by keyword query."""
    limit = min(max(1, limit), 50)
    if len(query.strip()) < 2:
        return json.dumps({"error": "Query must be at least 2 characters"})

    wiki_service = WikiService()
    async with _get_session() as session:
        results = await wiki_service.search(
            q=query,
            session=session,
            user_id=await _get_mcp_user_id(),
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
async def wiki_get_article(
    id_or_slug: str = Field(..., description="Article UUID or URL slug"),
) -> str:
    """Retrieve a full wiki article by ID or slug."""
    wiki_service = WikiService()
    async with _get_session() as session:
        try:
            article = await wiki_service.get_article(
                id_or_slug=id_or_slug,
                session=session,
                user_id=await _get_mcp_user_id(),
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
async def wiki_ask(
    question: str = Field(..., description="The question to ask against the wiki knowledge base"),
) -> str:
    """Ask a question and get an answer from the wiki."""
    if not question.strip():
        return json.dumps({"error": "Question cannot be empty"})

    query_service = QueryService()
    request = QueryRequest(question=question)

    async with _get_session() as session:
        try:
            result = await query_service.ask(
                request=request,
                session=session,
                user_id=await _get_mcp_user_id(),
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
    status: str | None = Field(None, description="Optional status filter (e.g. 'compiled', 'pending')"),
    limit: int = Field(20, description="Maximum number of results (default 20, max 100)"),
) -> str:
    """List ingested sources with optional status filtering."""
    limit = min(max(1, limit), 100)
    ingest_service = IngestService()

    async with _get_session() as session:
        sources = await ingest_service.list_sources(
            session=session,
            user_id=await _get_mcp_user_id(),
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
# Tool: wiki_ingest_url
# ---------------------------------------------------------------------------


@mcp.tool(
    name="wiki_ingest_url",
    description=(
        "Ingest a URL (web page or YouTube video) into the WikiMind knowledge base. "
        "The content is fetched, cleaned, and scheduled for compilation into a wiki article. "
        "Returns the created source record with its ID and status."
    ),
)
async def wiki_ingest_url(
    url: str = Field(..., description="The URL to ingest (web page or YouTube video)"),
    title: str | None = Field(None, description="Optional title override for the source"),
) -> str:
    """Ingest a URL source into the wiki."""
    if not url or not url.strip():
        return json.dumps({"error": "URL cannot be empty"})

    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return json.dumps({"error": "URL must start with http:// or https://"})

    ingest_service = IngestService()
    async with _get_session() as session:
        try:
            source = await ingest_service.ingest_url(
                url=url,
                session=session,
                user_id=await _get_mcp_user_id(),
            )
        except Exception as exc:
            log.warning("wiki_ingest_url failed", url=url, error=str(exc))
            return json.dumps({"error": f"Ingestion failed: {exc}"})

        # Apply user-provided title override (persisted by session commit)
        if title and title.strip():
            source.title = title.strip()

    return json.dumps(
        {
            "id": source.id,
            "source_type": source.source_type,
            "title": source.title,
            "source_url": source.source_url,
            "status": "scheduled_for_compilation",
        },
        default=str,
    )


# ---------------------------------------------------------------------------
# Tool: wiki_ingest_text
# ---------------------------------------------------------------------------


@mcp.tool(
    name="wiki_ingest_text",
    description=(
        "Ingest raw text content into the WikiMind knowledge base. "
        "The text is stored as a source and scheduled for compilation into a wiki article. "
        "Useful for adding notes, excerpts, or any textual content to the wiki."
    ),
)
async def wiki_ingest_text(
    text: str = Field(..., description="The text content to ingest"),
    title: str = Field(..., description="Title for the source"),
) -> str:
    """Ingest raw text content into the wiki."""
    if not text or not text.strip():
        return json.dumps({"error": "Text content cannot be empty"})

    if not title or not title.strip():
        return json.dumps({"error": "Title cannot be empty"})

    ingest_service = IngestService()
    async with _get_session() as session:
        try:
            source = await ingest_service.ingest_text(
                content=text.strip(),
                title=title.strip(),
                session=session,
                user_id=await _get_mcp_user_id(),
            )
        except Exception as exc:
            log.warning("wiki_ingest_text failed", title=title, error=str(exc))
            return json.dumps({"error": f"Ingestion failed: {exc}"})

    return json.dumps(
        {
            "id": source.id,
            "source_type": source.source_type,
            "title": source.title,
            "status": "scheduled_for_compilation",
        },
        default=str,
    )


# ---------------------------------------------------------------------------
# Tool: wiki_list_articles
# ---------------------------------------------------------------------------


@mcp.tool(
    name="wiki_list_articles",
    description=(
        "List all wiki articles with their summaries. "
        "Returns article titles, slugs, summaries, confidence scores, "
        "and source counts. Use this to browse the wiki content."
    ),
)
async def wiki_list_articles(
    limit: int = Field(20, description="Maximum number of articles to return (max 100)"),
    offset: int = Field(0, description="Pagination offset (skip this many articles)"),
) -> str:
    """List wiki articles with summaries."""
    limit = min(max(1, limit), 100)
    offset = max(0, offset)

    wiki_service = WikiService()
    async with _get_session() as session:
        try:
            articles = await wiki_service.list_articles(
                session=session,
                user_id=await _get_mcp_user_id(),
                limit=limit,
                offset=offset,
            )
        except Exception as exc:
            log.warning("wiki_list_articles failed", error=str(exc))
            return json.dumps({"error": f"Failed to list articles: {exc}"})

    return json.dumps(
        [
            {
                "id": a.id,
                "slug": a.slug,
                "title": a.title,
                "summary": a.summary,
                "confidence": a.confidence,
                "confidence_score": a.confidence_score,
                "source_count": a.source_count,
                "page_type": a.page_type,
                "created_at": a.created_at,
                "updated_at": a.updated_at,
            }
            for a in articles
        ],
        default=str,
    )


# ---------------------------------------------------------------------------
# Tool: wiki_recompile
# ---------------------------------------------------------------------------


@mcp.tool(
    name="wiki_recompile",
    description=(
        "Trigger recompilation of a wiki article by its slug or ID. "
        "This re-runs the LLM compiler on the article's sources to produce "
        "an updated wiki page. Use when sources have changed or you want "
        "to improve article quality."
    ),
)
async def wiki_recompile(
    article_slug: str = Field(..., description="Article slug or UUID to recompile"),
) -> str:
    """Trigger recompilation of a wiki article."""
    if not article_slug or not article_slug.strip():
        return json.dumps({"error": "Article slug cannot be empty"})

    wiki_service = WikiService()
    async with _get_session() as session:
        try:
            # First resolve the slug/id to the article's UUID
            article_id = await wiki_service._resolve_article_id(
                article_slug.strip(),
                session,
                user_id=await _get_mcp_user_id(),
            )
            if article_id is None:
                return json.dumps({"error": "Article not found"})

            result = await wiki_service.recompile_article(
                article_id=article_id,
                session=session,
                user_id=await _get_mcp_user_id(),
            )
        except Exception as exc:
            log.warning("wiki_recompile failed", slug=article_slug, error=str(exc))
            return json.dumps({"error": f"Recompilation failed: {exc}"})

    return json.dumps(
        {
            "status": result.status,
            "job_id": result.job_id,
            "article_slug": article_slug.strip(),
        },
        default=str,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_server() -> None:
    """Run the WikiMind MCP server.

    Supports stdio (default) and HTTP transports via --transport flag.
    """
    parser = argparse.ArgumentParser(description="WikiMind MCP Server")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9100)
    args = parser.parse_args()

    if args.transport == "http":
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    run_server()
