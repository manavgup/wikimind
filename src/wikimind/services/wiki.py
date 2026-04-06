"""Retrieve wiki articles, build the knowledge graph, and search content.

Centralizes all article retrieval, full-text search, concept taxonomy,
and health report generation so route handlers stay thin.
"""

import json
from pathlib import Path

from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.config import get_settings
from wikimind.models import (
    Article,
    ArticleResponse,
    Backlink,
    Concept,
    GraphEdge,
    GraphNode,
    GraphResponse,
)


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


class WikiService:
    """Provide article retrieval, search, graph building, and health reporting."""

    async def list_articles(
        self,
        session: AsyncSession,
        concept: str | None = None,
        confidence: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Article]:
        """List wiki articles with optional filtering by concept or confidence.

        Args:
            session: Async database session.
            concept: Optional concept filter (unused, reserved for future).
            confidence: Optional confidence level filter.
            limit: Maximum number of results.
            offset: Pagination offset.

        Returns:
            List of Article records.
        """
        query = select(Article).offset(offset).limit(limit)
        if confidence:
            query = query.where(Article.confidence == confidence)
        result = await session.execute(query)
        return list(result.scalars().all())

    async def get_article(self, slug: str, session: AsyncSession) -> ArticleResponse:
        """Retrieve a full article by slug, including content and backlinks.

        Args:
            slug: The article URL slug.
            session: Async database session.

        Returns:
            ArticleResponse with content and backlink data.

        Raises:
            HTTPException: If the article is not found.
        """
        result = await session.execute(select(Article).where(Article.slug == slug))
        article = result.scalar_one_or_none()
        if not article:
            raise HTTPException(status_code=404, detail="Article not found")

        bl_in = await session.execute(select(Backlink).where(Backlink.target_article_id == article.id))
        bl_out = await session.execute(select(Backlink).where(Backlink.source_article_id == article.id))

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

    async def search(self, q: str, session: AsyncSession, limit: int = 20) -> list[Article]:
        """Full-text search across wiki article titles and content.

        Args:
            q: Search query string (minimum 2 characters).
            session: Async database session.
            limit: Maximum number of results.

        Returns:
            List of matching Article records, ordered by relevance score.
        """
        result = await session.execute(select(Article))
        all_articles = result.scalars().all()

        q_lower = q.lower()
        matches = []
        for article in all_articles:
            content = _read_article_content(article.file_path)
            if q_lower in article.title.lower() or q_lower in content.lower():
                score = 10 if q_lower in article.title.lower() else 0
                score += content.lower().count(q_lower)
                matches.append({"article": article, "score": score})

        matches.sort(key=lambda x: x["score"], reverse=True)
        return [m["article"] for m in matches[:limit]]

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
