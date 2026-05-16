"""WikiMind MCP server — Phase 1 read-only tools over stdio transport.

Exposes four tools to MCP clients (Claude Desktop, Cursor, etc.):
  - wiki_search:       full-text search across wiki articles
  - wiki_get_article:  retrieve a full article by ID or slug
  - wiki_ask:          ask a question against the wiki (Q&A agent)
  - wiki_list_sources: list ingested sources

The server supports stdio (default) and HTTP transports.
HTTP transport requires JWT authentication (configurable via
``WIKIMIND_MCP__REQUIRE_AUTH``). Stdio transport never requires auth.

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
from mcp.server.auth.middleware.auth_context import auth_context_var
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
        "ask questions, and browse ingested sources."
    ),
    lifespan=_lifespan,
)


# ---------------------------------------------------------------------------
# Session helper — standalone (not FastAPI DI)
# ---------------------------------------------------------------------------


async def _get_mcp_user_id() -> str:
    """Return the user ID for MCP operations.

    When accessed via authenticated HTTP transport, extracts user_id
    from the JWT token's claims (set by WikiMindJWTAuthProvider).
    Falls back to the dev user for stdio transport or when auth is
    disabled.
    """
    # Check if we have an authenticated user from HTTP transport.
    # WikiMindJWTAuthProvider sets client_id = user_id (from JWT "sub" claim).
    auth_user = auth_context_var.get(None)
    if auth_user is not None and auth_user.access_token.client_id:
        return auth_user.access_token.client_id

    # Fallback: stdio transport or dev mode — use dev user
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
# Entry point
# ---------------------------------------------------------------------------


def run_server() -> None:
    """Run the WikiMind MCP server.

    Supports stdio (default) and HTTP transports via --transport flag.
    HTTP transport enforces JWT authentication by default (configurable
    via WIKIMIND_MCP__REQUIRE_AUTH).
    """
    parser = argparse.ArgumentParser(description="WikiMind MCP Server")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9100)
    args = parser.parse_args()

    if args.transport == "http":
        settings = get_settings()
        if settings.mcp.require_auth:
            from wikimind.mcp.auth import WikiMindJWTAuthProvider  # noqa: PLC0415

            mcp.auth = WikiMindJWTAuthProvider()
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    run_server()
