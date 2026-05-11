"""Deep health check endpoint for production monitoring.

Checks database connectivity, Alembic migration version, LLM provider
availability, and stuck source processing jobs. Returns a structured JSON
response with per-check status and overall system health.
"""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Any

import structlog
from fastapi import APIRouter
from sqlalchemy import text as sa_text
from sqlmodel import select

from wikimind._datetime import utcnow_naive
from wikimind.config import get_settings
from wikimind.database import get_session_factory
from wikimind.models import IngestStatus, Source

router = APIRouter()
log = structlog.get_logger()

# Alembic head revision — derived from the migration files at import time
# so it never goes stale when new migrations are added.
def _get_alembic_head() -> str:
    """Read the latest revision from alembic's script directory."""
    try:
        from alembic.config import Config  # noqa: PLC0415
        from alembic.script import ScriptDirectory  # noqa: PLC0415

        cfg = Config("alembic.ini")
        script = ScriptDirectory.from_config(cfg)
        heads = script.get_heads()
        return heads[0] if heads else "unknown"
    except Exception:
        return "unknown"


_EXPECTED_ALEMBIC_HEAD = _get_alembic_head()

# Sources stuck in PROCESSING for longer than this are considered unhealthy.
_STUCK_SOURCE_THRESHOLD = timedelta(minutes=10)


async def _check_database() -> dict[str, Any]:
    """Verify database connectivity with a simple SELECT 1."""
    start = time.monotonic()
    try:
        async with get_session_factory()() as session:
            await session.execute(sa_text("SELECT 1"))
        latency_ms = round((time.monotonic() - start) * 1000)
        return {"status": "ok", "latency_ms": latency_ms}
    except Exception as exc:
        latency_ms = round((time.monotonic() - start) * 1000)
        log.warning("health: database check failed", error=str(exc))
        return {"status": "error", "latency_ms": latency_ms, "error": str(exc)}


async def _check_migrations() -> dict[str, Any]:
    """Verify Alembic migration version matches the expected head."""
    try:
        async with get_session_factory()() as session:
            result = await session.execute(
                sa_text("SELECT version_num FROM alembic_version ORDER BY version_num DESC LIMIT 1")
            )
            row = result.fetchone()
            current = row[0] if row else "none"
        status = "ok" if current == _EXPECTED_ALEMBIC_HEAD else "warning"
        return {
            "status": status,
            "current": current,
            "expected": _EXPECTED_ALEMBIC_HEAD,
        }
    except Exception as exc:
        log.warning("health: migration check failed", error=str(exc))
        return {
            "status": "error",
            "current": "unknown",
            "expected": _EXPECTED_ALEMBIC_HEAD,
            "error": str(exc),
        }


def _check_llm_provider() -> dict[str, Any]:
    """Check that at least one LLM provider is configured and enabled."""
    settings = get_settings()
    providers = ["anthropic", "openai", "openai_compatible", "google", "ollama", "mock"]
    for name in providers:
        cfg = getattr(settings.llm, name, None)
        if cfg and cfg.enabled:
            return {"status": "ok", "provider": name}
    return {"status": "error", "provider": "none"}


async def _check_stuck_sources() -> dict[str, Any]:
    """Count sources stuck in PROCESSING for longer than the threshold."""
    try:
        cutoff = utcnow_naive() - _STUCK_SOURCE_THRESHOLD
        async with get_session_factory()() as session:
            result = await session.execute(
                select(Source).where(
                    Source.status == IngestStatus.PROCESSING,
                    Source.ingested_at < cutoff,
                )
            )
            stuck = list(result.scalars().all())
        count = len(stuck)
        status = "ok" if count == 0 else "warning"
        return {"status": status, "count": count}
    except Exception as exc:
        log.warning("health: stuck sources check failed", error=str(exc))
        return {"status": "error", "count": -1, "error": str(exc)}


def _overall_status(checks: dict[str, dict[str, Any]]) -> str:
    """Derive overall status from individual check results.

    - All ok -> healthy
    - Any warning -> degraded
    - Any error -> unhealthy
    """
    statuses = {c["status"] for c in checks.values()}
    if "error" in statuses:
        return "unhealthy"
    if "warning" in statuses:
        return "degraded"
    return "healthy"


@router.get("/health/deep")
async def deep_health_check() -> dict[str, Any]:
    """Deep health check — verifies database, migrations, LLM provider, and stuck sources."""
    checks: dict[str, dict[str, Any]] = {}

    checks["database"] = await _check_database()
    checks["migrations"] = await _check_migrations()
    checks["llm_provider"] = _check_llm_provider()
    checks["stuck_sources"] = await _check_stuck_sources()

    return {
        "status": _overall_status(checks),
        "checks": checks,
    }
