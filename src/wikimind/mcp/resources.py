"""MCP resources for the WikiMind server.

Resources:
  - wikimind://index: static, flat article list (capped at 500)
  - wikimind://articles/{slug}: template, markdown content
  - wikimind://sources/{source_id}: template, JSON metadata
"""

from __future__ import annotations

import json

import structlog

from wikimind.mcp.server import _get_mcp_user_id, _get_session, mcp

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Resource: wikimind://index
# ---------------------------------------------------------------------------


@mcp.resource(
    "wikimind://index",
    name="wiki_index",
    description="Table of contents — all articles with slugs, titles, and concepts",
    mime_type="application/json",
)
async def resource_index() -> str:
    """Return a flat article index (capped at 500 articles)."""
    user_id = await _get_mcp_user_id()
    async with _get_session() as session:
        from wikimind.services.wiki import WikiService  # noqa: PLC0415

        wiki_svc = WikiService()
        articles = await wiki_svc.list_articles(
            session=session,
            user_id=user_id,
            limit=500,
            offset=0,
        )
        data = {
            "articles": [
                {
                    "slug": a.slug,
                    "title": a.title,
                    "page_type": a.page_type,
                    "concepts": a.concepts,
                }
                for a in articles
            ]
        }
        return json.dumps(data, default=str)


# ---------------------------------------------------------------------------
# Resource: wikimind://articles/{slug}
# ---------------------------------------------------------------------------


@mcp.resource(
    "wikimind://articles/{slug}",
    name="article",
    description="Full article content as markdown",
    mime_type="text/markdown",
)
async def resource_article(slug: str) -> str:
    """Return article content as markdown."""
    user_id = await _get_mcp_user_id()
    async with _get_session() as session:
        from wikimind.services.wiki import WikiService  # noqa: PLC0415

        wiki_svc = WikiService()
        article = await wiki_svc.get_article(
            id_or_slug=slug,
            session=session,
            user_id=user_id,
        )
        return article.content or ""


# ---------------------------------------------------------------------------
# Resource: wikimind://sources/{source_id}
# ---------------------------------------------------------------------------


@mcp.resource(
    "wikimind://sources/{source_id}",
    name="source",
    description="Source ingestion metadata",
    mime_type="application/json",
)
async def resource_source(source_id: str) -> str:
    """Return source metadata as JSON."""
    user_id = await _get_mcp_user_id()
    async with _get_session() as session:
        from wikimind.services.ingest import IngestService  # noqa: PLC0415

        ingest_svc = IngestService()
        source = await ingest_svc.get_source(
            source_id=source_id,
            session=session,
            user_id=user_id,
        )
        return json.dumps(
            {
                "id": source.id,
                "title": source.title,
                "source_type": source.source_type,
                "status": source.status,
                "url": source.source_url,
                "ingested_at": str(source.ingested_at) if source.ingested_at else None,
            },
            default=str,
        )
