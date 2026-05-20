"""Per-resource quota enforcement for billing plans.

Each check function validates a specific resource limit and raises
``QuotaExceededError`` when the user exceeds their plan's allowance.

Race-condition strategy:
- Sources/articles/shares: PostgreSQL advisory locks (``pg_advisory_xact_lock``)
  serialise concurrent creates per user without locking the entire table.
- Queries: Atomic upsert + SELECT FOR UPDATE. The row lock is the serialisation.
- Storage: FOR UPDATE on the single StorageUsage row per user.
- LLM spend: Soft cap checked before the LLM call, not reserved. Concurrent
  calls may slightly overshoot — acceptable for a safety-net cap.
"""

from datetime import UTC, datetime

import structlog
from sqlalchemy import func, update
from sqlmodel import select, text
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind._datetime import utcnow_naive
from wikimind.models import (
    Article,
    Plan,
    ShareLink,
    Source,
    StorageUsage,
    User,
)

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class QuotaExceededError(Exception):
    """Raised when a user exceeds a plan quota for a specific resource."""

    def __init__(self, resource: str, used: int, limit: int) -> None:
        self.resource = resource
        self.used = used
        self.limit = limit
        msg = f"{resource} quota exceeded: {used}/{limit}"
        super().__init__(msg)


# ---------------------------------------------------------------------------
# Plan resolution
# ---------------------------------------------------------------------------


async def get_effective_plan(session: AsyncSession, user_id: str) -> Plan:
    """Resolve the user's current billing plan.

    1. Load user.
    2. If ``user.plan_id`` is set AND (``plan_effective_until`` is None OR
       still in the future): return that plan.
    3. Otherwise: return the default plan (``is_default=True``).
    """
    result = await session.exec(select(User).where(User.id == user_id))
    user = result.one_or_none()

    if user and user.plan_id:
        now = utcnow_naive()
        if user.plan_effective_until is None or user.plan_effective_until > now:
            plan_result = await session.exec(select(Plan).where(Plan.id == user.plan_id))
            plan = plan_result.one_or_none()
            if plan:
                return plan

    # Fall back to the default plan
    default_result = await session.exec(
        select(Plan).where(Plan.is_default == True)  # noqa: E712
    )
    default_plan = default_result.one()
    return default_plan


# ---------------------------------------------------------------------------
# Advisory-lock helpers
# ---------------------------------------------------------------------------


async def _advisory_lock(session: AsyncSession, key: str) -> None:
    """Acquire a transaction-scoped advisory lock keyed by *key*.

    Uses PostgreSQL's built-in ``hashtext()`` for deterministic hashing.
    Python's ``hash()`` is randomised per process and MUST NOT be used.
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": key},
    )


# ---------------------------------------------------------------------------
# Resource-specific checks
# ---------------------------------------------------------------------------


async def check_source_quota(session: AsyncSession, user_id: str, plan: Plan) -> None:
    """Raise if the user has reached their source limit."""
    if not plan.max_sources:
        return

    await _advisory_lock(session, f"{user_id}:source")

    result = await session.exec(select(func.count()).where(Source.user_id == user_id))
    count = result.one()

    if count >= plan.max_sources:
        msg = "source"
        raise QuotaExceededError(msg, count, plan.max_sources)


async def check_article_quota(session: AsyncSession, user_id: str, plan: Plan) -> None:
    """Raise if the user has reached their article limit."""
    if not plan.max_articles:
        return

    await _advisory_lock(session, f"{user_id}:article")

    result = await session.exec(select(func.count()).where(Article.user_id == user_id))
    count = result.one()

    if count >= plan.max_articles:
        msg = "article"
        raise QuotaExceededError(msg, count, plan.max_articles)


# ---------------------------------------------------------------------------
# Storage (reserve / commit pattern)
# ---------------------------------------------------------------------------


async def reserve_storage(session: AsyncSession, user_id: str, plan: Plan) -> None:
    """Pre-check: reject if already over the storage limit.

    No bytes are reserved — call :func:`commit_storage` after ingest
    with the actual byte count.
    """
    if not plan.max_storage_bytes:
        return

    result = await session.exec(select(StorageUsage).where(StorageUsage.user_id == user_id).with_for_update())
    usage = result.one_or_none()

    if usage and usage.total_bytes >= plan.max_storage_bytes:
        msg = "storage"
        raise QuotaExceededError(msg, usage.total_bytes, plan.max_storage_bytes)


async def check_storage_quota(session: AsyncSession, user_id: str, plan: Plan) -> None:
    """Pre-check only: reject if already over limit.

    Alias for :func:`reserve_storage`.
    Call :func:`commit_storage` after ingest with the actual bytes.
    """
    await reserve_storage(session, user_id, plan)


async def commit_storage(session: AsyncSession, user_id: str, actual_bytes: int) -> None:
    """Atomically add *actual_bytes* to the user's storage usage."""
    await session.execute(
        update(StorageUsage)
        .where(StorageUsage.user_id == user_id)  # type: ignore[arg-type]
        .values(
            total_bytes=StorageUsage.total_bytes + actual_bytes,
            updated_at=utcnow_naive(),
        )
    )


