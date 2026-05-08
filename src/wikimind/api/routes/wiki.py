"""Endpoints for browsing wiki articles, knowledge graph, and search."""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind._datetime import utcnow_naive
from wikimind.api.deps import get_current_user_id
from wikimind.database import get_session
from wikimind.jobs.background import get_background_compiler
from wikimind.models import (
    Article,
    ArticleEditRequest,
    ArticleRelationshipsResponse,
    ArticleResponse,
    ArticleSummaryResponse,
    ArticleTagResponse,
    Backlink,
    Contradiction,
    ContradictionResolution,
    ContradictionResolutionOption,
    ContradictionResponse,
    ContradictionStatus,
    CreateStubRequest,
    CreateStubResponse,
    GraphResponse,
    HealthSummaryResponse,
    Job,
    JobStatus,
    JobType,
    PageType,
    RebuildConceptsResponse,
    RecompileResponse,
    RefreshArticleResponse,
    RelationType,
    ResolveContradictionBody,
    ResolveContradictionRequest,
    ResolveContradictionResponse,
    SearchResponse,
    SearchResult,
    TagArticleRequest,
    TagResponse,
    WikilinkMatch,
)
from wikimind.services.contradiction import ContradictionService, get_contradiction_service
from wikimind.services.linter import LinterService, get_linter_service
from wikimind.services.search import SearchService, get_search_service
from wikimind.services.tags import TagService, get_tag_service
from wikimind.services.taxonomy import rebuild_taxonomy
from wikimind.services.wiki import WikiService, _staleness_score, get_wiki_service

log = structlog.get_logger()

router = APIRouter()


@router.get(
    "/contradiction-resolutions",
    response_model=list[ContradictionResolutionOption],
)
async def list_contradiction_resolutions():
    """Return the valid contradiction resolution options."""
    return [
        ContradictionResolutionOption(value=r.value, label=r.value.replace("_", " ").title())
        for r in ContradictionResolution
    ]


@router.get("/contradictions", response_model=list[ContradictionResponse])
async def list_contradictions(
    status: ContradictionStatus | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
    service: ContradictionService = Depends(get_contradiction_service),
    user_id: str = Depends(get_current_user_id),
):
    """List all contradictions for the user, optionally filtered by status."""
    return await service.list_contradictions(session, user_id=user_id, status=status, limit=limit, offset=offset)


@router.get(
    "/contradictions/{contradiction_id}",
    response_model=ContradictionResponse,
    responses={404: {"description": "Contradiction not found"}},
)
async def get_contradiction(
    contradiction_id: str,
    session: AsyncSession = Depends(get_session),
    service: ContradictionService = Depends(get_contradiction_service),
    user_id: str = Depends(get_current_user_id),
):
    """Get a single contradiction with article details."""
    return await service.get_contradiction(session, contradiction_id, user_id=user_id)


@router.patch(
    "/contradictions/{contradiction_id}",
    response_model=ContradictionResponse,
    responses={404: {"description": "Contradiction not found"}},
)
async def resolve_persisted_contradiction(
    contradiction_id: str,
    body: ResolveContradictionBody,
    session: AsyncSession = Depends(get_session),
    service: ContradictionService = Depends(get_contradiction_service),
    user_id: str = Depends(get_current_user_id),
):
    """Resolve or dismiss a contradiction."""
    return await service.resolve_contradiction(
        session,
        contradiction_id,
        user_id=user_id,
        new_status=body.status,
        resolution=body.resolution,
    )


@router.get("/articles", response_model=list[ArticleSummaryResponse])
async def list_articles(
    concept: str | None = None,
    confidence: str | None = None,
    page_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
    service: WikiService = Depends(get_wiki_service),
    user_id: str = Depends(get_current_user_id),
):
    """List wiki articles with optional filtering and source provenance."""
    return await service.list_articles(
        session,
        concept=concept,
        confidence=confidence,
        page_type=page_type,
        limit=limit,
        offset=offset,
        user_id=user_id,
    )


