"""Endpoints for user-saved searches with tag and concept filters."""

import structlog
from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.api.deps import get_current_user_id
from wikimind.database import get_session
from wikimind.models import (
    CreateSavedSearchRequest,
    SavedSearchExecuteResponse,
    SavedSearchResponse,
)
from wikimind.services.saved_searches import SavedSearchService, get_saved_search_service
from wikimind.services.wiki import WikiService, get_wiki_service

log = structlog.get_logger()

router = APIRouter()


@router.post("", response_model=SavedSearchResponse, status_code=201)
async def create_saved_search(
    body: CreateSavedSearchRequest,
    session: AsyncSession = Depends(get_session),
    service: SavedSearchService = Depends(get_saved_search_service),
    user_id: str = Depends(get_current_user_id),
):
    """Create a new saved search."""
    return await service.create(
        session,
        user_id=user_id,
        name=body.name,
        query=body.query,
        filters_json=body.filters_json,
    )


@router.get("", response_model=list[SavedSearchResponse])
async def list_saved_searches(
    session: AsyncSession = Depends(get_session),
    service: SavedSearchService = Depends(get_saved_search_service),
    user_id: str = Depends(get_current_user_id),
):
    """List all saved searches for the current user."""
    return await service.list_searches(session, user_id=user_id)


@router.delete(
    "/{search_id}",
    status_code=204,
    responses={404: {"description": "Saved search not found"}},
)
async def delete_saved_search(
    search_id: str,
    session: AsyncSession = Depends(get_session),
    service: SavedSearchService = Depends(get_saved_search_service),
    user_id: str = Depends(get_current_user_id),
):
    """Delete a saved search."""
    await service.delete(session, search_id=search_id, user_id=user_id)


@router.post(
    "/{search_id}/execute",
    response_model=SavedSearchExecuteResponse,
    responses={404: {"description": "Saved search not found"}},
)
async def execute_saved_search(
    search_id: str,
    session: AsyncSession = Depends(get_session),
    search_service: SavedSearchService = Depends(get_saved_search_service),
    wiki_service: WikiService = Depends(get_wiki_service),
    user_id: str = Depends(get_current_user_id),
):
    """Execute a saved search and return matching articles."""
    saved_response, article_ids = await search_service.execute(
        session,
        search_id=search_id,
        user_id=user_id,
    )
    articles = await wiki_service.list_articles(
        session,
        user_id=user_id,
        article_ids=article_ids,
    )
    return SavedSearchExecuteResponse(
        saved_search=saved_response,
        articles=articles,
    )
