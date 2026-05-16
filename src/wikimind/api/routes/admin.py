"""Administrative endpoints — system diagnostics and maintenance triggers."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlmodel import select

from wikimind.api.deps import require_admin
from wikimind.config import get_settings
from wikimind.database import get_session
from wikimind.models import LLMTrace, LLMTraceListResponse, LLMTraceResponse
from wikimind.services.admin import AdminService, get_admin_service

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

log = structlog.get_logger()

router = APIRouter()


class DoclingStatusResponse(BaseModel):
    """Response model for Docling sidecar health check."""

    status: str  # "connected" | "disconnected"
    url: str
    latency_ms: float | None = None


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


@router.get("/traces", response_model=LLMTraceListResponse)
async def get_traces(
    session: AsyncSession = Depends(get_session),
    _admin_user_id: str = Depends(require_admin),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Paginated LLM traces (most recent first, admin only)."""
    count_result = await session.execute(select(func.count()).select_from(LLMTrace))
    total = count_result.scalar() or 0

    result = await session.exec(
        select(LLMTrace)
        .order_by(LLMTrace.created_at.desc())  # type: ignore[attr-defined]
        .offset(offset)
        .limit(limit)
    )
    traces = list(result.all())

    return LLMTraceListResponse(
        items=[
            LLMTraceResponse(
                id=t.id,
                user_id=t.user_id,
                model=t.model,
                prompt_tokens=t.prompt_tokens,
                completion_tokens=t.completion_tokens,
                total_tokens=t.total_tokens,
                latency_ms=t.latency_ms,
                created_at=t.created_at,
                prompt_text=t.prompt_text,
                completion_text=t.completion_text,
                source_id=t.source_id,
                operation=t.operation,
            )
            for t in traces
        ],
        total=total,
    )
