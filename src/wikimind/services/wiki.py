"""Retrieve wiki articles, build the knowledge graph, and search content.

Centralizes all article retrieval, full-text search, concept taxonomy,
and health report generation so route handlers stay thin. Article and
search responses are enriched with source provenance so callers can
trace each compiled article back to its raw ingested sources.
"""

import json
from pathlib import Path

import structlog
from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.config import get_settings
from wikimind.models import (
    Article,
    ArticleResponse,
    ArticleSourceSummary,
    ArticleSummaryResponse,
    Backlink,
    Concept,
    GraphEdge,
    GraphNode,
    GraphResponse,
    Source,
    SourceResponse,
)

log = structlog.get_logger()


def _read_article_content(file_path: str) -> str:
    """Read article markdown content from disk.

    Args:
        file_path: Absolute path to the article markdown file.

    Returns:
        The file content, or an empty string if the file cannot be read.
    """
    try:
        return Path(file_path).read_text(encoding="utf-8")
    except Exception:
        return ""


def _parse_source_ids(raw: str | None) -> list[str]:
    """Parse the JSON-encoded ``Article.source_ids`` field into a list of IDs.

    Returns an empty list when the field is missing, empty, or malformed.
    Malformed values are logged but never raised so a single broken record
    cannot break listing or search responses.

    Args:
        raw: Raw JSON string stored on :attr:`Article.source_ids`.

    Returns:
        List of source UUID strings (possibly empty).
    """
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        log.warning("Failed to parse Article.source_ids JSON", raw=raw)
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if item]


async def _fetch_sources(session: AsyncSession, source_ids: list[str]) -> list[Source]:
    """Fetch :class:`Source` records for a list of source IDs, preserving order.

    Missing rows (e.g. a source was deleted after the article was compiled)
    are silently dropped — callers receive only the sources that still
    exist in the database.

    Args:
        session: Async database session.
        source_ids: List of source UUIDs to fetch.

    Returns:
        Source records in the same order as ``source_ids``, with any
        missing IDs omitted.
    """
    if not source_ids:
        return []
    result = await session.execute(select(Source).where(Source.id.in_(source_ids)))  # type: ignore[attr-defined]
    by_id = {s.id: s for s in result.scalars().all()}
    return [by_id[sid] for sid in source_ids if sid in by_id]


def _to_source_response(source: Source) -> SourceResponse:
    """Project a :class:`Source` row into the API-facing :class:`SourceResponse`."""
    return SourceResponse(
        id=source.id,
        source_type=source.source_type,
        title=source.title,
        source_url=source.source_url,
        ingested_at=source.ingested_at,
    )


def _to_source_summary(source: Source) -> ArticleSourceSummary:
    """Project a :class:`Source` row into the lightweight summary form."""
    return ArticleSourceSummary(
        id=source.id,
        source_type=source.source_type,
        title=source.title,
    )


async def _build_article_summary(article: Article, session: AsyncSession) -> ArticleSummaryResponse:
    """Build an :class:`ArticleSummaryResponse` for list and search payloads.

    Args:
        article: The article ORM row.
        session: Async database session used to fetch the article's sources.

    Returns:
        Summary response with a minimal source list attached.
    """
    source_ids = _parse_source_ids(article.source_ids)
    sources = await _fetch_sources(session, source_ids)
    return ArticleSummaryResponse(
        id=article.id,
        slug=article.slug,
        title=article.title,
        summary=article.summary,
        confidence=article.confidence,
        linter_score=article.linter_score,
        sources=[_to_source_summary(s) for s in sources],
        created_at=article.created_at,
        updated_at=article.updated_at,
    )


