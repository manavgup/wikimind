"""Tests for billing data models (Plan, Subscription, WebhookEvent, StorageUsage, QueryCount)."""

from datetime import date

from wikimind._datetime import utcnow_naive
from wikimind.models import Plan, QueryCount, StorageUsage, Subscription, WebhookEvent


def test_plan_model_fields():
    now = utcnow_naive()
    plan = Plan(
        id="plan-1",
        name="free",
        display_name="Free",
        price_cents=0,
        billing_interval=None,
        max_sources=20,
        max_articles=30,
        max_queries_per_day=10,
        max_storage_bytes=25 * 1024 * 1024,
        max_active_shares=3,
        daily_llm_spend_cap_cents=50,
        allowed_exports=["markdown"],
        mcp_enabled=False,
        llm_provider="openai_compatible",
        llm_model="gpt-4o-mini",
        byok_allowed=False,
        is_default=True,
        is_active=True,
        sort_order=0,
        lemon_squeezy_variant_id=None,
        created_at=now,
        updated_at=now,
    )
    assert plan.price_cents == 0
    assert plan.allowed_exports == ["markdown"]
    assert plan.byok_allowed is False
    assert plan.is_default is True
    assert plan.max_sources == 20
    assert plan.billing_interval is None


def test_plan_defaults():
    plan = Plan(
        name="test",
        display_name="Test",
        price_cents=0,
        allowed_exports=["markdown"],
    )
    assert plan.id  # UUID auto-generated
    assert plan.mcp_enabled is False
    assert plan.llm_provider == "openai_compatible"
    assert plan.llm_model == "gpt-4o-mini"
    assert plan.byok_allowed is False
    assert plan.is_default is False
    assert plan.is_active is True
    assert plan.sort_order == 0
    assert plan.lemon_squeezy_variant_id is None
    assert plan.max_sources is None
    assert plan.created_at is not None
    assert plan.updated_at is not None


def test_subscription_model_fields():
    now = utcnow_naive()
    sub = Subscription(
        id="sub-1",
        user_id="user-1",
        plan_id="plan-pro",
        lemon_squeezy_subscription_id="ls-sub-123",
        lemon_squeezy_customer_id="ls-cust-456",
        status="active",
        cancel_at_period_end=False,
        current_period_start=now,
        current_period_end=now,
        created_at=now,
        updated_at=now,
    )
    assert sub.status == "active"
    assert sub.cancel_at_period_end is False
    assert sub.user_id == "user-1"
    assert sub.lemon_squeezy_subscription_id == "ls-sub-123"


def test_subscription_defaults():
    now = utcnow_naive()
    sub = Subscription(
        user_id="user-1",
        plan_id="plan-pro",
        lemon_squeezy_subscription_id="ls-sub-999",
        lemon_squeezy_customer_id="ls-cust-999",
        current_period_start=now,
        current_period_end=now,
    )
    assert sub.id  # UUID auto-generated
    assert sub.status == "active"
    assert sub.cancel_at_period_end is False
    assert sub.created_at is not None
    assert sub.updated_at is not None


def test_webhook_event_model():
    now = utcnow_naive()
    evt = WebhookEvent(
        id="evt-1",
        lemon_squeezy_event_id="ls-evt-789",
        event_type="subscription_created",
        processed_at=now,
        payload_hash="abc123",
    )
    assert evt.event_type == "subscription_created"
    assert evt.lemon_squeezy_event_id == "ls-evt-789"
    assert evt.payload_hash == "abc123"


def test_webhook_event_defaults():
    now = utcnow_naive()
    evt = WebhookEvent(
        lemon_squeezy_event_id="ls-evt-auto",
        event_type="subscription_updated",
        processed_at=now,
        payload_hash="def456",
    )
    assert evt.id  # UUID auto-generated


def test_storage_usage_model():
    now = utcnow_naive()
    su = StorageUsage(
        user_id="user-1",
        total_bytes=1024,
        updated_at=now,
    )
    assert su.total_bytes == 1024
    assert su.user_id == "user-1"


def test_storage_usage_defaults():
    su = StorageUsage(user_id="user-1")
    assert su.total_bytes == 0
    assert su.updated_at is not None


def test_query_count_model():
    today = date.today()
    qc = QueryCount(
        user_id="user-1",
        date=today,
        count=5,
    )
    assert qc.count == 5
    assert qc.user_id == "user-1"
    assert qc.date == today


def test_query_count_defaults():
    today = date.today()
    qc = QueryCount(user_id="user-1", date=today)
    assert qc.count == 0


def test_user_billing_fields():
    from wikimind.models import User

    now = utcnow_naive()
    user = User(
        email="test@example.com",
        auth_provider="google",
        auth_provider_id="google-123",
        plan_id="plan-free",
        plan_effective_until=now,
        lemon_squeezy_customer_id="ls-cust-100",
    )
    assert user.plan_id == "plan-free"
    assert user.plan_effective_until == now
    assert user.lemon_squeezy_customer_id == "ls-cust-100"


def test_user_billing_fields_default_to_none():
    from wikimind.models import User

    user = User(
        email="test2@example.com",
        auth_provider="github",
        auth_provider_id="github-456",
    )
    assert user.plan_id is None
    assert user.plan_effective_until is None
    assert user.lemon_squeezy_customer_id is None