@router.post(
    "/articles/stub",
    response_model=CreateStubResponse,
    status_code=201,
)
async def create_stub_article(
    body: CreateStubRequest,
    session: AsyncSession = Depends(get_session),
    service: WikiService = Depends(get_wiki_service),
    user_id: str = Depends(get_current_user_id),
):
    """Create a stub wiki article — a placeholder page for a concept not yet compiled."""
    return await service.create_stub_article(
        title=body.title,
        body_markdown=body.body_markdown,
        session=session,
        user_id=user_id,
    )


@router.get(
    "/wikilinks/resolve",
    response_model=list[WikilinkMatch],
)
async def resolve_wikilinks(
    q: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
    service: WikiService = Depends(get_wiki_service),
    user_id: str = Depends(get_current_user_id),
):
    """Search articles by partial title for wikilink autocomplete."""
    return await service.resolve_wikilinks(q, session, user_id=user_id, limit=limit)


@router.get(
    "/articles/random",
    response_model=ArticleSummaryResponse,
    responses={404: {"description": "No articles found"}},
)
async def get_random_article(
    session: AsyncSession = Depends(get_session),
    service: WikiService = Depends(get_wiki_service),
    user_id: str = Depends(get_current_user_id),
):
    """Return a random article belonging to the current user."""
    return await service.get_random_article(session, user_id=user_id)


@router.get(
    "/articles/{id_or_slug}",
    response_model=ArticleResponse,
    responses={404: {"description": "Article not found"}},
)
async def get_article(
    id_or_slug: str,
    session: AsyncSession = Depends(get_session),
    service: WikiService = Depends(get_wiki_service),
    user_id: str = Depends(get_current_user_id),
):
    """Get full article by ID or slug, with content, backlinks, and source provenance."""
    return await service.get_article(id_or_slug, session, user_id=user_id)


@router.patch(
    "/articles/{id_or_slug}",
    response_model=ArticleResponse,
    responses={404: {"description": "Article not found"}},
)
async def edit_article(
    id_or_slug: str,
    body: ArticleEditRequest,
    session: AsyncSession = Depends(get_session),
    service: WikiService = Depends(get_wiki_service),
    user_id: str = Depends(get_current_user_id),
):
    """Manually edit an article's content and/or title.

    Sets ``manually_edited=True`` so that recompilation respects user edits.
    Only the article owner can edit.
    """
    return await service.edit_article(
        id_or_slug,
        session,
        user_id=user_id,
        content=body.content,
        title=body.title,
    )


@router.get("/graph", response_model=GraphResponse)
async def get_graph(
    relation_type: RelationType | None = Query(default=None),
    from_article: str | None = Query(default=None),
    to_article: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
    service: WikiService = Depends(get_wiki_service),
    user_id: str = Depends(get_current_user_id),
):
    """Full knowledge graph -- nodes and edges.

    Optional query parameters filter the returned edge set:

    * ``relation_type`` — keep only edges of one semantic relation type.
    * ``from_article`` — id or slug of the source article.
    * ``to_article`` — id or slug of the target article.

    Filters compose with AND. Filtering is pushed down into SQL.
    """
    return await service.get_graph(
        session,
        user_id=user_id,
        relation_type=relation_type,
        from_article=from_article,
        to_article=to_article,
    )


@router.get(
    "/articles/{id_or_slug}/relationships",
    response_model=ArticleRelationshipsResponse,
    responses={404: {"description": "Article not found"}},
)
async def get_article_relationships(
    id_or_slug: str,
    session: AsyncSession = Depends(get_session),
    service: WikiService = Depends(get_wiki_service),
    user_id: str = Depends(get_current_user_id),
):
    """Return typed relationships for an article, grouped by direction and type."""
    return await service.get_relationships(id_or_slug, session, user_id=user_id)


@router.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(..., min_length=2),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
    search_service: SearchService = Depends(get_search_service),
    user_id: str = Depends(get_current_user_id),
):
    """Full-text search across wiki articles using BM25 ranking."""
    fts_response = await search_service.search(q, session, user_id=user_id, limit=limit, offset=offset)
    results = [
        SearchResult(
            article_id=r.article_id,
            slug=r.slug,
            title=r.title,
            snippet=r.snippet,
            rank=r.rank,
        )
        for r in fts_response.results
    ]
    return SearchResponse(results=results, total=fts_response.total, query=q)


