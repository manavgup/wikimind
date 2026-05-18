"""Analysis tools (Tier 4) for the WikiMind MCP server.

Tools: wiki_synthesize, wiki_get_health, wiki_list_sources, wiki_get_graph.
These are registered on the FastMCP instance in server.py via decorators.
"""

from __future__ import annotations

import structlog
from fastmcp import Context  # noqa: TC002 — required at runtime for FastMCP function parsing
from fastmcp.exceptions import ToolError
from pydantic import Field
from sqlalchemy import func
from sqlmodel import select

from wikimind.mcp.server import (
    _VALID_INGEST_STATUSES,
    _VALID_SYNTHESIS_TYPES,
    _get_mcp_user_id,
    _get_session,
    mcp,
)
from wikimind.models import Contradiction, ContradictionStatus

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Tool: wiki_synthesize
# ---------------------------------------------------------------------------


@mcp.tool(
    name="wiki_synthesize",
    description=(
        "Synthesize a cross-cutting analysis from 2-10 wiki articles. "
        "Produces a new synthesis page combining insights from the selected articles. "
        "Always runs synchronously with progress reporting."
    ),
    annotations={"readOnlyHint": False, "idempotentHint": False, "openWorldHint": True},
)
async def wiki_synthesize(
    ctx: Context,
    article_ids: list[str] = Field(..., description="List of 2-10 article IDs to synthesize (no duplicates)"),
    synthesis_type: str = Field("thematic", description="Type: comparative, chronological, thematic, or gap_analysis"),
    guidance: str = Field("", description="Optional guidance for the synthesis (max 1000 chars)"),
) -> dict:
    """Create a synthesis page from multiple articles."""
    # Validate article_ids count
    if len(article_ids) < 2:
        msg = "At least 2 article_ids are required for synthesis"
        raise ToolError(msg)
    if len(article_ids) > 10:
        msg = "Maximum 10 article_ids allowed for synthesis"
        raise ToolError(msg)

    # Check for duplicates
    if len(set(article_ids)) != len(article_ids):
        msg = "article_ids must not contain duplicates"
        raise ToolError(msg)

    # Validate synthesis_type
    if synthesis_type not in _VALID_SYNTHESIS_TYPES:
        msg = f"Invalid synthesis_type '{synthesis_type}'. Must be one of: {', '.join(sorted(_VALID_SYNTHESIS_TYPES))}"
        raise ToolError(msg)

    # Validate guidance length
    if guidance and len(guidance) > 1000:
        msg = "guidance must be 1000 characters or fewer"
        raise ToolError(msg)

    try:
        user_id = await _get_mcp_user_id()

        # Build a query from synthesis_type and guidance
        query = f"{synthesis_type} synthesis"
        if guidance:
            query = f"{guidance} ({synthesis_type})"

        async with _get_session() as session:
            from wikimind.engine.synthesis_compiler import SynthesisCompiler  # noqa: PLC0415

            # Report progress: fetching articles
            await ctx.report_progress(1, len(article_ids) + 1)

            compiler = SynthesisCompiler(user_id=user_id)
            result = await compiler.synthesize(
                query=query,
                session=session,
                article_ids=article_ids,
            )

            # Report progress: LLM synthesis complete
            await ctx.report_progress(len(article_ids) + 1, len(article_ids) + 1)

            if result is None:
                msg = "Synthesis failed — could not produce a result. Verify the article IDs exist and contain content."
                raise ToolError(msg)

            article, compilation = result
            await ctx.log(f"Synthesis complete: {article.title}", level="info")

            return {
                "title": article.title,
                "content": compilation.article_body,
                "themes": compilation.themes if hasattr(compilation, "themes") else [],
            }
    except ToolError:
        raise
    except Exception as exc:
        log.error("wiki_synthesize failed", error=str(exc))
        msg = f"Synthesis failed: {exc}"
        raise ToolError(msg) from exc


# ---------------------------------------------------------------------------
# Tool: wiki_get_health
# ---------------------------------------------------------------------------


