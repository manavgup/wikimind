"""Administrative endpoints — system diagnostics and maintenance triggers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends

from wikimind.api.deps import get_current_user_id
from wikimind.database import get_session
from wikimind.services.admin import AdminService, get_admin_service

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter()


@router.get("/stats")
async def get_stats(
    session: AsyncSession = Depends(get_session),
    service: AdminService = Depends(get_admin_service),
    user_id: str = Depends(get_current_user_id),
):
    """Aggregate system statistics."""
    return await service.get_stats(session, user_id=user_id)


@router.get("/orphans")
async def get_orphans(
    session: AsyncSession = Depends(get_session),
    service: AdminService = Depends(get_admin_service),
    user_id: str = Depends(get_current_user_id),
):
    """Articles with missing wiki files."""
    return await service.get_orphan_articles(session, user_id=user_id)


@router.get("/concepts/eligible")
async def get_eligible_concepts(
    session: AsyncSession = Depends(get_session),
    service: AdminService = Depends(get_admin_service),
    user_id: str = Depends(get_current_user_id),
):
    """Concepts eligible for page generation."""
    return await service.get_eligible_concepts(session, user_id=user_id)


@router.get("/stuck-sources")
async def get_stuck_sources(
    session: AsyncSession = Depends(get_session),
    service: AdminService = Depends(get_admin_service),
    user_id: str = Depends(get_current_user_id),
):
    """Sources stuck in processing for >10 minutes."""
    return await service.get_stuck_sources(session, user_id=user_id)


@router.post("/retry-stuck/{source_id}")
async def retry_stuck_source(
    source_id: str,
    session: AsyncSession = Depends(get_session),
    service: AdminService = Depends(get_admin_service),
    user_id: str = Depends(get_current_user_id),
):
    """Reset a stuck source to pending and re-queue compilation."""
    return await service.retry_stuck_source(session, source_id=source_id, user_id=user_id)


@router.post("/sweep")
async def trigger_sweep(
    service: AdminService = Depends(get_admin_service),
    user_id: str = Depends(get_current_user_id),
):
    """Trigger wikilink sweep manually."""
    return await service.trigger_sweep(user_id=user_id)


@router.post("/reindex")
async def trigger_reindex(
    service: AdminService = Depends(get_admin_service),
):
    """Rebuild search index."""
    return await service.trigger_reindex()
