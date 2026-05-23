"""Billing endpoints — plans, usage, checkout, portal, and webhook."""

import hashlib
import json
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind._datetime import utcnow_naive
from wikimind.api.deps import get_current_user_id, require_plan
from wikimind.config import get_settings
from wikimind.database import get_session
from wikimind.models import Plan, Subscription, User, WebhookEvent
from wikimind.services.billing import (
    LemonSqueezyClient,
    apply_entitlement,
    get_usage_stats,
    handle_product_updated,
    handle_variant_updated,
    verify_webhook_signature,
)

log = structlog.get_logger()

router = APIRouter()


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------


class CheckoutRequest(BaseModel):
    """Request body for creating a checkout session."""

    plan_id: str


class CheckoutResponse(BaseModel):
    """Checkout URL response."""

    checkout_url: str


class PortalResponse(BaseModel):
    """Customer portal URL response."""

    portal_url: str


class UsageResponse(BaseModel):
    """Current resource usage vs plan limits."""

    plan_name: str
    plan_display_name: str
    sources: int
    sources_limit: int | None
    articles: int
    articles_limit: int | None
    storage_bytes: int
    storage_limit: int | None
    queries_today: int
    queries_limit: int | None
    active_shares: int
    shares_limit: int | None
    llm_spend_cents_today: int
    llm_spend_limit: int | None


class PlanResponse(BaseModel):
    """Public billing plan details."""

    id: str
    name: str
    display_name: str
    price_cents: int
    billing_interval: str | None
    max_sources: int | None
    max_articles: int | None
    max_queries_per_day: int | None
    max_storage_bytes: int | None
    max_active_shares: int | None
    allowed_exports: list[str]
    mcp_enabled: bool
    byok_allowed: bool
    sort_order: int


# ---------------------------------------------------------------------------
# Public endpoint — no auth required
# ---------------------------------------------------------------------------


@router.get("/plans", response_model=list[PlanResponse])
async def list_plans(
    session: AsyncSession = Depends(get_session),
) -> list[PlanResponse]:
    """List all active billing plans (public, no auth required)."""
    result = await session.exec(
        select(Plan).where(Plan.is_active == True).order_by(Plan.sort_order)  # type: ignore[arg-type]  # noqa: E712
    )
    plans = result.all()
    return [
        PlanResponse(
            id=p.id,
            name=p.name,
            display_name=p.display_name,
            price_cents=p.price_cents,
            billing_interval=p.billing_interval,
            max_sources=p.max_sources,
            max_articles=p.max_articles,
            max_queries_per_day=p.max_queries_per_day,
            max_storage_bytes=p.max_storage_bytes,
            max_active_shares=p.max_active_shares,
            allowed_exports=p.allowed_exports,
            mcp_enabled=p.mcp_enabled,
            byok_allowed=p.byok_allowed,
            sort_order=p.sort_order,
        )
        for p in plans
    ]


@router.get("/usage", response_model=UsageResponse)
async def get_usage(
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
    plan: Plan | None = Depends(require_plan),
) -> UsageResponse:
    """Get current resource usage vs plan limits."""
    if not plan:
        raise HTTPException(status_code=404, detail="Billing not enabled")

    usage = await get_usage_stats(session, user_id)
    return UsageResponse(
        plan_name=plan.name,
        plan_display_name=plan.display_name,
        sources=usage["sources"],
        sources_limit=plan.max_sources,
        articles=usage["articles"],
        articles_limit=plan.max_articles,
        storage_bytes=usage["storage_bytes"],
        storage_limit=plan.max_storage_bytes,
        queries_today=usage["queries_today"],
        queries_limit=plan.max_queries_per_day,
        active_shares=usage["active_shares"],
        shares_limit=plan.max_active_shares,
        llm_spend_cents_today=usage["llm_spend_cents_today"],
        llm_spend_limit=plan.daily_llm_spend_cap_cents,
    )


