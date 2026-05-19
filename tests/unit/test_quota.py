"""Unit tests for the quota enforcement service.

Tests for pure (non-DB) check functions. Advisory-lock and DB-dependent
functions require integration tests with a real PostgreSQL session.
"""

from datetime import UTC, datetime

import pytest

from wikimind.models import Plan

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def free_plan() -> Plan:
    return Plan(
        id="plan-free",
        name="free",
        display_name="Free",
        price_cents=0,
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
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.fixture
def pro_plan() -> Plan:
    return Plan(
        id="plan-pro",
        name="pro",
        display_name="Pro",
        price_cents=1200,
        billing_interval="month",
        max_sources=500,
        max_articles=1000,
        max_queries_per_day=200,
        max_storage_bytes=5 * 1024 * 1024 * 1024,
        max_active_shares=100,
        daily_llm_spend_cap_cents=1000,
        allowed_exports=["markdown", "json", "pdf", "linkedin", "slides", "obsidian"],
        mcp_enabled=True,
        llm_provider="openai_compatible",
        llm_model="gpt-4o",
        byok_allowed=True,
        is_default=False,
        is_active=True,
        sort_order=1,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# QuotaExceededError
# ---------------------------------------------------------------------------


def test_quota_exceeded_error_has_fields():
    from wikimind.services.quota import QuotaExceededError

    err = QuotaExceededError("source", 20, 20)
    assert err.resource == "source"
    assert err.used == 20
    assert err.limit == 20
    assert "source quota exceeded: 20/20" in str(err)


# ---------------------------------------------------------------------------
# check_export_format
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_export_format_allowed(free_plan):
    from wikimind.services.quota import check_export_format

    # Should not raise — markdown is in the free plan
    await check_export_format(free_plan, "markdown")


@pytest.mark.asyncio
async def test_check_export_format_blocked(free_plan):
    from wikimind.services.quota import QuotaExceededError, check_export_format

    with pytest.raises(QuotaExceededError, match="export"):
        await check_export_format(free_plan, "pdf")


@pytest.mark.asyncio
async def test_check_export_format_pro_allows_pdf(pro_plan):
    from wikimind.services.quota import check_export_format

    # Should not raise — pdf is in the pro plan
    await check_export_format(pro_plan, "pdf")


# ---------------------------------------------------------------------------
# check_mcp_access
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_mcp_access_blocked(free_plan):
    from wikimind.services.quota import QuotaExceededError, check_mcp_access

    with pytest.raises(QuotaExceededError, match="mcp"):
        await check_mcp_access(free_plan)


@pytest.mark.asyncio
async def test_check_mcp_access_allowed(pro_plan):
    from wikimind.services.quota import check_mcp_access

    # Should not raise — MCP is enabled on pro plan
    await check_mcp_access(pro_plan)
