"""Administrative endpoints — system diagnostics and maintenance triggers."""

from __future__ import annotations

import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import select

from wikimind.api.deps import require_admin
from wikimind.config import get_settings
from wikimind.database import get_session
from wikimind.models import (
    AdminActionResult,
    AdminUserDetail,
    AdminUserSummary,
    EligibleConcept,
    LLMTrace,
    LLMTraceListResponse,
    LLMTraceResponse,
    OrphanArticle,
    Plan,
    StuckSource,
    Subscription,
    SystemStats,
    User,
    WebhookEvent,
)
from wikimind.services.admin import AdminService  # noqa: TC001 — needed at runtime for Depends()
from wikimind.services.billing import LemonSqueezyClient, apply_entitlement
from wikimind.services.factories import get_admin_service

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
) -> SystemStats:
    """Aggregate system-wide statistics (admin only)."""
    return await service.get_stats(session)


@router.get("/orphans")
async def get_orphans(
    session: AsyncSession = Depends(get_session),
    service: AdminService = Depends(get_admin_service),
    _admin_user_id: str = Depends(require_admin),
) -> list[OrphanArticle]:
    """Articles with missing wiki files."""
    return await service.get_orphan_articles(session)


@router.get("/concepts/eligible")
async def get_eligible_concepts(
    session: AsyncSession = Depends(get_session),
    service: AdminService = Depends(get_admin_service),
    _admin_user_id: str = Depends(require_admin),
) -> list[EligibleConcept]:
    """Concepts eligible for page generation."""
    return await service.get_eligible_concepts(session)


@router.get("/stuck-sources")
async def get_stuck_sources(
    session: AsyncSession = Depends(get_session),
    service: AdminService = Depends(get_admin_service),
    _admin_user_id: str = Depends(require_admin),
) -> list[StuckSource]:
    """Sources stuck in processing for >10 minutes."""
    return await service.get_stuck_sources(session)


@router.post("/retry-stuck/{source_id}")
async def retry_stuck_source(
    source_id: str,
    session: AsyncSession = Depends(get_session),
    service: AdminService = Depends(get_admin_service),
    admin_user_id: str = Depends(require_admin),
) -> AdminActionResult:
    """Reset a stuck source to pending and re-queue compilation."""
    return await service.retry_stuck_source(session, source_id=source_id, user_id=admin_user_id)


@router.post("/sweep")
async def trigger_sweep(
    service: AdminService = Depends(get_admin_service),
    admin_user_id: str = Depends(require_admin),
) -> AdminActionResult:
    """Trigger wikilink sweep manually."""
    return await service.trigger_sweep(user_id=admin_user_id)


@router.post("/reindex")
async def trigger_reindex(
    service: AdminService = Depends(get_admin_service),
    _admin_user_id: str = Depends(require_admin),
) -> AdminActionResult:
    """Rebuild search index."""
    return await service.trigger_reindex()


@router.get("/docling-status", response_model=DoclingStatusResponse)
async def get_docling_status(
    _admin_user_id: str = Depends(require_admin),
) -> DoclingStatusResponse:
    """Check connectivity to the Docling-serve PDF extraction sidecar."""
    settings = get_settings()
    url = settings.docling_serve_url

    if not url:
        return DoclingStatusResponse(status="disconnected", url="(not configured)")

    try:
        start = time.monotonic()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{url}/health")
            resp.raise_for_status()
        latency = round((time.monotonic() - start) * 1000, 1)
        return DoclingStatusResponse(status="connected", url=url, latency_ms=latency)
    except (httpx.HTTPError, OSError) as exc:
        log.warning("docling-status: sidecar unreachable", url=url, error=str(exc))
        return DoclingStatusResponse(status="disconnected", url=url)


@router.get("/users", response_model=list[AdminUserSummary])
async def list_users(
    session: AsyncSession = Depends(get_session),
    service: AdminService = Depends(get_admin_service),
    _admin_user_id: str = Depends(require_admin),
) -> list[AdminUserSummary]:
    """List all users with summary metrics (admin only)."""
    return await service.list_users(session)


@router.get("/users/{user_id}", response_model=AdminUserDetail)
async def get_user_detail(
    user_id: str,
    session: AsyncSession = Depends(get_session),
    service: AdminService = Depends(get_admin_service),
    _admin_user_id: str = Depends(require_admin),
) -> AdminUserDetail:
    """Full stats breakdown for a single user (admin only)."""
    detail = await service.get_user_detail(session, user_id=user_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="User not found")
    return detail