@mcp.tool(
    name="wiki_get_health",
    description=(
        "Get health metrics for the knowledge base: article counts, orphans, "
        "contradictions, stuck sources, and compilation success rate."
    ),
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
)
async def wiki_get_health(ctx: Context) -> dict:
    """Return knowledge base health metrics."""
    try:
        await _get_mcp_user_id()
        async with _get_session() as session:
            from wikimind.services.admin import AdminService  # noqa: PLC0415

            admin_svc = AdminService()
            stats = await admin_svc.get_stats(session)

            # Count active contradictions
            contradiction_stmt = (
                select(func.count())
                .select_from(Contradiction)
                .where(Contradiction.status == ContradictionStatus.ACTIVE)
            )
            contradiction_result = await session.execute(contradiction_stmt)
            contradiction_count = contradiction_result.scalar() or 0

            await ctx.log(
                f"Health: {stats.article_count} articles, "
                f"{stats.orphan_count} orphans, "
                f"{contradiction_count} contradictions",
                level="info",
            )

            return {
                "article_count": stats.article_count,
                "source_count": stats.source_count,
                "orphan_count": stats.orphan_count,
                "contradiction_count": contradiction_count,
                "stuck_source_count": stats.stuck_sources,
                "compilation_success_rate": stats.compilation_success_rate,
            }
    except ToolError:
        raise
    except Exception as exc:
        log.error("wiki_get_health failed", error=str(exc))
        msg = f"Failed to get health metrics: {exc}"
        raise ToolError(msg) from exc


# ---------------------------------------------------------------------------
# Tool: wiki_list_sources (rewrite)
# ---------------------------------------------------------------------------


@mcp.tool(
    name="wiki_list_sources",
    description=(
        "List ingested sources in the WikiMind knowledge base. "
        "Shows what content has been fed into the wiki (URLs, PDFs, "
        "text, YouTube). Optionally filter by status."
    ),
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
)
async def wiki_list_sources(
    status: str | None = Field(None, description="Optional status filter: pending, processing, compiled, or failed"),
    limit: int = Field(20, description="Maximum number of results (default 20, max 100)"),
) -> list[dict]:
    """List ingested sources with optional status filtering."""
    # Validate status enum
    if status is not None and status not in _VALID_INGEST_STATUSES:
        msg = f"Invalid status '{status}'. Must be one of: {', '.join(sorted(_VALID_INGEST_STATUSES))}"
        raise ToolError(msg)

    limit = min(max(1, limit), 100)

    try:
        user_id = await _get_mcp_user_id()
        async with _get_session() as session:
            from wikimind.services.ingest import IngestService  # noqa: PLC0415

            ingest_service = IngestService()
            sources = await ingest_service.list_sources(
                session=session,
                user_id=user_id,
                status=status,
                limit=limit,
            )

            return [
                {
                    "id": s.id,
                    "title": s.title,
                    "source_type": s.source_type,
                    "status": s.status,
                    "ingested_at": str(s.ingested_at) if s.ingested_at else None,
                }
                for s in sources
            ]
    except ToolError:
        raise
    except Exception as exc:
        log.error("wiki_list_sources failed", error=str(exc))
        msg = f"Failed to list sources: {exc}"
        raise ToolError(msg) from exc


# ---------------------------------------------------------------------------
# Tool: wiki_get_graph
# ---------------------------------------------------------------------------


@mcp.tool(
    name="wiki_get_graph",
    description=(
        "Get the knowledge graph showing relationships between articles. "
        "Returns nodes (articles) and edges (relationships). "
        "Optionally filter to edges involving a specific article."
    ),
    annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False},
)
async def wiki_get_graph(
    article_slug: str | None = Field(None, description="Optional article slug to filter graph edges"),
) -> dict:
    """Return the knowledge graph (nodes and edges)."""
    try:
        user_id = await _get_mcp_user_id()
        async with _get_session() as session:
            from wikimind.services.wiki import WikiService  # noqa: PLC0415

            wiki_svc = WikiService()
            graph = await wiki_svc.get_graph(
                session=session,
                user_id=user_id,
                from_article=article_slug,
            )

            return {
                "nodes": [
                    {
                        "id": n.id,
                        "title": n.label,
                        "type": n.concept_cluster,
                        "confidence": n.confidence,
                    }
                    for n in graph.nodes
                ],
                "edges": [
                    {
                        "source": e.source,
                        "target": e.target,
                        "relation": e.relation_type.value
                        if hasattr(e.relation_type, "value")
                        else str(e.relation_type),
                    }
                    for e in graph.edges
                ],
            }
    except ToolError:
        raise
    except Exception as exc:
        log.error("wiki_get_graph failed", error=str(exc))
        msg = f"Failed to get graph: {exc}"
        raise ToolError(msg) from exc
