"""Synthesis page endpoints — cross-cutting analysis across multiple sources."""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.api.deps import get_current_user_id
from wikimind.database import get_session
from wikimind.engine.synthesis_compiler import SynthesisCompiler
from wikimind.models import (
    ArticleSummaryResponse,
    CreateSynthesisRequest,
    PageType,
    SynthesisResponse,
)
from wikimind.services.wiki import WikiService, get_wiki_service

log = structlog.get_logger()

router = APIRouter()


@router.post(
    "/synthesize",
    response_model=SynthesisResponse,
    status_code=201,
    responses={
        422: {"description": "Not enough relevant articles for synthesis"},
    },
)
async def create_synthesis(
    body: CreateSynthesisRequest,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
) -> SynthesisResponse:
    """Create a synthesis page that analyzes across multiple source articles.

    Takes a topic or question and produces a cross-cutting analysis identifying
    themes, contradictions, timelines, and knowledge gaps.

    Requires at least 2 relevant articles in the wiki.
    """
    compiler = SynthesisCompiler(user_id)
    result = await compiler.synthesize(
        query=body.query,
        session=session,
        article_ids=body.article_ids,
    )

    if result is None:
        raise HTTPException(
            status_code=422,
            detail="Not enough relevant articles for synthesis (need at least 2).",
        )

    article, compilation = result
    return SynthesisResponse(
        id=article.id,
        slug=article.slug,
        title=article.title,
        query=body.query,
        summary=compilation.summary,
        themes=compilation.themes,
        source_count=len(compilation.source_article_ids),
        source_article_ids=compilation.source_article_ids,
        created_at=article.created_at,
        page_type=PageType.SYNTHESIS,
    )


@router.get(
    "/synthesis",
    response_model=list[ArticleSummaryResponse],
)
async def list_synthesis_pages(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    service: WikiService = Depends(get_wiki_service),
    user_id: str = Depends(get_current_user_id),
) -> list[ArticleSummaryResponse]:
    """List all synthesis pages for the current user."""
    return await service.list_articles(
        session,
        page_type="synthesis",
        limit=limit,
        offset=offset,
        user_id=user_id,
    )
