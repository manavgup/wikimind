"""Write tools (Tier 3) for the WikiMind MCP server.

Standalone async functions that implement wiki_ingest_url, wiki_ingest_text,
and wiki_get_source_status. These are NOT decorated with @mcp.tool yet —
they will be registered in server.py in a later task.

Design decisions (from spec):
- Return source_id only, NOT job_id (job_id has a race condition)
- wiki_get_source_status polls Source.status field directly
- URL validation: only http/https (SSRF protection)
- Title override: update source.title after ingest if provided
- Dedup: if source already exists, return {status: "already_exists"}
- Text validation: 1-100000 chars, title 1-200 chars
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

import structlog
from fastmcp.exceptions import ToolError
from sqlmodel import select

from wikimind.database import get_session_factory
from wikimind.errors import IngestError, NotFoundError
from wikimind.models import ArticleSource, IngestStatus
from wikimind.services.factories import get_ingest_service

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlmodel.ext.asyncio.session import AsyncSession

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Session helper (mirrors server.py pattern for write operations)
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def _get_session() -> AsyncIterator[AsyncSession]:
    """Yield an async database session for write tool handlers."""
    factory = get_session_factory()
    async with factory() as session:
        yield session


# ---------------------------------------------------------------------------
# wiki_ingest_url
# ---------------------------------------------------------------------------


async def wiki_ingest_url(url: str, title: str, user_id: str) -> dict[str, Any]:
    """Ingest a web page or PDF into the wiki.

    Returns immediately with a source_id. Use wiki_get_source_status to check
    progress.

    Args:
        url: URL to ingest (http/https only).
        title: Optional title override (max 200 chars). Pass empty string for none.
        user_id: The authenticated user's ID.

    Returns:
        Dict with source_id and status. Status is "queued" for new sources,
        "already_exists" for duplicates (with article_slug if available).

    Raises:
        ToolError: On invalid input or ingestion failure.
    """
    # Validate URL scheme (SSRF protection)
    if not url.startswith(("http://", "https://")):
        msg = "Only http:// and https:// URLs are allowed"
        raise ToolError(msg)

    # Validate title length
    if title and len(title) > 200:
        msg = "Title must be 200 characters or fewer"
        raise ToolError(msg)

    try:
        ingest_svc = get_ingest_service()
        async with _get_session() as session:
            # Disable auto_compile so we can apply title override before compilation
            source = await ingest_svc.ingest_url(
                url,
                session,
                user_id=user_id,
                auto_compile=False,
            )

            # Detect dedup hit: compiled_at is already set for existing sources
            if source.compiled_at is not None:
                result: dict[str, Any] = {
                    "source_id": source.id,
                    "status": "already_exists",
                }
                # Find linked article slug if available
                article_slug = await _find_article_slug_for_source(session, source.id)
                if article_slug:
                    result["article_slug"] = article_slug
                return result

            # Apply title override BEFORE committing so the compiler sees it
            if title:
                source.title = title

            await session.commit()

            # Schedule compilation after title is persisted
            await ingest_svc._schedule_compile(source)

            return {"source_id": source.id, "status": "queued"}
    except ToolError:
        raise
    except IngestError as exc:
        msg = f"Ingestion failed: {exc.message}"
        raise ToolError(msg) from exc
    except Exception as exc:
        log.error("wiki_ingest_url failed", url=url, error=str(exc))
        msg = f"Ingestion failed: {exc}"
        raise ToolError(msg) from exc


# ---------------------------------------------------------------------------
# wiki_ingest_text
# ---------------------------------------------------------------------------


async def wiki_ingest_text(text: str, title: str, user_id: str) -> dict[str, Any]:
    """Ingest raw text content into the wiki.

    Returns immediately with a source_id. Use wiki_get_source_status to check
    progress.

    Args:
        text: Text content to ingest (1-100000 chars).
        title: Title for the source (1-200 chars, required).
        user_id: The authenticated user's ID.

    Returns:
        Dict with source_id and status. Status is "queued" for new sources,
        "already_exists" for duplicates (with article_slug if available).

    Raises:
        ToolError: On invalid input or ingestion failure.
    """
    # Validate text length
    if not text or len(text) < 1:
        msg = "Text content must be at least 1 character"
        raise ToolError(msg)
    if len(text) > 100000:
        msg = "Text content must be 100000 characters or fewer"
        raise ToolError(msg)

    # Validate title
    if not title or len(title) < 1:
        msg = "Title is required (1-200 characters)"
        raise ToolError(msg)
    if len(title) > 200:
        msg = "Title must be 200 characters or fewer"
        raise ToolError(msg)

    try:
        ingest_svc = get_ingest_service()
        async with _get_session() as session:
            source = await ingest_svc.ingest_text(text, title, session, user_id=user_id)

            # Detect dedup hit: compiled_at is already set for existing sources
            if source.compiled_at is not None:
                result: dict[str, Any] = {
                    "source_id": source.id,
                    "status": "already_exists",
                }
                article_slug = await _find_article_slug_for_source(session, source.id)
                if article_slug:
                    result["article_slug"] = article_slug
                return result

            await session.commit()

            return {"source_id": source.id, "status": "queued"}
    except ToolError:
        raise
    except IngestError as exc:
        msg = f"Ingestion failed: {exc.message}"
        raise ToolError(msg) from exc
    except Exception as exc:
        log.error("wiki_ingest_text failed", error=str(exc))
        msg = f"Ingestion failed: {exc}"
        raise ToolError(msg) from exc


# ---------------------------------------------------------------------------
# wiki_get_source_status
# ---------------------------------------------------------------------------

# Map IngestStatus enum values to MCP-facing status strings
_STATUS_MAP: dict[IngestStatus, str] = {
    IngestStatus.PENDING: "queued",
    IngestStatus.PROCESSING: "processing",
    IngestStatus.COMPILED: "compiled",
    IngestStatus.FAILED: "failed",
}


async def wiki_get_source_status(source_id: str, user_id: str) -> dict[str, Any]:
    """Check the ingestion status of a source.

    Use the source_id returned by wiki_ingest_url or wiki_ingest_text.

    Args:
        source_id: Source ID to check.
        user_id: The authenticated user's ID.

    Returns:
        Dict with source_id, status, title, and optionally article_slug or error.

    Raises:
        ToolError: If source not found or other failure.
    """
    try:
        ingest_svc = get_ingest_service()
        async with _get_session() as session:
            source = await ingest_svc.get_source(source_id, session, user_id=user_id)

            status = _STATUS_MAP.get(source.status, source.status.value)
            result: dict[str, Any] = {
                "source_id": source.id,
                "status": status,
                "title": source.title,
            }

            # If compiled, include the linked article slug
            if source.status == IngestStatus.COMPILED:
                article_slug = await _find_article_slug_for_source(session, source.id)
                if article_slug:
                    result["article_slug"] = article_slug

            # If failed, include error message
            if source.status == IngestStatus.FAILED and source.error_message:
                result["error"] = source.error_message

            return result
    except NotFoundError as exc:
        msg = f"Source not found: {source_id}"
        raise ToolError(msg) from exc
    except ToolError:
        raise
    except Exception as exc:
        log.error("wiki_get_source_status failed", source_id=source_id, error=str(exc))
        msg = f"Failed to check status: {exc}"
        raise ToolError(msg) from exc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _find_article_slug_for_source(session: AsyncSession, source_id: str) -> str | None:
    """Find the article slug linked to a source via the ArticleSource join table.

    Returns None if no article is linked yet.
    """
    from wikimind.models import Article  # noqa: PLC0415

    stmt = (
        select(Article.slug)
        .join(ArticleSource, onclause=ArticleSource.article_id == Article.id)  # type: ignore[arg-type]
        .where(ArticleSource.source_id == source_id)
        .limit(1)
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    return row
