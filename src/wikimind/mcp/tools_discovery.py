"""Discovery tools (Tier 1) for WikiMind MCP server.

Provides high-level browsing of the knowledge base:
  - wiki_overview: article/concept counts + recent articles
  - wiki_list_articles: paginated article listing with filters
  - wiki_list_concepts: concept taxonomy with article counts

Each function is a standalone async callable. The integration task will
wire these into the FastMCP server via @mcp.tool() decorators.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

import structlog
from fastmcp.exceptions import ToolError

from wikimind.database import get_session_factory

if TYPE_CHECKING:
    from fastmcp import Context

log = structlog.get_logger()

# Valid enum values for input validation
_VALID_PAGE_TYPES = {"source", "concept", "synthesis", "answer"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_mcp_user_id() -> str:
    """Return the user ID for MCP operations.

    In dev mode, uses the auto-provisioned dev user.
    In production, this should be overridden by auth context.
    """
    from wikimind.config import get_settings  # noqa: PLC0415

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
# Tool: wiki_overview
# ---------------------------------------------------------------------------


async def wiki_overview(ctx: Context) -> dict[str, Any]:
    """Get a high-level overview of the knowledge base.

    Returns article counts, concept taxonomy, recent articles, and
    page type breakdown. Call this first to understand what's in the wiki.

    Annotations: readOnlyHint=True, idempotentHint=True, openWorldHint=False
    """
    try:
        user_id = await _get_mcp_user_id()
        async with _get_session() as session:
            from wikimind.services.admin import AdminService  # noqa: PLC0415
            from wikimind.services.wiki import WikiService  # noqa: PLC0415

            wiki_svc = WikiService()
            admin_svc = AdminService()

            stats = await admin_svc.get_stats(session)
            concepts = await wiki_svc.get_concepts(session, user_id, include_empty=False)
            articles = await wiki_svc.list_articles(session, user_id, limit=5, offset=0)

            await ctx.log(
                f"Wiki has {stats.article_count} articles across {len(concepts)} concepts",
                level="info",
            )

            return {
                "article_count": stats.article_count,
                "source_count": stats.source_count,
                "concept_count": len(concepts),
                "concepts": [{"name": c.name, "article_count": c.article_count} for c in concepts[:20]],
                "recent_articles": [
                    {
                        "slug": a.slug,
                        "title": a.title,
                        "summary": a.summary,
                        "updated_at": str(a.updated_at),
                    }
                    for a in articles[:5]
                ],
                "page_type_breakdown": stats.articles_by_page_type,
            }
    except ToolError:
        raise
    except Exception as exc:
        log.error("wiki_overview failed", error=str(exc))
        msg = f"Failed to get wiki overview: {exc}"
        raise ToolError(msg) from exc


# ---------------------------------------------------------------------------
# Tool: wiki_list_articles
# ---------------------------------------------------------------------------


async def wiki_list_articles(
    ctx: Context,
    concept: str | None = None,
    page_type: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """List wiki articles with optional filtering and pagination.

    Args:
        ctx: MCP context for logging.
        concept: Optional concept name to filter by.
        page_type: Optional page type filter (source, concept, synthesis, answer).
        limit: Maximum results (default 20, max 100).
        offset: Pagination offset (>= 0).

    Returns:
        Dict with articles list and pagination metadata.

    Annotations: readOnlyHint=True, idempotentHint=True, openWorldHint=False
    """
    try:
        # Input validation
        if page_type is not None and page_type not in _VALID_PAGE_TYPES:
            msg = f"Invalid page_type '{page_type}'. Must be one of: {', '.join(sorted(_VALID_PAGE_TYPES))}"
            raise ToolError(msg)
        if offset < 0:
            msg = "offset must be >= 0"
            raise ToolError(msg)

        # Clamp limit to 1-100 range
        clamped = False
        original_limit = limit
        limit = max(1, min(limit, 100))
        if limit != original_limit:
            clamped = True

        user_id = await _get_mcp_user_id()
        async with _get_session() as session:
            from wikimind.services.wiki import WikiService  # noqa: PLC0415

            wiki_svc = WikiService()
            articles = await wiki_svc.list_articles(
                session,
                user_id,
                concept=concept,
                page_type=page_type,
                limit=limit,
                offset=offset,
            )

            await ctx.log(f"Listed {len(articles)} articles (offset={offset})", level="info")

            result: dict[str, Any] = {
                "articles": [
                    {
                        "slug": a.slug,
                        "title": a.title,
                        "summary": a.summary,
                        "concepts": a.concepts,
                        "page_type": a.page_type,
                        "source_count": a.source_count,
                        "confidence": a.confidence,
                        "updated_at": str(a.updated_at),
                    }
                    for a in articles
                ],
            }
            if clamped:
                result["warning"] = f"limit clamped to {limit} (requested {original_limit}, max 100)"
            return result
    except ToolError:
        raise
    except Exception as exc:
        log.error("wiki_list_articles failed", error=str(exc))
        msg = f"Failed to list articles: {exc}"
        raise ToolError(msg) from exc


# ---------------------------------------------------------------------------
# Tool: wiki_list_concepts
# ---------------------------------------------------------------------------


async def wiki_list_concepts(
    ctx: Context,
    include_empty: bool = False,
) -> dict[str, Any]:
    """List concept taxonomy with article counts.

    Args:
        ctx: MCP context for logging.
        include_empty: If True, include concepts with zero articles (default False).

    Returns:
        Dict with concepts list.

    Annotations: readOnlyHint=True, idempotentHint=True, openWorldHint=False
    """
    try:
        user_id = await _get_mcp_user_id()
        async with _get_session() as session:
            from wikimind.services.wiki import WikiService  # noqa: PLC0415

            wiki_svc = WikiService()
            concepts = await wiki_svc.get_concepts(session, user_id, include_empty=include_empty)

            await ctx.log(f"Found {len(concepts)} concepts", level="info")

            return {
                "concepts": [
                    {
                        "name": c.name,
                        "article_count": c.article_count,
                        "concept_kind": c.concept_kind,
                    }
                    for c in concepts
                ],
            }
    except ToolError:
        raise
    except Exception as exc:
        log.error("wiki_list_concepts failed", error=str(exc))
        msg = f"Failed to list concepts: {exc}"
        raise ToolError(msg) from exc
