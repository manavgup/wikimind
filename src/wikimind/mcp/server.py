"""WikiMind MCP server — tools and prompts over stdio transport.

Exposes tools to MCP clients (Claude Desktop, Cursor, etc.):
  - wiki_search:              full-text search across wiki articles
  - wiki_get_article:         retrieve a full article by ID or slug
  - wiki_ask:                 ask a question against the wiki (Q&A agent)
  - wiki_list_sources:        list ingested sources
  - wiki_synthesize:          cross-cutting synthesis across selected articles
  - wiki_list_contradictions: list contradictions between wiki articles
  - wiki_get_health:          get wiki health report
  - wiki_get_graph:           get the knowledge graph

Prompts:
  - compare_articles:  compare two wiki articles
  - knowledge_gaps:    identify knowledge gaps in the wiki
  - fact_check:        check a claim against wiki evidence

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
from wikimind.engine.synthesis_compiler import SynthesisCompiler
from wikimind.models import ContradictionStatus, QueryRequest
from wikimind.services.contradiction import ContradictionService
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
        "ask questions, browse ingested sources, synthesize "
        "cross-cutting analyses, review contradictions, check "
        "wiki health, and explore the knowledge graph."
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
# Tool: wiki_synthesize
# ---------------------------------------------------------------------------


VALID_SYNTHESIS_TYPES = {"comparative", "chronological", "thematic", "gap_analysis"}


@mcp.tool(
    name="wiki_synthesize",
    description=(
        "Trigger cross-cutting synthesis across selected wiki articles. "
        "This is WikiMind's killer feature: it compares, contrasts, and "
        "finds patterns across multiple sources to produce a new synthesis "
        "page. Provide article IDs to synthesize, and optionally specify "
        "a synthesis type and guidance."
    ),
)
async def wiki_synthesize(
    article_ids: list[str] = Field(..., description="List of article UUIDs to synthesize (minimum 2)"),
    synthesis_type: str | None = Field(
        None,
        description=(
            "Type of synthesis: comparative, chronological, thematic, or gap_analysis. Omit for general synthesis."
        ),
    ),
    guidance: str | None = Field(
        None,
        description="Optional guidance or focus question for the synthesis",
    ),
) -> str:
    """Synthesize a cross-cutting analysis across multiple articles."""
    if len(article_ids) < 2:
        return json.dumps({"error": "At least 2 article IDs are required for synthesis"})

    if synthesis_type and synthesis_type not in VALID_SYNTHESIS_TYPES:
        return json.dumps({"error": f"Invalid synthesis_type. Must be one of: {sorted(VALID_SYNTHESIS_TYPES)}"})

    query_parts: list[str] = []
    if synthesis_type:
        query_parts.append(f"{synthesis_type} analysis")
    if guidance:
        query_parts.append(guidance)
    query = " — ".join(query_parts) if query_parts else "Cross-cutting synthesis"

    user_id = await _get_mcp_user_id()
    compiler = SynthesisCompiler(user_id=user_id)

    async with _get_session() as session:
        try:
            result = await compiler.synthesize(
                query=query,
                session=session,
                article_ids=article_ids,
            )
        except Exception as exc:
            log.warning("wiki_synthesize failed", error=str(exc))
            return json.dumps({"error": f"Synthesis failed: {exc}"})

    if result is None:
        return json.dumps(
            {
                "error": "Synthesis could not be performed. Ensure the article IDs are valid "
                "and at least 2 articles exist."
            }
        )

    article, compilation = result
    return json.dumps(
        {
            "article_id": article.id,
            "slug": article.slug,
            "title": compilation.title,
            "summary": compilation.summary,
            "themes": compilation.themes,
            "gaps": compilation.gaps,
            "open_questions": compilation.open_questions,
            "source_article_count": len(compilation.source_article_ids),
            "content": compilation.article_body,
        },
        default=str,
    )


# ---------------------------------------------------------------------------
# Tool: wiki_list_contradictions
# ---------------------------------------------------------------------------


@mcp.tool(
    name="wiki_list_contradictions",
    description=(
        "List contradictions detected between wiki articles. "
        "Contradictions are conflicting claims found by the linter "
        "across different articles. Filter by status to see active, "
        "resolved, or dismissed contradictions."
    ),
)
async def wiki_list_contradictions(
    status: str | None = Field(
        None,
        description="Filter by status: 'active', 'resolved', or 'dismissed'. Omit for all.",
    ),
    limit: int = Field(50, description="Maximum results to return (max 100)"),
) -> str:
    """List contradictions between wiki articles."""
    limit = min(max(1, limit), 100)

    parsed_status: ContradictionStatus | None = None
    if status:
        try:
            parsed_status = ContradictionStatus(status)
        except ValueError:
            valid = [s.value for s in ContradictionStatus]
            return json.dumps({"error": f"Invalid status. Must be one of: {valid}"})

    contradiction_service = ContradictionService()
    async with _get_session() as session:
        try:
            results = await contradiction_service.list_contradictions(
                session=session,
                user_id=await _get_mcp_user_id(),
                status=parsed_status,
                limit=limit,
            )
        except Exception as exc:
            log.warning("wiki_list_contradictions failed", error=str(exc))
            return json.dumps({"error": f"Failed to list contradictions: {exc}"})

    return json.dumps(
        [
            {
                "id": c.id,
                "claim_a": c.claim_a,
                "claim_b": c.claim_b,
                "article_a_id": c.article_a_id,
                "article_b_id": c.article_b_id,
                "article_a_title": c.article_a_title,
                "article_b_title": c.article_b_title,
                "status": c.status,
                "detected_at": c.detected_at,
                "resolution": c.resolution,
            }
            for c in results
        ],
        default=str,
    )


# ---------------------------------------------------------------------------
# Tool: wiki_get_health
# ---------------------------------------------------------------------------


@mcp.tool(
    name="wiki_get_health",
    description=(
        "Get a wiki health report including orphan articles, stale articles, "
        "linter findings, and contradiction counts. Use this to understand "
        "the overall state and quality of the knowledge base."
    ),
)
async def wiki_get_health() -> str:
    """Get the wiki health report."""
    wiki_service = WikiService()
    async with _get_session() as session:
        try:
            report = await wiki_service.get_health(
                session=session,
                user_id=await _get_mcp_user_id(),
            )
        except Exception as exc:
            log.warning("wiki_get_health failed", error=str(exc))
            return json.dumps({"error": f"Failed to get health report: {exc}"})

    return json.dumps(
        {
            "generated_at": report.generated_at,
            "total_articles": report.total_articles,
            "total_sources": report.total_sources,
            "total_findings": report.total_findings,
            "contradictions_count": report.contradictions_count,
            "orphans_count": report.orphans_count,
            "status": report.status,
            "message": report.message,
        },
        default=str,
    )


# ---------------------------------------------------------------------------
# Tool: wiki_get_graph
# ---------------------------------------------------------------------------


@mcp.tool(
    name="wiki_get_graph",
    description=(
        "Get the knowledge graph showing all articles and their "
        "relationships (references, contradictions, synthesis links). "
        "Optionally filter to relationships involving a specific article. "
        "Returns nodes (articles) and edges (relationships)."
    ),
)
async def wiki_get_graph(
    article_slug: str | None = Field(
        None,
        description=(
            "Optional article slug or ID to filter edges. When set, only edges involving this article are returned."
        ),
    ),
) -> str:
    """Get the knowledge graph with optional article filter."""
    wiki_service = WikiService()
    async with _get_session() as session:
        try:
            graph = await wiki_service.get_graph(
                session=session,
                user_id=await _get_mcp_user_id(),
                from_article=article_slug,
            )
        except Exception as exc:
            log.warning("wiki_get_graph failed", error=str(exc))
            return json.dumps({"error": f"Failed to get graph: {exc}"})

    return json.dumps(
        {
            "node_count": len(graph.nodes),
            "edge_count": len(graph.edges),
            "nodes": [
                {
                    "id": n.id,
                    "label": n.label,
                    "concept_cluster": n.concept_cluster,
                    "connection_count": n.connection_count,
                    "confidence": n.confidence,
                    "effective_confidence": n.effective_confidence,
                }
                for n in graph.nodes
            ],
            "edges": [
                {
                    "source": e.source,
                    "target": e.target,
                    "relation_type": e.relation_type,
                    "context": e.context,
                }
                for e in graph.edges
            ],
        },
        default=str,
    )


# ---------------------------------------------------------------------------
# Prompt: compare_articles
# ---------------------------------------------------------------------------


@mcp.prompt(
    name="compare_articles",
    description=(
        "Compare two wiki articles side-by-side. Fetches both articles "
        "and builds a prompt identifying key agreements, disagreements, "
        "and synthesis opportunities."
    ),
)
async def compare_articles(
    slug_a: str = Field(..., description="Slug or ID of the first article"),
    slug_b: str = Field(..., description="Slug or ID of the second article"),
) -> str:
    """Build a comparison prompt for two wiki articles."""
    wiki_service = WikiService()
    async with _get_session() as session:
        user_id = await _get_mcp_user_id()
        try:
            article_a = await wiki_service.get_article(id_or_slug=slug_a, session=session, user_id=user_id)
            article_b = await wiki_service.get_article(id_or_slug=slug_b, session=session, user_id=user_id)
        except Exception as exc:
            return f"Error fetching articles: {exc}"

    return (
        f"Compare these two WikiMind articles and identify:\n"
        f"1. Key agreements — where do they align?\n"
        f"2. Key disagreements — where do they conflict?\n"
        f"3. Synthesis opportunities — what new insights emerge from combining them?\n"
        f"4. Knowledge gaps — what is missing from both?\n\n"
        f"---\n\n"
        f"## Article A: {article_a.title}\n\n"
        f"{article_a.content}\n\n"
        f"---\n\n"
        f"## Article B: {article_b.title}\n\n"
        f"{article_b.content}\n"
    )


# ---------------------------------------------------------------------------
# Prompt: knowledge_gaps
# ---------------------------------------------------------------------------


@mcp.prompt(
    name="knowledge_gaps",
    description=(
        "Identify knowledge gaps in the wiki. Optionally focus on a specific "
        "topic. Combines search results and health data to surface what's "
        "missing, stale, or contradictory."
    ),
)
async def knowledge_gaps(
    topic: str | None = Field(
        None,
        description="Optional topic to focus the gap analysis on. Omit for general wiki health.",
    ),
) -> str:
    """Build a knowledge-gap analysis prompt."""
    wiki_service = WikiService()
    user_id = await _get_mcp_user_id()

    async with _get_session() as session:
        try:
            health = await wiki_service.get_health(session=session, user_id=user_id)
        except Exception:
            health = None

        search_results = []
        if topic:
            with contextlib.suppress(Exception):
                search_results = await wiki_service.search(q=topic, session=session, user_id=user_id, limit=10)

    parts: list[str] = ["Analyze the WikiMind knowledge base and identify knowledge gaps.\n"]

    if topic:
        parts.append(f"Focus area: {topic}\n")

    if health:
        parts.append("## Wiki Health Summary\n")
        parts.append(f"- Total articles: {health.total_articles}")
        parts.append(f"- Total sources: {health.total_sources}")
        if health.total_findings is not None:
            parts.append(f"- Linter findings: {health.total_findings}")
        if health.contradictions_count is not None:
            parts.append(f"- Contradictions: {health.contradictions_count}")
        if health.orphans_count is not None:
            parts.append(f"- Orphan articles: {health.orphans_count}")
        if health.message:
            parts.append(f"- Status: {health.message}")
        parts.append("")

    if search_results:
        parts.append(f"## Articles matching '{topic}'\n")
        parts.extend(
            f"- **{r.title}** (confidence: {r.confidence}): {r.summary or 'No summary'}" for r in search_results
        )
        parts.append("")

    parts.append(
        "\nBased on the above, identify:\n"
        "1. What topics are missing or under-covered?\n"
        "2. Which articles are stale and need updating?\n"
        "3. What contradictions need resolution?\n"
        "4. What connections between topics are missing?\n"
        "5. Recommend specific actions to improve wiki coverage."
    )

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Prompt: fact_check
# ---------------------------------------------------------------------------


@mcp.prompt(
    name="fact_check",
    description=(
        "Fact-check a claim against the WikiMind knowledge base. "
        "Searches the wiki for relevant evidence and builds a prompt "
        "asking to evaluate the claim with supporting and contradicting "
        "article excerpts."
    ),
)
async def fact_check(
    claim: str = Field(..., description="The claim to fact-check against the wiki"),
) -> str:
    """Build a fact-checking prompt with wiki evidence."""
    wiki_service = WikiService()
    user_id = await _get_mcp_user_id()

    async with _get_session() as session:
        try:
            results = await wiki_service.search(q=claim, session=session, user_id=user_id, limit=5)
        except Exception:
            results = []

    if not results:
        return (
            f'Fact-check this claim: "{claim}"\n\n'
            "No relevant articles were found in the WikiMind knowledge base. "
            "The claim cannot be verified or refuted with available evidence."
        )

    parts: list[str] = [
        f"Fact-check this claim against the WikiMind knowledge base:\n\n"
        f'**Claim:** "{claim}"\n\n'
        f"## Relevant Wiki Articles\n"
    ]

    for r in results:
        parts.append(f"### {r.title}")
        parts.append(f"- Confidence: {r.confidence}")
        parts.append(f"- Summary: {r.summary or 'No summary'}")
        if r.source_count:
            parts.append(f"- Based on {r.source_count} source(s)")
        parts.append("")

    parts.append(
        "\nBased on the evidence above, evaluate the claim:\n"
        "1. **Supported:** What evidence supports the claim?\n"
        "2. **Contradicted:** What evidence contradicts the claim?\n"
        "3. **Verdict:** Is the claim supported, contradicted, partially true, "
        "or unverifiable based on available evidence?\n"
        "4. **Confidence:** How confident is this assessment given the quality "
        "and breadth of the evidence?"
    )

    return "\n".join(parts)


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
