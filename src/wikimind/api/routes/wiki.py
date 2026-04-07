"""Endpoints for browsing wiki articles, knowledge graph, and search."""

from fastapi import APIRouter, Depends, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.database import get_session
from wikimind.models import ArticleResponse, ArticleSummaryResponse, GraphResponse
from wikimind.services.wiki import WikiService, get_wiki_service

router = APIRouter()


@router.get("/articles", response_model=list[ArticleSummaryResponse])
async def list_articles(
    concept: str | None = None,
    confidence: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
    service: WikiService = Depends(get_wiki_service),
):
    """List wiki articles with optional filtering and source provenance."""
    return await service.list_articles(session, concept=concept, confidence=confidence, limit=limit, offset=offset)


@router.get("/articles/{slug}", response_model=ArticleResponse)
async def get_article(
    slug: str,
    session: AsyncSession = Depends(get_session),
    service: WikiService = Depends(get_wiki_service),
):
    """Get full article with content, backlinks, and source provenance."""
    return await service.get_article(slug, session)


@router.get("/graph", response_model=GraphResponse)
async def get_graph(
    session: AsyncSession = Depends(get_session),
    service: WikiService = Depends(get_wiki_service),
):
    """Full knowledge graph -- nodes and edges."""
    return await service.get_graph(session)


@router.get("/search", response_model=list[ArticleSummaryResponse])
async def search(
    q: str = Query(..., min_length=2),
    limit: int = 20,
    session: AsyncSession = Depends(get_session),
    service: WikiService = Depends(get_wiki_service),
):
    """Full-text search across wiki articles with source provenance."""
    return await service.search(q, session, limit=limit)


@router.get("/concepts")
async def get_concepts(
    session: AsyncSession = Depends(get_session),
    service: WikiService = Depends(get_wiki_service),
):
    """Concept taxonomy tree."""
    return await service.get_concepts(session)


@router.get("/health")
async def get_health(
    session: AsyncSession = Depends(get_session),
    service: WikiService = Depends(get_wiki_service),
):
    """Latest wiki health report from linter."""
    return await service.get_health(session)
