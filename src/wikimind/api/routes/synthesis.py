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
    SynthesisConfirmRequest,
    SynthesisConfirmResponse,
    SynthesisPreviewRequest,
    SynthesisPreviewResponse,
    SynthesisRefineRequest,
    SynthesisRefineResponse,
    SynthesisResponse,
)
from wikimind.services.factories import get_wiki_service
from wikimind.services.wiki import WikiService

log = structlog.get_logger()

router = APIRouter()


@router.post(
    "/synthesis/preview",
    response_model=SynthesisPreviewResponse,
    responses={
        422: {"description": "Not enough articles or synthesis failed"},
    },
)
async def preview_synthesis(
    body: SynthesisPreviewRequest,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
) -> SynthesisPreviewResponse:
    """Generate a synthesis draft without saving it.

    Returns draft content, suggested title, and key themes for user review.
    The draft can be refined with feedback or confirmed to save.
    """
    compiler = SynthesisCompiler(user_id)
    result = await compiler.preview(
        session=session,
        article_ids=body.article_ids,
        synthesis_type=body.synthesis_type,
        guidance=body.guidance,
    )

    if result is None:
        raise HTTPException(
            status_code=422,
            detail="Could not generate synthesis preview (need at least 2 articles).",
        )

    return SynthesisPreviewResponse(
        draft_content=result.article_body,
        suggested_title=result.title,
        summary=result.summary,
        themes=result.themes,
        article_ids=result.source_article_ids,
        source_count=len(result.source_article_ids),
    )


@router.post(
    "/synthesis/refine",
    response_model=SynthesisRefineResponse,
    responses={
        422: {"description": "Refinement failed"},
    },
)
async def refine_synthesis(
    body: SynthesisRefineRequest,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
) -> SynthesisRefineResponse:
    """Refine a synthesis draft with user feedback.

    Takes a previous draft and user guidance, regenerates the synthesis
    incorporating the feedback. Can be called multiple times for iterative
    refinement before confirming.
    """
    compiler = SynthesisCompiler(user_id)
    result = await compiler.refine(
        session=session,
        article_ids=body.article_ids,
        previous_draft=body.draft_content,
        guidance=body.guidance,
    )

    if result is None:
        raise HTTPException(
            status_code=422,
            detail="Could not refine synthesis (need at least 2 articles).",
        )

    return SynthesisRefineResponse(
        draft_content=result.article_body,
        suggested_title=result.title,
        summary=result.summary,
        themes=result.themes,
        article_ids=result.source_article_ids,
        source_count=len(result.source_article_ids),
    )


@router.post(
    "/synthesis/confirm",
    response_model=SynthesisConfirmResponse,
    status_code=201,
    responses={
        422: {"description": "Could not save synthesis"},
    },
)
async def confirm_synthesis(
    body: SynthesisConfirmRequest,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
) -> SynthesisConfirmResponse:
    """Save a confirmed synthesis draft as a real wiki article.

    Takes the final draft content and title from a preview/refine cycle
    and persists it as a synthesis article in the wiki.
    """
    compiler = SynthesisCompiler(user_id)
    article = await compiler.confirm(
        session=session,
        title=body.title,
        draft_content=body.draft_content,
        article_ids=body.article_ids,
    )

    if article is None:
        raise HTTPException(
            status_code=422,
            detail="Could not save synthesis (need at least 2 valid articles).",
        )

    return SynthesisConfirmResponse(
        id=article.id,
        slug=article.slug,
        title=article.title,
        summary=article.summary or "",
        themes=[],
        source_count=len(body.article_ids),
        source_article_ids=body.article_ids,
        created_at=article.created_at,
        page_type=PageType.SYNTHESIS,
    )


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