@router.get("/traces", response_model=LLMTraceListResponse)
async def get_traces(
    session: AsyncSession = Depends(get_session),
    _admin_user_id: str = Depends(require_admin),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> LLMTraceListResponse:
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


@router.get("/billing/subscriptions")
async def admin_list_subscriptions(
    session: AsyncSession = Depends(get_session),
    _admin: str = Depends(require_admin),
) -> list[dict[str, Any]]:
    """List all subscriptions with user info (admin only)."""
    result = await session.exec(
        select(Subscription, User.email)
        .join(User, User.id == Subscription.user_id)  # type: ignore[arg-type]
        .order_by(Subscription.created_at.desc())  # type: ignore[attr-defined]
    )
    rows = result.all()
    return [
        {
            "id": sub.id,
            "user_id": sub.user_id,
            "user_email": email,
            "plan_id": sub.plan_id,
            "status": sub.status,
            "lemon_squeezy_subscription_id": sub.lemon_squeezy_subscription_id,
            "cancel_at_period_end": sub.cancel_at_period_end,
            "created_at": sub.created_at.isoformat(),
        }
        for sub, email in rows
    ]


@router.get("/billing/subscriptions/{user_id}")
async def admin_get_user_subscription(
    user_id: str,
    session: AsyncSession = Depends(get_session),
    _admin: str = Depends(require_admin),
) -> list[dict[str, Any]]:
    """Get subscription details for a specific user (admin only)."""
    result = await session.exec(select(Subscription).where(Subscription.user_id == user_id))
    subs = result.all()
    if not subs:
        raise HTTPException(status_code=404, detail="No subscriptions found for user")
    return [
        {
            "id": sub.id,
            "plan_id": sub.plan_id,
            "status": sub.status,
            "lemon_squeezy_subscription_id": sub.lemon_squeezy_subscription_id,
            "cancel_at_period_end": sub.cancel_at_period_end,
            "current_period_start": sub.current_period_start.isoformat() if sub.current_period_start else None,
            "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
            "created_at": sub.created_at.isoformat(),
        }
        for sub in subs
    ]


@router.post("/billing/subscriptions/{user_id}/override")
async def admin_override_plan(
    user_id: str,
    plan_name: str,
    session: AsyncSession = Depends(get_session),
    _admin: str = Depends(require_admin),
) -> dict[str, str]:
    """Override a user's plan (admin only). Used for manual fixes."""
    plan_result = await session.exec(select(Plan).where(Plan.name == plan_name))
    plan = plan_result.one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail=f"Plan '{plan_name}' not found")

    user_result = await session.exec(select(User).where(User.id == user_id))
    user = user_result.one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.plan_id = plan.id
    user.plan_effective_until = None  # Clear any grace period
    session.add(user)
    await session.commit()
    return {"status": "ok", "user_id": user_id, "plan_name": plan_name}


@router.post("/billing/subscriptions/{user_id}/sync")
async def admin_sync_subscription(
    user_id: str,
    session: AsyncSession = Depends(get_session),
    _admin: str = Depends(require_admin),
) -> dict[str, str]:
    """Force-sync a user's subscription with Lemon Squeezy (admin only)."""
    sub_result = await session.exec(
        select(Subscription).where(
            Subscription.user_id == user_id,
            Subscription.status.in_(["active", "cancelled", "past_due"]),  # type: ignore[attr-defined]
        )
    )
    sub = sub_result.one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="No active subscription to sync")

    client = LemonSqueezyClient()
    data = await client.get_subscription(sub.lemon_squeezy_subscription_id)
    attrs = data["attributes"]
    ls_status = attrs["status"]

    user_result = await session.exec(select(User).where(User.id == user_id))
    user = user_result.one()

    variant_id = str(attrs.get("variant_id", ""))
    plan_result = await session.exec(select(Plan).where(Plan.lemon_squeezy_variant_id == variant_id))
    plan = plan_result.one_or_none()
    plan_name = plan.name if plan else "pro"

    sub.status = ls_status
    session.add(sub)

    ends_at = attrs.get("ends_at")
    period_end = datetime.fromisoformat(ends_at) if ends_at else None
    await apply_entitlement(session, user, ls_status, plan_name, period_end)
    await session.commit()

    return {"status": "synced", "ls_status": ls_status, "plan_name": plan_name}


@router.get("/billing/webhook-events")
async def admin_list_webhook_events(
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    _admin: str = Depends(require_admin),
) -> list[dict[str, Any]]:
    """List recent webhook events (admin only)."""
    result = await session.exec(
        select(WebhookEvent).order_by(WebhookEvent.processed_at.desc()).limit(limit)  # type: ignore[attr-defined]
    )
    events = result.all()
    return [
        {
            "id": evt.id,
            "event_type": evt.event_type,
            "lemon_squeezy_event_id": evt.lemon_squeezy_event_id,
            "processed_at": evt.processed_at.isoformat(),
            "payload_hash": evt.payload_hash,
        }
        for evt in events
    ]
