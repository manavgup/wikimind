"""Endpoints for human-in-the-loop discussion before compilation (issue #418).

Users can discuss an article's source material with the LLM, then trigger
recompilation incorporating the discussion as guidance.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends

from wikimind.api.deps import get_current_user_id
from wikimind.database import get_session
from wikimind.models import (
    CompileWithGuidanceResponse,
    DiscussionMessageRequest,
    DiscussionMessageResponse,
    DiscussionThreadResponse,
)
from wikimind.services.factories import get_discussion_service

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from wikimind.services.discussion import DiscussionService

router = APIRouter()


@router.post(
    "/articles/{article_id}/discuss",
    response_model=DiscussionMessageResponse,
    responses={404: {"description": "Article not found"}},
)
async def post_discussion_message(
    article_id: str,
    body: DiscussionMessageRequest,
    session: AsyncSession = Depends(get_session),
    service: DiscussionService = Depends(get_discussion_service),
    user_id: str = Depends(get_current_user_id),
) -> DiscussionMessageResponse:
    """Send a message about an article's sources and get an LLM response."""
    return await service.post_message(article_id, body.message, session, user_id)


@router.get(
    "/articles/{article_id}/discussion",
    response_model=DiscussionThreadResponse,
    responses={404: {"description": "Article not found"}},
)
async def get_discussion_thread(
    article_id: str,
    session: AsyncSession = Depends(get_session),
    service: DiscussionService = Depends(get_discussion_service),
    user_id: str = Depends(get_current_user_id),
) -> DiscussionThreadResponse:
    """Get the full discussion thread for an article."""
    return await service.get_thread(article_id, session, user_id)


@router.post(
    "/articles/{article_id}/compile-with-guidance",
    response_model=CompileWithGuidanceResponse,
    responses={404: {"description": "Article not found"}},
)
async def compile_with_guidance(
    article_id: str,
    session: AsyncSession = Depends(get_session),
    service: DiscussionService = Depends(get_discussion_service),
    user_id: str = Depends(get_current_user_id),
) -> CompileWithGuidanceResponse:
    """Trigger recompilation incorporating the discussion as guidance."""
    return await service.compile_with_guidance(article_id, session, user_id)