@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout(
    body: CheckoutRequest,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
) -> CheckoutResponse:
    """Create a Lemon Squeezy checkout session for plan upgrade."""
    result = await session.exec(select(Plan).where(Plan.id == body.plan_id))
    plan = result.one_or_none()
    if not plan or not plan.lemon_squeezy_variant_id:
        raise HTTPException(status_code=404, detail="Plan not found or not purchasable")

    user_result = await session.exec(select(User).where(User.id == user_id))
    user = user_result.one()

    client = LemonSqueezyClient()
    checkout_url = await client.create_checkout(
        variant_id=plan.lemon_squeezy_variant_id,
        user_id=user_id,
        email=user.email,
    )
    return CheckoutResponse(checkout_url=checkout_url)


@router.get("/portal", response_model=PortalResponse)
async def get_portal(
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
) -> PortalResponse:
    """Get Lemon Squeezy customer portal URL for subscription management."""
    result = await session.exec(
        select(Subscription).where(
            Subscription.user_id == user_id,
            Subscription.status == "active",
        )
    )
    sub = result.one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="No active subscription")

    client = LemonSqueezyClient()
    data = await client.get_subscription(sub.lemon_squeezy_subscription_id)
    portal_url = data["attributes"]["urls"]["customer_portal"]
    return PortalResponse(portal_url=portal_url)


# ---------------------------------------------------------------------------
# Webhook — no auth, signature-verified
# ---------------------------------------------------------------------------


