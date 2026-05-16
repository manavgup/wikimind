"""Administrative endpoints — system diagnostics and maintenance triggers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends

from wikimind.api.deps import require_admin
from wikimind.database import get_session
from wikimind.services.factories import get_admin_service

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from wikimind.services.admin import AdminService

router = APIRouter()


@router.get("/stats")
async def get_stats(
    session: AsyncSession = Depends(get_session),
    service: AdminService = Depends(get_admin_service),
    _admin_user_id: str = Depends(require_admin),
):
    """Aggregate system-wide statistics (admin only)."""
    return await service.get_stats(session)


@router.get("/orphans")
async def get_orphans(
    session: AsyncSession = Depends(get_session),
    service: AdminService = Depends(get_admin_service),
    _admin_user_id: str = Depends(require_admin),
):
    """Articles with missing wiki files."""
    return await service.get_orphan_articles(session)


@router.get("/concepts/eligible")
async def get_eligible_concepts(
    session: AsyncSession = Depends(get_session),
    service: AdminService = Depends(get_admin_service),
    _admin_user_id: str = Depends(require_admin),
):
    """Concepts eligible for page generation."""
    return await service.get_eligible_concepts(session)


@router.get("/stuck-sources")
async def get_stuck_sources(
    session: AsyncSession = Depends(get_session),
    service: AdminService = Depends(get_admin_service),
    _admin_user_id: str = Depends(require_admin),
):
    """Sources stuck in processing for >10 minutes."""
    return await service.get_stuck_sources(session)


@router.post("/retry-stuck/{source_id}")
async def retry_stuck_source(
    source_id: str,
    session: AsyncSession = Depends(get_session),
    service: AdminService = Depends(get_admin_service),
    admin_user_id: str = Depends(require_admin),
):
    """Reset a stuck source to pending and re-queue compilation."""
    return await service.retry_stuck_source(session, source_id=source_id, user_id=admin_user_id)


@router.post("/sweep")
async def trigger_sweep(
    service: AdminService = Depends(get_admin_service),
    admin_user_id: str = Depends(require_admin),
):
    """Trigger wikilink sweep manually."""
    return await service.trigger_sweep(user_id=admin_user_id)


@router.post("/reindex")
async def trigger_reindex(
    service: AdminService = Depends(get_admin_service),
    _admin_user_id: str = Depends(require_admin),
):
    """Rebuild search index."""
    return await service.trigger_reindex()
