"""WikiMind MCP server — tools, resources, and prompts over stdio transport.

Exposes four tools to MCP clients (Claude Desktop, Cursor, etc.):
  - wiki_search:       full-text search across wiki articles
  - wiki_get_article:  retrieve a full article by ID or slug
  - wiki_ask:          ask a question against the wiki (Q&A agent)
  - wiki_list_sources: list ingested sources

Resources (browseable URIs):
  - wikimind://articles/{slug}:  individual article content
  - wikimind://sources/{id}:     source metadata

Prompts (pre-built templates):
  - research_topic(topic):       search wiki + synthesize findings
  - summarize_article(slug):     get article + create summary

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
        "ask questions, and browse ingested sources."
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
# Resource: wikimind://articles/{slug}
# ---------------------------------------------------------------------------


@mcp.resource(
    "wikimind://articles/{slug}",
    name="article",
    description="Read a wiki article by slug. Returns the full markdown content.",
    mime_type="text/markdown",
)
async def resource_article(slug: str) -> str:
    """Return article content as a browseable MCP resource."""
    wiki_service = WikiService()
    async with _get_session() as session:
        try:
            article = await wiki_service.get_article(
                id_or_slug=slug,
                session=session,
                user_id=await _get_mcp_user_id(),
            )
        except Exception as exc:
            return f"Error: {exc}"

    header = f"# {article.title}\n\n"
    summary = f"**Summary:** {article.summary}\n\n" if article.summary else ""
    content = article.content or ""
    return f"{header}{summary}{content}"


# ---------------------------------------------------------------------------
# Resource: wikimind://sources/{id}
# ---------------------------------------------------------------------------


@mcp.resource(
    "wikimind://sources/{source_id}",
    name="source",
    description="Read source metadata by ID. Returns ingestion details as JSON.",
    mime_type="application/json",
)
async def resource_source(source_id: str) -> str:
    """Return source metadata as a browseable MCP resource."""
    ingest_service = IngestService()
    async with _get_session() as session:
        try:
            source = await ingest_service.get_source(
                source_id=source_id,
                session=session,
                user_id=await _get_mcp_user_id(),
            )
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    return json.dumps(
        {
            "id": source.id,
            "source_type": source.source_type,
            "title": source.title,
            "source_url": source.source_url,
            "author": source.author,
            "status": source.status,
            "ingested_at": source.ingested_at,
            "compiled_at": source.compiled_at,
            "token_count": source.token_count,
        },
        default=str,
    )


# ---------------------------------------------------------------------------
# Prompt: research_topic
# ---------------------------------------------------------------------------


@mcp.prompt(
    name="research_topic",
    description=(
        "Research a topic using the WikiMind knowledge base. "
        "Searches for relevant articles and synthesizes findings "
        "into a comprehensive overview."
    ),
)
async def prompt_research_topic(topic: str) -> str:
    """Generate a research prompt that searches the wiki and synthesizes findings."""
    wiki_service = WikiService()
    async with _get_session() as session:
        results = await wiki_service.search(
            q=topic,
            session=session,
            user_id=await _get_mcp_user_id(),
            limit=5,
        )

    if not results:
        return (
            f"I want to research the topic: {topic}\n\n"
            "No existing articles were found in the WikiMind knowledge base. "
            "Please provide a general overview of this topic and suggest "
            "sources that could be ingested to build knowledge on it."
        )

    articles_section = "\n".join(f"- **{r.title}** (slug: {r.slug}): {r.summary or 'No summary'}" for r in results)
    return (
        f"I want to research the topic: {topic}\n\n"
        f"The following relevant articles exist in my WikiMind knowledge base:\n"
        f"{articles_section}\n\n"
        f"Please synthesize the key findings from these articles into a "
        f"comprehensive overview of '{topic}'. Highlight connections between "
        f"articles, identify gaps in coverage, and suggest follow-up questions."
    )


# ---------------------------------------------------------------------------
# Prompt: summarize_article
# ---------------------------------------------------------------------------


@mcp.prompt(
    name="summarize_article",
    description=(
        "Summarize a specific wiki article. Retrieves the article "
        "by slug and creates a structured summary with key points."
    ),
)
async def prompt_summarize_article(slug: str) -> str:
    """Generate a summary prompt for a specific wiki article."""
    wiki_service = WikiService()
    async with _get_session() as session:
        try:
            article = await wiki_service.get_article(
                id_or_slug=slug,
                session=session,
                user_id=await _get_mcp_user_id(),
            )
        except Exception:
            return (
                f"Article with slug '{slug}' was not found in the knowledge base. "
                "Please use wiki_search to find available articles first."
            )

    content = article.content or "No content available."
    sources_info = ""
    if article.sources:
        sources_list = "\n".join(
            f"- {s.title or s.source_url or 'Unknown source'} ({s.source_type})" for s in article.sources
        )
        sources_info = f"\n\nSources used:\n{sources_list}"

    return (
        f"Please summarize the following wiki article.\n\n"
        f"**Title:** {article.title}\n"
        f"**Confidence:** {article.confidence}\n"
        f"**Type:** {article.page_type}\n"
        f"{sources_info}\n\n"
        f"---\n\n"
        f"{content}\n\n"
        f"---\n\n"
        f"Provide a structured summary with:\n"
        f"1. Key points (3-5 bullet points)\n"
        f"2. Main conclusions or takeaways\n"
        f"3. Any caveats or limitations noted in the article"
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