@router.post("/webhook")
async def handle_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Process Lemon Squeezy webhook with insert-first idempotency."""
    settings = get_settings()
    body = await request.body()

    # Verify HMAC signature
    signature = request.headers.get("x-signature", "")
    if not verify_webhook_signature(body, signature, settings.billing.lemon_squeezy_webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload = json.loads(body)
    event_type = payload.get("meta", {}).get("event_name", "")
    event_id = payload.get("meta", {}).get("webhook_id", "")

    if not event_id:
        raise HTTPException(status_code=400, detail="Missing webhook_id")

    # Insert-first idempotency: skip if duplicate
    payload_hash = hashlib.sha256(body).hexdigest()
    existing = await session.exec(select(WebhookEvent).where(WebhookEvent.lemon_squeezy_event_id == event_id))
    if existing.one_or_none():
        log.info("Duplicate webhook event, skipping", event_id=event_id)
        return JSONResponse({"status": "duplicate"})

    event = WebhookEvent(
        lemon_squeezy_event_id=event_id,
        event_type=event_type,
        processed_at=utcnow_naive(),
        payload_hash=payload_hash,
    )
    session.add(event)

    await _process_webhook_event(session, event_type, payload)
    await session.commit()

    return JSONResponse({"status": "ok"})


async def _resolve_user(
    session: AsyncSession,
    attrs: dict,
    custom_data: dict,
    event_type: str,
) -> "User | None":
    """Resolve the User for a webhook event, returning None if not found."""
    user_id = custom_data.get("user_id")

    if not user_id:
        customer_id = str(attrs.get("customer_id", ""))
        if customer_id:
            result = await session.exec(select(User).where(User.lemon_squeezy_customer_id == customer_id))
            found = result.one_or_none()
            if found:
                user_id = found.id

    if not user_id:
        log.warning("Webhook event without user_id", event_type=event_type)
        return None

    user_result = await session.exec(select(User).where(User.id == user_id))
    user = user_result.one_or_none()
    if not user:
        log.warning("Webhook event for unknown user", user_id=user_id)
    return user


async def _handle_subscription_active(
    session: AsyncSession,
    user: User,
    attrs: dict,
    payload: dict,
    plan: Plan | None,
    plan_name: str,
) -> None:
    """Handle subscription_created / subscription_updated / subscription_resumed."""
    ls_sub_id = str(attrs.get("first_subscription_item", {}).get("subscription_id", ""))
    if not ls_sub_id:
        ls_sub_id = str(payload.get("data", {}).get("id", ""))
    status = attrs.get("status", "")
    customer_id = str(attrs.get("customer_id", ""))

    sub_result = await session.exec(select(Subscription).where(Subscription.lemon_squeezy_subscription_id == ls_sub_id))
    sub = sub_result.one_or_none()
    if not sub:
        sub = Subscription(
            user_id=user.id,
            plan_id=plan.id if plan else "",
            lemon_squeezy_subscription_id=ls_sub_id,
            lemon_squeezy_customer_id=customer_id,
            current_period_start=utcnow_naive(),
            current_period_end=utcnow_naive(),
        )
    sub.status = status
    session.add(sub)
    await apply_entitlement(session, user, status, plan_name)


async def _handle_subscription_cancelled(
    session: AsyncSession,
    user: User,
    attrs: dict,
    payload: dict,
    plan_name: str,
) -> None:
    """Handle subscription_cancelled."""
    ls_sub_id = str(attrs.get("first_subscription_item", {}).get("subscription_id", ""))
    if not ls_sub_id:
        ls_sub_id = str(payload.get("data", {}).get("id", ""))

    sub_result = await session.exec(select(Subscription).where(Subscription.lemon_squeezy_subscription_id == ls_sub_id))
    sub = sub_result.one_or_none()
    if sub:
        sub.status = "cancelled"
        sub.cancel_at_period_end = True
        session.add(sub)

    ends_at_str = attrs.get("ends_at")
    period_end = datetime.fromisoformat(ends_at_str) if ends_at_str else None
    await apply_entitlement(session, user, "cancelled", plan_name, period_end)


async def _handle_subscription_expired(
    session: AsyncSession,
    user: User,
    attrs: dict,
    payload: dict,
    plan_name: str,
) -> None:
    """Handle subscription_expired."""
    ls_sub_id = str(attrs.get("first_subscription_item", {}).get("subscription_id", ""))
    if not ls_sub_id:
        ls_sub_id = str(payload.get("data", {}).get("id", ""))

    sub_result = await session.exec(select(Subscription).where(Subscription.lemon_squeezy_subscription_id == ls_sub_id))
    sub = sub_result.one_or_none()
    if sub:
        sub.status = "expired"
        session.add(sub)
    await apply_entitlement(session, user, "expired", plan_name)


async def _process_webhook_event(
    session: AsyncSession,
    event_type: str,
    payload: dict,
) -> None:
    """Route webhook event to the appropriate handler."""
    # Price-change events are not user-specific — handle them separately.
    if event_type == "variant_updated":
        await handle_variant_updated(session, payload)
        log.info("Processed webhook", event_type=event_type)
        return
    if event_type == "product_updated":
        await handle_product_updated(session, payload)
        log.info("Processed webhook", event_type=event_type)
        return

    attrs = payload.get("data", {}).get("attributes", {})
    custom_data = payload.get("meta", {}).get("custom_data", {})

    user = await _resolve_user(session, attrs, custom_data, event_type)
    if not user:
        return

    customer_id = str(attrs.get("customer_id", ""))
    if customer_id and not user.lemon_squeezy_customer_id:
        user.lemon_squeezy_customer_id = customer_id

    variant_id = str(attrs.get("variant_id", ""))
    plan_result = await session.exec(select(Plan).where(Plan.lemon_squeezy_variant_id == variant_id))
    plan = plan_result.one_or_none()
    plan_name = plan.name if plan else "pro"

    if event_type in ("subscription_created", "subscription_updated", "subscription_resumed"):
        await _handle_subscription_active(session, user, attrs, payload, plan, plan_name)
    elif event_type == "subscription_cancelled":
        await _handle_subscription_cancelled(session, user, attrs, payload, plan_name)
    elif event_type == "subscription_expired":
        await _handle_subscription_expired(session, user, attrs, payload, plan_name)

    log.info("Processed webhook", event_type=event_type, user_id=user.id)
