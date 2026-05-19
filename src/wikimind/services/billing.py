"""Lemon Squeezy billing service — checkout, portal, subscription management.

Provides an HTTP client for the Lemon Squeezy API v1 and business logic
for managing subscriptions. Only active when ``deployment_mode == "hosted"``.
"""

import hashlib
import hmac
from datetime import UTC, datetime

import httpx
import structlog
from sqlalchemy import func
from sqlmodel import select, text
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.config import get_settings
from wikimind.models import (
    Article,
    Plan,
    ShareLink,
    Source,
    StorageUsage,
    User,
)

log = structlog.get_logger()

LS_API_BASE = "https://api.lemonsqueezy.com/v1"


class LemonSqueezyClient:
    """HTTP client for Lemon Squeezy API v1."""

    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.billing.lemon_squeezy_api_key
        self._store_id = settings.billing.lemon_squeezy_store_id

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/vnd.api+json",
            "Content-Type": "application/vnd.api+json",
        }

    async def create_checkout(self, variant_id: str, user_id: str, email: str) -> str:
        """Create a checkout session and return the checkout URL."""
        payload = {
            "data": {
                "type": "checkouts",
                "attributes": {
                    "checkout_data": {
                        "email": email,
                        "custom": {"user_id": user_id},
                    },
                },
                "relationships": {
                    "store": {"data": {"type": "stores", "id": self._store_id}},
                    "variant": {"data": {"type": "variants", "id": variant_id}},
                },
            }
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{LS_API_BASE}/checkouts",
                json=payload,
                headers=self._headers(),
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["data"]["attributes"]["url"]

    async def get_subscription(self, subscription_id: str) -> dict:
        """Fetch subscription details from Lemon Squeezy."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{LS_API_BASE}/subscriptions/{subscription_id}",
                headers=self._headers(),
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()["data"]

    async def cancel_subscription(self, subscription_id: str) -> None:
        """Cancel a subscription via Lemon Squeezy API."""
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{LS_API_BASE}/subscriptions/{subscription_id}",
                headers=self._headers(),
                timeout=30,
            )
            resp.raise_for_status()


def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify HMAC-SHA256 webhook signature from Lemon Squeezy."""
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


async def apply_entitlement(
    session: AsyncSession,
    user: User,
    ls_status: str,
    plan_name: str,
    period_end: datetime | None = None,
) -> None:
    """Map Lemon Squeezy subscription state to local plan entitlement.

    Single source of truth shared by webhook handler and reconciliation job.
    """
    plan_result = await session.exec(select(Plan).where(Plan.name == plan_name))
    plan = plan_result.one_or_none()
    if not plan:
        log.warning("Unknown plan name in entitlement", plan_name=plan_name)
        return

    default_result = await session.exec(select(Plan).where(Plan.is_default == True))  # noqa: E712
    default_plan = default_result.one()

    if ls_status in ("active", "on_trial", "past_due"):
        user.plan_id = plan.id
        user.plan_effective_until = None  # Active — no expiry
    elif ls_status in ("cancelled", "paused"):
        user.plan_id = plan.id
        user.plan_effective_until = period_end  # Keep Pro until period ends
    elif ls_status in ("expired", "unpaid"):
        user.plan_id = default_plan.id
        user.plan_effective_until = None  # Immediate downgrade
    else:
        log.warning("Unknown LS subscription status", status=ls_status)

    session.add(user)


async def get_usage_stats(session: AsyncSession, user_id: str) -> dict:
    """Get current resource usage for the user's billing dashboard."""
    today = datetime.now(tz=UTC).date()

    source_count = (await session.exec(select(func.count()).where(Source.user_id == user_id))).one()

    article_count = (await session.exec(select(func.count()).where(Article.user_id == user_id))).one()

    # Storage usage
    storage_result = await session.exec(select(StorageUsage).where(StorageUsage.user_id == user_id))
    storage = storage_result.one_or_none()
    storage_bytes = storage.total_bytes if storage else 0

    # Today's query count
    qc_result = await session.execute(
        text("SELECT count FROM query_count WHERE user_id = :uid AND date = :d"),
        {"uid": user_id, "d": today},
    )
    queries_today = qc_result.scalar() or 0

    # Active share links
    share_count = (
        await session.exec(
            select(func.count()).where(
                ShareLink.user_id == user_id,
                ShareLink.revoked == False,  # noqa: E712
            )
        )
    ).one()

    # Today's LLM spend
    spend_result = await session.execute(
        text("SELECT COALESCE(SUM(cost_usd), 0) FROM costlog WHERE user_id = :uid AND DATE(created_at) = :d"),
        {"uid": user_id, "d": today},
    )
    llm_spend_cents = int((spend_result.scalar() or 0.0) * 100)

    return {
        "sources": source_count,
        "articles": article_count,
        "storage_bytes": storage_bytes,
        "queries_today": queries_today,
        "active_shares": share_count,
        "llm_spend_cents_today": llm_spend_cents,
    }
