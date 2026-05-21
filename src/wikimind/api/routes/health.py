"""Deep health check endpoint for production monitoring.

Checks database connectivity, Alembic migration version, LLM provider
availability, stuck source processing jobs, Redis connectivity, and ARQ
queue depth. Returns a structured JSON response with per-check status
and overall system health.

The ``/health/job-ping`` endpoint enqueues a lightweight ping job and
polls for its result to verify the full background job pipeline:
API -> Redis -> ARQ worker -> result.
"""

from __future__ import annotations

import asyncio
import time
from datetime import timedelta
from typing import Any

import structlog
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from arq.jobs import Job as ArqJob
from arq.jobs import JobStatus as ArqJobStatus
from fastapi import APIRouter
from redis.asyncio import Redis
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
        cfg = AlembicConfig("alembic.ini")
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


async def _check_redis() -> dict[str, Any]:
    """Verify Redis connectivity via PING when redis_url is configured."""
    settings = get_settings()
    if settings.redis_url is None:
        return {"status": "ok", "mode": "in_process"}

    start = time.monotonic()
    r = Redis.from_url(settings.redis_url, socket_connect_timeout=3, socket_timeout=3)
    try:
        await r.ping()
        latency_ms = round((time.monotonic() - start) * 1000)
        return {"status": "ok", "mode": "arq", "latency_ms": latency_ms}
    except Exception as exc:
        log.warning("health: redis check failed", error=str(exc))
        return {"status": "error", "mode": "arq", "error": str(exc)}
    finally:
        await r.aclose()


async def _check_queue_depth() -> dict[str, Any]:
    """Check the ARQ pending job queue depth."""
    settings = get_settings()
    if settings.redis_url is None:
        return {"status": "ok", "pending_jobs": 0}

    r = Redis.from_url(settings.redis_url, socket_connect_timeout=3, socket_timeout=3)
    try:
        depth = await r.zcard("arq:queue")
        status = "ok" if depth < 100 else "warning"
        return {"status": status, "pending_jobs": depth}
    except Exception as exc:
        log.warning("health: queue depth check failed", error=str(exc))
        return {"status": "error", "error": str(exc)}
    finally:
        await r.aclose()


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
    checks["redis"] = await _check_redis()
    checks["queue"] = await _check_queue_depth()

    return {
        "status": _overall_status(checks),
        "checks": checks,
    }


# ---------------------------------------------------------------------------
# Job ping — end-to-end background job verification
# ---------------------------------------------------------------------------

# Maximum time to wait for the ping job to complete (seconds).
_JOB_PING_TIMEOUT = 30
# Interval between result polls (seconds).
_JOB_PING_POLL_INTERVAL = 1


@router.get("/health/job-ping")
async def job_ping() -> dict[str, Any]:
    """Enqueue a lightweight ping job and wait for its result.

    Proves the full background job pipeline works end-to-end:
    API -> Redis -> ARQ worker -> result.

    Returns ``{"status": "ok", ...}`` when the job completes within the
    timeout, or ``{"status": "error", ...}`` on failure or timeout.
    In dev mode (no Redis), returns ``{"status": "skipped"}`` since
    there is no ARQ worker to verify.
    """
    from wikimind.jobs.background import get_background_compiler  # noqa: PLC0415

    compiler = get_background_compiler()

    if not compiler.is_prod:
        return {"status": "skipped", "reason": "in-process mode (no Redis)"}

    start = time.monotonic()
    try:
        job_id = await compiler.schedule_ping()
        if job_id is None:
            return {"status": "error", "error": "Failed to enqueue ping job"}

        # Poll ARQ for the job result
        pool = await compiler._get_pool()
        for _ in range(int(_JOB_PING_TIMEOUT / _JOB_PING_POLL_INTERVAL)):
            arq_job = ArqJob(job_id, redis=pool)
            status = await arq_job.status()
            if status == ArqJobStatus.complete:
                info = await arq_job.result_info()
                latency_ms = round((time.monotonic() - start) * 1000)
                return {
                    "status": "ok",
                    "job_id": job_id,
                    "result": info.result if info else None,
                    "latency_ms": latency_ms,
                }
            if status == ArqJobStatus.not_found:
                # Job disappeared — worker may have crashed
                latency_ms = round((time.monotonic() - start) * 1000)
                return {
                    "status": "error",
                    "job_id": job_id,
                    "error": "Job not found — worker may not be running",
                    "latency_ms": latency_ms,
                }
            await asyncio.sleep(_JOB_PING_POLL_INTERVAL)

        latency_ms = round((time.monotonic() - start) * 1000)
        return {
            "status": "error",
            "job_id": job_id,
            "error": f"Ping job did not complete within {_JOB_PING_TIMEOUT}s",
            "latency_ms": latency_ms,
        }
    except Exception as exc:
        latency_ms = round((time.monotonic() - start) * 1000)
        log.warning("health: job-ping failed", error=str(exc))
        return {
            "status": "error",
            "error": str(exc),
            "latency_ms": latency_ms,
        }
