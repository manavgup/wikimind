"""Endpoints for managing async compilation and linting jobs."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.database import get_session
from wikimind.jobs.worker import enqueue_compile, enqueue_lint
from wikimind.models import Job

router = APIRouter()


@router.get("")
async def list_jobs(
    status: str | None = None,
    limit: int = 20,
    session: AsyncSession = Depends(get_session),
):
    """List jobs with optional status filter."""
    query = select(Job).order_by(Job.queued_at.desc()).limit(limit)  # type: ignore[attr-defined]
    if status:
        query = query.where(Job.status == status)
    result = await session.execute(query)
    return result.scalars().all()


@router.get("/{job_id}")
async def get_job(job_id: str, session: AsyncSession = Depends(get_session)):
    """Get job by ID."""
    job = await session.get(Job, job_id)
    return job


@router.post("/compile/{source_id}")
async def trigger_compile(source_id: str, session: AsyncSession = Depends(get_session)):
    """Trigger compilation for a source."""
    job_id = await enqueue_compile(source_id)
    return {"job_id": job_id, "status": "queued"}


@router.post("/lint")
async def trigger_lint(session: AsyncSession = Depends(get_session)):
    """Trigger wiki linting."""
    job_id = await enqueue_lint()
    return {"job_id": job_id, "status": "queued"}


@router.post("/reindex")
async def trigger_reindex(session: AsyncSession = Depends(get_session)):
    """Trigger wiki reindexing."""
    return {"status": "queued", "message": "Reindex job enqueued"}
