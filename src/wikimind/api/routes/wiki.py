"""Endpoints for browsing wiki articles, knowledge graph, and search."""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind._datetime import utcnow_naive
from wikimind.database import get_session
from wikimind.jobs.background import get_background_compiler
from wikimind.models import (
    Article,
    ArticleResponse,
    ArticleSummaryResponse,
    Backlink,
    ContradictionResolution,
    GraphResponse,
    Job,
    JobStatus,
    JobType,
    PageType,
    RelationType,
    ResolveContradictionRequest,
)
from wikimind.services.linter import LinterService, get_linter_service
from wikimind.services.taxonomy import rebuild_taxonomy
from wikimind.services.wiki import WikiService, get_wiki_service

log = structlog.get_logger()

router = APIRouter()


@router.get("/contradiction-resolutions")
async def list_contradiction_resolutions():
    """Return the valid contradiction resolution options."""
    return [{"value": r.value, "label": r.value.replace("_", " ").title()} for r in ContradictionResolution]


@router.get("/articles", response_model=list[ArticleSummaryResponse])
async def list_articles(
    concept: str | None = None,
    confidence: str | None = None,
    page_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
    service: WikiService = Depends(get_wiki_service),
):
    """List wiki articles with optional filtering and source provenance."""
    return await service.list_articles(
        session, concept=concept, confidence=confidence, page_type=page_type, limit=limit, offset=offset
    )


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
    valid = {r.value for r in ContradictionResolution}
    if body.resolution not in valid:
        raise HTTPException(
            status_code=422,
            detail=f"resolution must be one of {sorted(valid)}",
        )

    # Check both directions — the finding's article_a/article_b order may not
    # match the backlink's source/target order.
    backlinks: list[Backlink] = []
    for src, tgt in [(source_id, target_id), (target_id, source_id)]:
        result = await session.execute(
            select(Backlink).where(
                Backlink.source_article_id == src,
                Backlink.target_article_id == tgt,
                Backlink.relation_type == RelationType.CONTRADICTS,
            )
        )
        bl = result.scalars().first()
        if bl:
            backlinks.append(bl)
    if not backlinks:
        raise HTTPException(status_code=404, detail="Contradiction backlink not found")

    now = utcnow_naive()
    for bl in backlinks:
        bl.resolution = body.resolution
        bl.resolution_note = body.resolution_note
        bl.resolved_at = now
        bl.resolved_by = "user"
        session.add(bl)

    await session.commit()

    return {
        "resolved": True,
        "source_id": source_id,
        "target_id": target_id,
        "resolution": body.resolution,
    }


_VALID_RECOMPILE_MODES = {"source", "concept"}

_PAGE_TYPE_TO_MODE = {
    PageType.SOURCE: "source",
    PageType.CONCEPT: "concept",
    PageType.ANSWER: "source",
    PageType.INDEX: "source",
    PageType.META: "source",
}


@router.post("/articles/{article_id}/recompile")
async def recompile_article(
    article_id: str,
    mode: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
):
    """Schedule an async recompilation job for an article."""
    if mode is not None and mode not in _VALID_RECOMPILE_MODES:
        raise HTTPException(
            status_code=422,
            detail=f"mode must be one of {sorted(_VALID_RECOMPILE_MODES)} or null",
        )

    article = await session.get(Article, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")

    effective_mode = mode or _PAGE_TYPE_TO_MODE.get(PageType(article.page_type), "source")

    job = Job(
        job_type=JobType.RECOMPILE_ARTICLE,
        status=JobStatus.QUEUED,
        source_id=article_id,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    compiler = get_background_compiler()
    await compiler.schedule_recompile(article_id, effective_mode, job.id)

    return {"status": "scheduled", "job_id": job.id}
