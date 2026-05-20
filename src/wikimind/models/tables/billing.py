"""Billing tables — plans, subscriptions, webhooks, and usage tracking."""

import datetime as dt
import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, Column
from sqlmodel import Field, SQLModel

from wikimind._datetime import utcnow_naive


class Plan(SQLModel, table=True):
    """Billing plan with limits and pricing."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str = Field(unique=True)
    display_name: str
    price_cents: int
    billing_interval: str | None = None
    max_sources: int | None = None
    max_articles: int | None = None
    max_queries_per_day: int | None = None
    max_storage_bytes: int | None = Field(default=None, sa_column=Column(BigInteger, nullable=True))
    max_active_shares: int | None = None
    daily_llm_spend_cap_cents: int | None = None
    allowed_exports: list[str] = Field(sa_column=Column(JSON, nullable=False))
    mcp_enabled: bool = False
    llm_provider: str = "openai_compatible"
    llm_model: str = "gpt-4o-mini"
    byok_allowed: bool = False
    is_default: bool = False
    is_active: bool = True
    sort_order: int = 0
    lemon_squeezy_variant_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)


class Subscription(SQLModel, table=True):
    """User subscription to a billing plan via Lemon Squeezy."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(index=True)
    plan_id: str
    lemon_squeezy_subscription_id: str = Field(unique=True)
    lemon_squeezy_customer_id: str
    status: str = "active"
    cancel_at_period_end: bool = False
    current_period_start: datetime
    current_period_end: datetime
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)


class WebhookEvent(SQLModel, table=True):
    """Processed Lemon Squeezy webhook events for idempotency."""

    __tablename__ = "webhook_event"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    lemon_squeezy_event_id: str = Field(unique=True)
    event_type: str
    processed_at: datetime
    payload_hash: str


class StorageUsage(SQLModel, table=True):
    """Precomputed storage usage per user for fast quota checks."""

    __tablename__ = "storage_usage"

    user_id: str = Field(primary_key=True)
    total_bytes: int = 0
    updated_at: datetime = Field(default_factory=utcnow_naive)


class QueryCount(SQLModel, table=True):
    """Daily query count per user for quota enforcement."""

    __tablename__ = "query_count"

    user_id: str = Field(primary_key=True)
    date: dt.date = Field(primary_key=True)
    count: int = 0