@router.get("/concepts")
async def get_concepts(
    include_empty: bool = True,
    session: AsyncSession = Depends(get_session),
    service: WikiService = Depends(get_wiki_service),
    user_id: str = Depends(get_current_user_id),
):
    """Concept taxonomy tree."""
    return await service.get_concepts(session, include_empty=include_empty, user_id=user_id)


@router.post("/concepts/rebuild", response_model=RebuildConceptsResponse)
async def rebuild_concepts(
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    """Trigger LLM-powered taxonomy hierarchy rebuild."""
    await rebuild_taxonomy(session, user_id=user_id)
    return RebuildConceptsResponse(status="ok")


@router.get(
    "/concepts/{name}",
    responses={404: {"description": "Concept not found"}},
)
async def get_concept(
    name: str,
    session: AsyncSession = Depends(get_session),
    service: WikiService = Depends(get_wiki_service),
    user_id: str = Depends(get_current_user_id),
):
    """Concept detail with linked articles."""
    return await service.get_concept(name, session, user_id=user_id)


@router.get("/concepts/{name}/articles", response_model=list[ArticleSummaryResponse])
async def get_concept_articles(
    name: str,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
    service: WikiService = Depends(get_wiki_service),
    user_id: str = Depends(get_current_user_id),
):
    """Articles tagged with this concept."""
    return await service.get_concept_articles(name, session, limit=limit, offset=offset, user_id=user_id)


@router.get("/health", response_model=HealthSummaryResponse)
async def get_health(
    session: AsyncSession = Depends(get_session),
    linter_service: LinterService = Depends(get_linter_service),
    user_id: str = Depends(get_current_user_id),
):
    """Latest wiki health report from linter.

    DEPRECATED: Use GET /lint/reports/latest instead. This endpoint
    delegates to the new LinterService for backward compatibility.
    """
    try:
        detail = await linter_service.get_latest(session, user_id=user_id)
        return HealthSummaryResponse(
            generated_at=detail.report.generated_at,
            total_articles=detail.report.article_count,
            total_findings=detail.report.total_findings,
            contradictions_count=detail.report.contradictions_count,
            orphans_count=detail.report.orphans_count,
            status=detail.report.status,
        )
    except (HTTPException, SQLAlchemyError):
        count_result = await session.execute(select(func.count()).select_from(Article))
        return HealthSummaryResponse(
            total_articles=count_result.scalar() or 0,
            message="Run the linter to generate a health report",
        )


@router.post(
    "/backlinks/{source_id}/{target_id}/resolve",
    response_model=ResolveContradictionResponse,
    deprecated=True,
)
async def resolve_contradiction(
    source_id: str,
    target_id: str,
    body: ResolveContradictionRequest,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    """Resolve a contradiction between two articles.

    DEPRECATED: Use ``PATCH /wiki/contradictions/{id}`` instead. This endpoint
    updates the Backlink for backward compatibility AND forwards the resolution
    to the Contradiction table (single source of truth).
    """
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

    # Forward resolution to the Contradiction table (single source of truth)
    ids = sorted([source_id, target_id])
    ctr_result = await session.execute(
        select(Contradiction).where(
            Contradiction.user_id == user_id,
            Contradiction.status == ContradictionStatus.ACTIVE,
            Contradiction.article_a_id.in_(ids),  # type: ignore[attr-defined]
            Contradiction.article_b_id.in_(ids),  # type: ignore[attr-defined]
        )
    )
    for ctr in ctr_result.scalars().all():
        ctr.status = ContradictionStatus.RESOLVED
        ctr.resolution = body.resolution
        ctr.resolved_at = now
        ctr.resolved_by = user_id
        session.add(ctr)

    await session.commit()

    return ResolveContradictionResponse(
        resolved=True,
        source_id=source_id,
        target_id=target_id,
        resolution=body.resolution,
    )


@router.post(
    "/articles/{id_or_slug}/refresh",
    response_model=RefreshArticleResponse,
    responses={404: {"description": "Article not found"}},
)
async def refresh_article(
    id_or_slug: str,
    session: AsyncSession = Depends(get_session),
    service: WikiService = Depends(get_wiki_service),
    user_id: str = Depends(get_current_user_id),
):
    """Mark an article as 'still current' without recompiling.

    Creates a manual_refresh reinforcement event and resets the article's
    staleness score. Use this when you have reviewed an article and
    confirmed its content is still accurate.
    """
    article = await service.refresh_article(id_or_slug, session, user_id=user_id)
    return RefreshArticleResponse(
        status="refreshed",
        staleness_score=_staleness_score(article),
    )


_VALID_RECOMPILE_MODES = {"source", "concept"}

_PAGE_TYPE_TO_MODE = {
    PageType.SOURCE: "source",
    PageType.CONCEPT: "concept",
    PageType.ANSWER: "source",
    PageType.INDEX: "source",
    PageType.META: "source",
}


@router.post(
    "/articles/{article_id}/recompile",
    response_model=RecompileResponse,
    responses={409: {"description": "Article has manual edits"}},
)
async def recompile_article(
    article_id: str,
    mode: str | None = Query(default=None),
    force: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    """Schedule an async recompilation job for an article.

    If the article has been manually edited (``manually_edited=True``),
    returns 409 Conflict unless ``force=true`` is passed. When forced,
    the manual edits flag is cleared before recompilation.
    """
    if mode is not None and mode not in _VALID_RECOMPILE_MODES:
        raise HTTPException(
            status_code=422,
            detail=f"mode must be one of {sorted(_VALID_RECOMPILE_MODES)} or null",
        )

    article = await session.get(Article, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")

    if article.manually_edited and not force:
        raise HTTPException(
            status_code=409,
            detail="Article has manual edits. Use force=true to overwrite.",
        )

    # Clear manual edit flag when force-recompiling
    if article.manually_edited and force:
        article.manually_edited = False
        article.edited_at = None
        session.add(article)
        await session.commit()

    effective_mode = mode or _PAGE_TYPE_TO_MODE.get(PageType(article.page_type), "source")

    job = Job(
        job_type=JobType.RECOMPILE_ARTICLE,
        status=JobStatus.QUEUED,
        source_id=article_id,
        user_id=user_id,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    compiler = get_background_compiler()
    await compiler.schedule_recompile(article_id, effective_mode, job.id, user_id=user_id)

    return RecompileResponse(status="scheduled", job_id=job.id)


# ---------------------------------------------------------------------------
# Article tagging endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/articles/{article_id}/tags",
    response_model=ArticleTagResponse,
    status_code=201,
    responses={404: {"description": "Article or tag not found"}},
)
async def tag_article(
    article_id: str,
    body: TagArticleRequest,
    session: AsyncSession = Depends(get_session),
    tag_service: TagService = Depends(get_tag_service),
    user_id: str = Depends(get_current_user_id),
):
    """Apply a tag to an article."""
    await tag_service.tag_article(
        session,
        article_id=article_id,
        tag_id=body.tag_id,
        user_id=user_id,
    )
    return ArticleTagResponse(article_id=article_id, tag_id=body.tag_id)


@router.delete(
    "/articles/{article_id}/tags/{tag_id}",
    status_code=204,
    responses={404: {"description": "Tag association not found"}},
)
async def untag_article(
    article_id: str,
    tag_id: str,
    session: AsyncSession = Depends(get_session),
    tag_service: TagService = Depends(get_tag_service),
    user_id: str = Depends(get_current_user_id),
):
    """Remove a tag from an article."""
    await tag_service.untag_article(
        session,
        article_id=article_id,
        tag_id=tag_id,
        user_id=user_id,
    )


@router.get(
    "/articles/{article_id}/tags",
    response_model=list[TagResponse],
    responses={404: {"description": "Article not found"}},
)
async def get_article_tags(
    article_id: str,
    session: AsyncSession = Depends(get_session),
    tag_service: TagService = Depends(get_tag_service),
    _user_id: str = Depends(get_current_user_id),
):
    """Get all tags applied to an article."""
    return await tag_service.get_tags_for_article(session, article_id=article_id)
