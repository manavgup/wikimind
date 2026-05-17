"""WikiMind MCP server — 13 tools, 3 resources, 4 prompts.

Exposes the WikiMind knowledge base to MCP clients (Claude Desktop,
AI agents). Supports stdio (local, no auth) and HTTP (JWT auth) transports.

Tools by tier:
  - Discovery (Tier 1): wiki_overview, wiki_list_articles, wiki_list_concepts
  - Read/Search (Tier 2): wiki_search, wiki_get_article, wiki_ask
  - Write (Tier 3): wiki_ingest_url, wiki_ingest_text, wiki_get_source_status
  - Analysis (Tier 4): wiki_synthesize, wiki_get_health, wiki_list_sources, wiki_get_graph

Resources:
  - wikimind://index — article table of contents
  - wikimind://articles/{slug} — full article markdown
  - wikimind://sources/{source_id} — source metadata JSON

Prompts:
  - wiki_onboarding — orient with the knowledge base
  - research_topic — search + read + synthesize workflow
  - compare_articles — fetch and compare two articles
  - knowledge_gaps — identify gaps in coverage
"""

from __future__ import annotations

# When run as `python -m wikimind.mcp.server`, this module is __main__.
# Side-effect imports at the bottom (tools_analysis, resources, prompts) do
# `from wikimind.mcp.server import mcp` — without this alias they'd create
# a second module instance with its own mcp. Must be set before any of
# those imports execute.
import sys

if __name__ == "__main__":
    sys.modules.setdefault("wikimind.mcp.server", sys.modules[__name__])

import argparse
import contextlib
import json
from typing import TYPE_CHECKING, Any

import structlog
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from wikimind.config import get_settings
from wikimind.database import get_session_factory, init_db
from wikimind.models import QueryRequest
from wikimind.services.query import QueryService
from wikimind.services.wiki import WikiService

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

log = structlog.get_logger()

# Valid enum values for input validation
_VALID_PAGE_TYPES = {"source", "concept", "synthesis", "answer"}
_VALID_INGEST_STATUSES = {"pending", "processing", "compiled", "failed"}
_VALID_SYNTHESIS_TYPES = {"comparative", "chronological", "thematic", "gap_analysis"}


@contextlib.asynccontextmanager
async def _lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    """Initialize database on MCP server startup."""
    settings = get_settings()
    settings.ensure_dirs()
    await init_db()
    log.info("WikiMind MCP server started")
    yield {}


