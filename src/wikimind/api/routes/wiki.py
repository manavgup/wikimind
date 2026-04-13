"""Endpoints for browsing wiki articles, knowledge graph, and search."""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind._datetime import utcnow_naive
from wikimind.database import get_session
from wikimind.models import (
    Article,
    ArticleResponse,
    ArticleSummaryResponse,
    Backlink,
    GraphResponse,
    RelationType,
    ResolveContradictionRequest,
)
from wikimind.services.linter import LinterService, get_linter_service
from wikimind.services.taxonomy import rebuild_taxonomy
from wikimind.services.wiki import WikiService, get_wiki_service

log = structlog.get_logger()

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


@router.get("/articles/{id_or_slug}", response_model=ArticleResponse)
async def get_article(
    id_or_slug: str,
    session: AsyncSession = Depends(get_session),
    service: WikiService = Depends(get_wiki_service),
):
    """Get full article by ID or slug, with content, backlinks, and source provenance."""
    return await service.get_article(id_or_slug, session)


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
    include_empty: bool = True,
    session: AsyncSession = Depends(get_session),
    service: WikiService = Depends(get_wiki_service),
):
    """Concept taxonomy tree."""
    return await service.get_concepts(session, include_empty=include_empty)


@router.post("/concepts/rebuild")
async def rebuild_concepts(
    session: AsyncSession = Depends(get_session),
):
    """Trigger LLM-powered taxonomy hierarchy rebuild."""
    await rebuild_taxonomy(session)
    return {"status": "ok"}


@router.get("/health")
async def get_health(
    session: AsyncSession = Depends(get_session),
    linter_service: LinterService = Depends(get_linter_service),
):
    """Latest wiki health report from linter.

    DEPRECATED: Use GET /lint/reports/latest instead. This endpoint
    delegates to the new LinterService for backward compatibility.
    """
    try:
        detail = await linter_service.get_latest(session)
        return {
            "generated_at": detail.report.generated_at.isoformat() if detail.report.generated_at else None,
            "total_articles": detail.report.article_count,
            "total_findings": detail.report.total_findings,
            "contradictions_count": detail.report.contradictions_count,
            "orphans_count": detail.report.orphans_count,
            "status": detail.report.status,
        }
    except Exception:
        count_result = await session.execute(select(func.count()).select_from(Article))
        return {
            "generated_at": None,
            "total_articles": count_result.scalar() or 0,
            "message": "Run the linter to generate a health report",
        }


@router.post("/backlinks/{source_id}/{target_id}/resolve")
async def resolve_contradiction(
    source_id: str,
    target_id: str,
    body: ResolveContradictionRequest,
    session: AsyncSession = Depends(get_session),
):
    """Resolve a contradiction between two articles."""
    _VALID_RESOLUTIONS = {"source_a_wins", "source_b_wins", "both_valid", "superseded"}
    if body.resolution not in _VALID_RESOLUTIONS:
        raise HTTPException(
            status_code=422,
            detail=f"resolution must be one of {sorted(_VALID_RESOLUTIONS)}",
        )

    result = await session.execute(
        select(Backlink).where(
            Backlink.source_article_id == source_id,
            Backlink.target_article_id == target_id,
            Backlink.relation_type == RelationType.CONTRADICTS,
        )
    )
    backlink = result.scalars().first()
    if backlink is None:
        raise HTTPException(status_code=404, detail="Contradiction backlink not found")

    now = utcnow_naive()
    backlink.resolution = body.resolution
    backlink.resolution_note = body.resolution_note
    backlink.resolved_at = now
    backlink.resolved_by = "user"
    session.add(backlink)

    inv_result = await session.execute(
        select(Backlink).where(
            Backlink.source_article_id == target_id,
            Backlink.target_article_id == source_id,
            Backlink.relation_type == RelationType.CONTRADICTS,
        )
    )
    inverse = inv_result.scalars().first()
    if inverse is not None:
        inverse.resolution = body.resolution
        inverse.resolution_note = body.resolution_note
        inverse.resolved_at = now
        inverse.resolved_by = "user"
        session.add(inverse)

    await session.commit()

    return {
        "resolved": True,
        "source_id": source_id,
        "target_id": target_id,
        "resolution": body.resolution,
    }