class WikiService:
    """Provide article retrieval, search, graph building, and health reporting."""

    async def list_articles(
        self,
        session: AsyncSession,
        concept: str | None = None,
        confidence: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ArticleSummaryResponse]:
        """List wiki articles with optional filtering by concept or confidence.

        Each returned summary embeds a lightweight list of source
        descriptors so callers can show provenance directly in listing
        views without fetching the full article.

        Args:
            session: Async database session.
            concept: Optional concept filter (unused, reserved for future).
            confidence: Optional confidence level filter.
            limit: Maximum number of results.
            offset: Pagination offset.

        Returns:
            List of :class:`ArticleSummaryResponse` records with sources
            populated.
        """
        query = select(Article).offset(offset).limit(limit)
        if confidence:
            query = query.where(Article.confidence == confidence)
        result = await session.execute(query)
        articles = list(result.scalars().all())
        return [await _build_article_summary(a, session) for a in articles]

    async def get_article(self, slug: str, session: AsyncSession) -> ArticleResponse:
        """Retrieve a full article by slug, including content, backlinks, and sources.

        The returned response embeds full :class:`SourceResponse` records
        for every raw source the article was compiled from. Sources that
        no longer exist in the database (e.g. deleted after compilation)
        are silently omitted.

        Args:
            slug: The article URL slug.
            session: Async database session.

        Returns:
            :class:`ArticleResponse` with content, backlink, and source data.

        Raises:
            HTTPException: If the article is not found.
        """
        result = await session.execute(select(Article).where(Article.slug == slug))
        article = result.scalar_one_or_none()
        if not article:
            raise HTTPException(status_code=404, detail="Article not found")

        bl_in = await session.execute(select(Backlink).where(Backlink.target_article_id == article.id))
        bl_out = await session.execute(select(Backlink).where(Backlink.source_article_id == article.id))

        source_ids = _parse_source_ids(article.source_ids)
        sources = await _fetch_sources(session, source_ids)

        return ArticleResponse(
            id=article.id,
            slug=article.slug,
            title=article.title,
            summary=article.summary,
            confidence=article.confidence,
            linter_score=article.linter_score,
            concepts=[],
            backlinks_in=[b.source_article_id for b in bl_in.scalars().all()],
            backlinks_out=[b.target_article_id for b in bl_out.scalars().all()],
            content=_read_article_content(article.file_path),
            sources=[_to_source_response(s) for s in sources],
            created_at=article.created_at,
            updated_at=article.updated_at,
        )

    async def get_graph(self, session: AsyncSession) -> GraphResponse:
        """Build the full knowledge graph from articles and backlinks.

        Args:
            session: Async database session.

        Returns:
            GraphResponse containing nodes and edges.
        """
        # Backlinks are eager-loaded via selectin on Article.backlinks_out
        articles_result = await session.execute(select(Article))
        articles = articles_result.scalars().all()

        all_backlinks: list[Backlink] = []
        for a in articles:
            all_backlinks.extend(a.backlinks_out)

        connection_counts: dict[str, int] = {}
        for bl in all_backlinks:
            connection_counts[bl.source_article_id] = connection_counts.get(bl.source_article_id, 0) + 1
            connection_counts[bl.target_article_id] = connection_counts.get(bl.target_article_id, 0) + 1

        nodes = [
            GraphNode(
                id=a.id,
                label=a.title,
                concept_cluster=None,
                connection_count=connection_counts.get(a.id, 0),
                confidence=a.confidence,
            )
            for a in articles
        ]

        edges = [
            GraphEdge(
                source=bl.source_article_id,
                target=bl.target_article_id,
                context=bl.context,
            )
            for bl in all_backlinks
        ]

        return GraphResponse(nodes=nodes, edges=edges)

    async def search(
        self,
        q: str,
        session: AsyncSession,
        limit: int = 20,
    ) -> list[ArticleSummaryResponse]:
        """Full-text search across wiki article titles and content.

        Returned summaries embed lightweight source descriptors so users
        can see at a glance which raw source(s) each matched article was
        compiled from.

        Args:
            q: Search query string (minimum 2 characters).
            session: Async database session.
            limit: Maximum number of results.

        Returns:
            Matching articles as :class:`ArticleSummaryResponse` records,
            ordered by relevance score.
        """
        result = await session.execute(select(Article))
        all_articles = result.scalars().all()

        q_lower = q.lower()
        scored: list[tuple[int, Article]] = []
        for article in all_articles:
            content = _read_article_content(article.file_path)
            if q_lower in article.title.lower() or q_lower in content.lower():
                score = 10 if q_lower in article.title.lower() else 0
                score += content.lower().count(q_lower)
                scored.append((score, article))

        scored.sort(key=lambda item: item[0], reverse=True)
        top = [article for _, article in scored[:limit]]
        return [await _build_article_summary(a, session) for a in top]

    async def get_concepts(self, session: AsyncSession) -> list[Concept]:
        """Retrieve the full concept taxonomy tree.

        Args:
            session: Async database session.

        Returns:
            List of Concept records.
        """
        result = await session.execute(select(Concept))
        return list(result.scalars().all())

    async def get_health(self, session: AsyncSession) -> dict:
        """Return the latest wiki health report from the linter.

        If no linter run has been performed yet, returns a stub report
        with the current article count and a prompt to run the linter.

        Args:
            session: Async database session.

        Returns:
            Health report dict.
        """
        settings = get_settings()
        health_path = Path(settings.data_dir) / "wiki" / "_meta" / "health.json"

        if health_path.exists():
            return json.loads(health_path.read_text())

        articles_result = await session.execute(select(Article))
        articles = articles_result.scalars().all()

        return {
            "generated_at": None,
            "total_articles": len(articles),
            "total_sources": 0,
            "message": "Run the linter to generate a health report",
        }


_wiki_service: WikiService | None = None


def get_wiki_service() -> WikiService:
    """Return a singleton WikiService instance for FastAPI dependency injection."""
    global _wiki_service
    if _wiki_service is None:
        _wiki_service = WikiService()
    return _wiki_service