mcp = FastMCP(
    name="wikimind",
    instructions=(
        "WikiMind is your personal knowledge base. Start with wiki_overview() to see "
        "what's in it. Browse with wiki_list_articles() or wiki_list_concepts(). "
        "Search with wiki_search(). Read articles with wiki_get_article(). For deep "
        "analysis, use wiki_synthesize(). To add knowledge, use wiki_ingest_url() "
        "or wiki_ingest_text(). Check ingestion progress with wiki_get_source_status()."
    ),
    lifespan=_lifespan,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_mcp_user_id() -> str:
    """Return the user ID for MCP operations.

    In dev mode, uses the auto-provisioned dev user.
    In production, this should be overridden by auth context.
    """
    settings = get_settings()
    if not settings.is_dev:
        msg = "Authentication required (production mode)"
        raise ToolError(msg)
    from wikimind.database import get_dev_user_id  # noqa: PLC0415

    return await get_dev_user_id()


@contextlib.asynccontextmanager
async def _get_session():
    """Yield an async database session for MCP tool handlers.

    Read-only tools should NOT commit. Write tools commit explicitly.
    """
    factory = get_session_factory()
    async with factory() as session:
        yield session


# ---------------------------------------------------------------------------
# Tier 2 — Read/Search tools
# ---------------------------------------------------------------------------


@mcp.tool(
    name="wiki_search",
    description=(
        "Search wiki articles by keyword. Returns article titles, "
        "summaries, and IDs ranked by relevance. Use this to find "
        "articles on a topic before reading the full content."
    ),
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
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


@mcp.tool(
    name="wiki_get_article",
    description=(
        "Retrieve the full content of a wiki article by its ID or slug. "
        "Returns the article title, markdown content, sources, and metadata. "
        "Use wiki_search first to find the article ID."
    ),
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
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


@mcp.tool(
    name="wiki_ask",
    description=(
        "Ask a question against the WikiMind knowledge base. "
        "The Q&A agent searches relevant articles and synthesizes "
        "an answer with citations. Use this for complex questions "
        "that span multiple articles."
    ),
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
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
# Tier 1 — Discovery tools (registered from tools_discovery module)
# ---------------------------------------------------------------------------


@mcp.tool(
    name="wiki_overview",
    description=(
        "Get a high-level overview of the knowledge base. Returns article counts, "
        "concept taxonomy, recent articles, and page type breakdown. "
        "Call this first to understand what's in the wiki."
    ),
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
)
async def _tool_wiki_overview(ctx: Context) -> dict[str, Any]:
    """Delegate to discovery module."""
    from wikimind.mcp.tools_discovery import wiki_overview  # noqa: PLC0415

    return await wiki_overview(ctx)


@mcp.tool(
    name="wiki_list_articles",
    description=(
        "List wiki articles with optional filtering by concept or page type. "
        "Supports pagination. Use to browse the knowledge base contents."
    ),
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
)
async def _tool_wiki_list_articles(
    ctx: Context,
    concept: str | None = Field(None, description="Optional concept name to filter by"),
    page_type: str | None = Field(None, description="Optional page type: source, concept, synthesis, or answer"),
    limit: int = Field(20, description="Maximum results (default 20, max 100)"),
    offset: int = Field(0, description="Pagination offset (>= 0)"),
) -> dict[str, Any]:
    """Delegate to discovery module."""
    from wikimind.mcp.tools_discovery import wiki_list_articles  # noqa: PLC0415

    return await wiki_list_articles(ctx, concept=concept, page_type=page_type, limit=limit, offset=offset)


@mcp.tool(
    name="wiki_list_concepts",
    description=(
        "List concept taxonomy with article counts. Shows how the knowledge base is organized into topic areas."
    ),
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
)
async def _tool_wiki_list_concepts(
    ctx: Context,
    include_empty: bool = Field(False, description="Include concepts with zero articles"),
) -> dict[str, Any]:
    """Delegate to discovery module."""
    from wikimind.mcp.tools_discovery import wiki_list_concepts  # noqa: PLC0415

    return await wiki_list_concepts(ctx, include_empty=include_empty)


# ---------------------------------------------------------------------------
# Tier 3 — Write tools (registered from tools_write module)
# ---------------------------------------------------------------------------


@mcp.tool(
    name="wiki_ingest_url",
    description=(
        "Ingest a web page or PDF into the wiki. Returns immediately with a "
        "source_id. Use wiki_get_source_status to check progress. "
        "Only http:// and https:// URLs are allowed."
    ),
    annotations={"readOnlyHint": False, "idempotentHint": False, "openWorldHint": True},
)
async def _tool_wiki_ingest_url(
    url: str = Field(..., description="URL to ingest (http/https only)"),
    title: str = Field("", description="Optional title override (max 200 chars)"),
) -> dict[str, Any]:
    """Ingest a URL into the wiki."""
    from wikimind.mcp.tools_write import wiki_ingest_url  # noqa: PLC0415

    user_id = await _get_mcp_user_id()
    return await wiki_ingest_url(url=url, title=title, user_id=user_id)


@mcp.tool(
    name="wiki_ingest_text",
    description=(
        "Ingest raw text content into the wiki. Returns immediately with a "
        "source_id. Use wiki_get_source_status to check progress."
    ),
    annotations={"readOnlyHint": False, "idempotentHint": False, "openWorldHint": True},
)
async def _tool_wiki_ingest_text(
    text: str = Field(..., description="Text content to ingest (1-100000 chars)"),
    title: str = Field(..., description="Title for the source (1-200 chars, required)"),
) -> dict[str, Any]:
    """Ingest raw text into the wiki."""
    from wikimind.mcp.tools_write import wiki_ingest_text  # noqa: PLC0415

    user_id = await _get_mcp_user_id()
    return await wiki_ingest_text(text=text, title=title, user_id=user_id)


@mcp.tool(
    name="wiki_get_source_status",
    description=(
        "Check the ingestion status of a source. Use the source_id returned by wiki_ingest_url or wiki_ingest_text."
    ),
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
)
async def _tool_wiki_get_source_status(
    source_id: str = Field(..., description="Source ID to check"),
) -> dict[str, Any]:
    """Check ingestion progress."""
    from wikimind.mcp.tools_write import wiki_get_source_status  # noqa: PLC0415

    user_id = await _get_mcp_user_id()
    return await wiki_get_source_status(source_id=source_id, user_id=user_id)


# ---------------------------------------------------------------------------
# Tier 4 — Analysis tools, resources, prompts (self-registering modules)
# ---------------------------------------------------------------------------

# These modules import `mcp` from this file and register their own tools,
# resources, and prompts via decorators. We import them here to trigger
# registration at module load time.
import wikimind.mcp.prompts as _prompts_module  # noqa: E402, F401 — side-effect registration
import wikimind.mcp.resources as _resources_module  # noqa: E402, F401 — side-effect registration
import wikimind.mcp.tools_analysis as _analysis_module  # noqa: E402, F401 — side-effect registration

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_server() -> None:
    """Run the WikiMind MCP server.

    Supports stdio (default) and HTTP transports via --transport flag.
    HTTP transport enables JWT authentication.
    """
    parser = argparse.ArgumentParser(description="WikiMind MCP Server")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9100)
    args = parser.parse_args()

    if args.transport == "http":
        from wikimind.mcp.auth import WikiMindJWTAuthProvider  # noqa: PLC0415

        settings = get_settings()
        if settings.mcp.require_auth:
            auth_provider = WikiMindJWTAuthProvider(secret=settings.auth.jwt_secret_key)
            mcp.run(transport="http", host=args.host, port=args.port, auth=auth_provider)
        else:
            mcp.run(transport="http", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    run_server()
