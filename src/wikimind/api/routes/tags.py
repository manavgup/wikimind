"""Endpoints for user-created tags and article-tag associations."""

import structlog
from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.api.deps import get_current_user_id
from wikimind.database import get_session
from wikimind.models import (
    CreateTagRequest,
    TagResponse,
)
from wikimind.services.tags import TagService, get_tag_service
from wikimind.services.wiki import WikiService, get_wiki_service

log = structlog.get_logger()

router = APIRouter()


@router.post("", response_model=TagResponse, status_code=201)
async def create_tag(
    body: CreateTagRequest,
    session: AsyncSession = Depends(get_session),
    service: TagService = Depends(get_tag_service),
    user_id: str = Depends(get_current_user_id),
):
    """Create a new user tag."""
    return await service.create_tag(session, user_id=user_id, name=body.name, color=body.color)


@router.get("", response_model=list[TagResponse])
async def list_tags(
    session: AsyncSession = Depends(get_session),
    service: TagService = Depends(get_tag_service),
    user_id: str = Depends(get_current_user_id),
):
    """List all tags for the current user."""
    return await service.list_tags(session, user_id=user_id)


@router.delete(
    "/{tag_id}",
    status_code=204,
    responses={404: {"description": "Tag not found"}},
)
async def delete_tag(
    tag_id: str,
    session: AsyncSession = Depends(get_session),
    service: TagService = Depends(get_tag_service),
    user_id: str = Depends(get_current_user_id),
):
    """Delete a tag and all its article associations."""
    await service.delete_tag(session, tag_id=tag_id, user_id=user_id)


@router.get(
    "/{tag_id}/articles",
    response_model=list,
    responses={404: {"description": "Tag not found"}},
)
async def get_articles_by_tag(
    tag_id: str,
    session: AsyncSession = Depends(get_session),
    tag_service: TagService = Depends(get_tag_service),
    wiki_service: WikiService = Depends(get_wiki_service),
    user_id: str = Depends(get_current_user_id),
):
    """Get articles tagged with a specific tag."""
    article_ids = await tag_service.get_articles_by_tag(
        session,
        tag_id=tag_id,
        user_id=user_id,
    )
    return await wiki_service.list_articles(
        session,
        user_id=user_id,
        article_ids=article_ids,
    )
