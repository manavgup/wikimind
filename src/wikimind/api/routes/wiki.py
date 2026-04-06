"""Endpoints for browsing wiki articles, knowledge graph, and search."""

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.config import get_settings
from wikimind.database import get_session
from wikimind.models import (
    Article,
    ArticleResponse,
    Backlink,
    Concept,
    GraphEdge,
    GraphNode,
    GraphResponse,
)

router = APIRouter()


def _read_article_content(file_path: str) -> str:
    """Read article markdown content from disk."""
    try:
        return Path(file_path).read_text(encoding="utf-8")
    except Exception:
        return ""


@router.get("/articles")
async def list_articles(
    concept: str | None = None,
    confidence: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    """List wiki articles with optional filtering."""
    query = select(Article).offset(offset).limit(limit)
    if confidence:
        query = query.where(Article.confidence == confidence)
    result = await session.execute(query)
    articles = result.scalars().all()
    return articles


@router.get("/articles/{slug}", response_model=ArticleResponse)
async def get_article(
    slug: str,
    session: AsyncSession = Depends(get_session),
):
    """Get full article with content and backlinks."""
    result = await session.execute(select(Article).where(Article.slug == slug))
    article = result.scalar_one_or_none()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    # Get backlinks
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


@router.get("/graph", response_model=GraphResponse)
async def get_graph(session: AsyncSession = Depends(get_session)):
    """Full knowledge graph — nodes and edges."""
    articles_result = await session.execute(select(Article))
    articles = articles_result.scalars().all()

    backlinks_result = await session.execute(select(Backlink))
    backlinks = backlinks_result.scalars().all()

    # Count connections per article
    connection_counts: dict[str, int] = {}
    for bl in backlinks:
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
        for bl in backlinks
    ]

    return GraphResponse(nodes=nodes, edges=edges)


@router.get("/search")
async def search(
    q: str = Query(..., min_length=2),
    limit: int = 20,
    session: AsyncSession = Depends(get_session),
):
    """Full-text search across wiki articles."""
    result = await session.execute(select(Article))
    all_articles = result.scalars().all()

    q_lower = q.lower()
    matches = []
    for article in all_articles:
        content = _read_article_content(article.file_path)
        if q_lower in article.title.lower() or q_lower in content.lower():
            # Score: title match = 10, content match = 1 per occurrence
            score = 10 if q_lower in article.title.lower() else 0
            score += content.lower().count(q_lower)
            matches.append({"article": article, "score": score})

    matches.sort(key=lambda x: x["score"], reverse=True)
    return [m["article"] for m in matches[:limit]]


@router.get("/concepts")
async def get_concepts(session: AsyncSession = Depends(get_session)):
    """Concept taxonomy tree."""
    result = await session.execute(select(Concept))
    return result.scalars().all()


@router.get("/health")
async def get_health(session: AsyncSession = Depends(get_session)):
    """Latest wiki health report from linter."""
    settings = get_settings()
    health_path = Path(settings.data_dir) / "wiki" / "_meta" / "health.json"

    if health_path.exists():
        return json.loads(health_path.read_text())

    # No linter run yet
    articles_result = await session.execute(select(Article))
    articles = articles_result.scalars().all()

    return {
        "generated_at": None,
        "total_articles": len(articles),
        "total_sources": 0,
        "message": "Run the linter to generate a health report",
    }
