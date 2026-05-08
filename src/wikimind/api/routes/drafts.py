"""Endpoints for managing compilation drafts (issue #418).

When ``compilation.interactive`` is enabled, sources are compiled into
drafts that the user can review, guide, and approve before the article
is saved to the wiki.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends

from wikimind.api.deps import get_current_user_id
from wikimind.database import get_session
from wikimind.models import (
    ApproveDraftRequest,
    ApproveDraftResponse,
    CompilationDraftResponse,
    RejectDraftResponse,
)
from wikimind.services.draft import DraftService, get_draft_service

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter()


@router.get(
    "/sources/{source_id}/draft",
    response_model=CompilationDraftResponse,
    responses={404: {"description": "No pending draft for this source"}},
)
async def get_draft(
    source_id: str,
    session: AsyncSession = Depends(get_session),
    service: DraftService = Depends(get_draft_service),
    user_id: str = Depends(get_current_user_id),
) -> CompilationDraftResponse:
    """Get the pending compilation draft for a source."""
    draft = await service.get_draft_for_source(source_id, session, user_id)
    return service.to_response(draft)


@router.post(
    "/sources/{source_id}/draft/approve",
    response_model=ApproveDraftResponse,
    responses={404: {"description": "No pending draft for this source"}},
)
async def approve_draft(
    source_id: str,
    body: ApproveDraftRequest | None = None,
    session: AsyncSession = Depends(get_session),
    service: DraftService = Depends(get_draft_service),
    user_id: str = Depends(get_current_user_id),
) -> ApproveDraftResponse:
    """Approve a compilation draft, optionally with focus guidance.

    When ``guidance`` is provided, the source is re-compiled with the
    user's direction. Otherwise the original draft is saved as-is.
    """
    guidance = body.guidance if body else None
    return await service.approve_draft(source_id, session, user_id, guidance)


@router.post(
    "/sources/{source_id}/draft/reject",
    response_model=RejectDraftResponse,
    responses={404: {"description": "No pending draft for this source"}},
)
async def reject_draft(
    source_id: str,
    session: AsyncSession = Depends(get_session),
    service: DraftService = Depends(get_draft_service),
    user_id: str = Depends(get_current_user_id),
) -> RejectDraftResponse:
    """Reject a compilation draft and reset the source to pending."""
    return await service.reject_draft(source_id, session, user_id)