# ---------------------------------------------------------------------------
# Query quota (check-then-increment)
# ---------------------------------------------------------------------------


async def check_query_quota(session: AsyncSession, user_id: str, plan: Plan) -> None:
    """Check the daily query count BEFORE incrementing.

    If the user is under quota the count is incremented atomically.
    If the transaction rolls back (e.g. downstream LLM error), the
    increment is undone automatically.
    """
    if not plan.max_queries_per_day:
        return

    today = datetime.now(tz=UTC).date()

    # Ensure a row exists for today (idempotent upsert)
    await session.execute(
        text(
            "INSERT INTO query_count (user_id, date, count) VALUES (:uid, :d, 0) ON CONFLICT (user_id, date) DO NOTHING"
        ),
        {"uid": user_id, "d": today},
    )

    # Lock the row and read current count
    row = await session.execute(
        text("SELECT count FROM query_count WHERE user_id = :uid AND date = :d FOR UPDATE"),
        {"uid": user_id, "d": today},
    )
    current = row.scalar() or 0

    # Check BEFORE incrementing
    if current >= plan.max_queries_per_day:
        msg = "query"
        raise QuotaExceededError(msg, current, plan.max_queries_per_day)

    # Increment (only reached when under quota)
    await session.execute(
        text("UPDATE query_count SET count = count + 1 WHERE user_id = :uid AND date = :d"),
        {"uid": user_id, "d": today},
    )


# ---------------------------------------------------------------------------
# Share quota
# ---------------------------------------------------------------------------


async def check_share_quota(session: AsyncSession, user_id: str, plan: Plan) -> None:
    """Raise if the user has reached their active share-link limit."""
    if not plan.max_active_shares:
        return

    await _advisory_lock(session, f"{user_id}:share")

    result = await session.exec(
        select(func.count()).where(
            ShareLink.user_id == user_id,
            ShareLink.revoked == False,  # noqa: E712
        )
    )
    count = result.one()

    if count >= plan.max_active_shares:
        msg = "share_link"
        raise QuotaExceededError(msg, count, plan.max_active_shares)


# ---------------------------------------------------------------------------
# Pure checks (no DB access)
# ---------------------------------------------------------------------------


async def check_export_format(plan: Plan, fmt: str) -> None:
    """Raise if *fmt* is not in the plan's allowed export formats."""
    if fmt not in plan.allowed_exports:
        msg = "export"
        raise QuotaExceededError(msg, 0, 0)


async def check_mcp_access(plan: Plan) -> None:
    """Raise if the plan does not include MCP access."""
    if not plan.mcp_enabled:
        msg = "mcp"
        raise QuotaExceededError(msg, 0, 0)


# ---------------------------------------------------------------------------
# Daily LLM spend cap
# ---------------------------------------------------------------------------


async def check_daily_llm_spend(session: AsyncSession, user_id: str, plan: Plan) -> None:
    """Raise if today's LLM spend has reached the plan's daily cap.

    ``CostLog.cost_usd`` is stored as a float in USD. The plan cap is
    in integer cents. Multiply the sum by 100 to compare in cents.
    """
    if not plan.daily_llm_spend_cap_cents:
        return

    today = datetime.now(tz=UTC).date()

    result = await session.execute(
        text("SELECT COALESCE(SUM(cost_usd), 0) FROM costlog WHERE user_id = :uid AND DATE(created_at) = :d"),
        {"uid": user_id, "d": today},
    )
    today_usd = result.scalar() or 0.0
    today_cents = int(today_usd * 100)

    if today_cents >= plan.daily_llm_spend_cap_cents:
        msg = "llm_spend"
        raise QuotaExceededError(msg, today_cents, plan.daily_llm_spend_cap_cents)
