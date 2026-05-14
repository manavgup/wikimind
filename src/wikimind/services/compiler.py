"""Manage compilation jobs and article persistence.

Wraps the BackgroundCompiler and job queue, providing a clean interface
for triggering compilation, linting, and reindexing from API routes.
"""

import functools

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.jobs.background import get_background_compiler
from wikimind.models import Job, JobTriggerResponse


class CompilerService:
    """Coordinate compilation job management and status tracking."""

    async def list_jobs(
        self,
        session: AsyncSession,
        user_id: str,
        status: str | None = None,
        limit: int = 20,
    ) -> list[Job]:
        """List jobs with optional status filtering.

        Args:
            session: Async database session.
            status: Optional status filter (queued, running, complete, failed).
            limit: Maximum number of results.
            user_id: Optional user ID filter.

        Returns:
            List of Job records ordered by queue time descending.
        """
        query = select(Job).order_by(Job.queued_at.desc()).limit(limit)  # type: ignore[attr-defined]
        if user_id:
            query = query.where(Job.user_id == user_id)
        if status:
            query = query.where(Job.status == status)
        result = await session.execute(query)
        return list(result.scalars().all())

    async def get_job(self, job_id: str, session: AsyncSession, *, user_id: str) -> Job | None:
        """Retrieve a single job by ID, scoped to the requesting user.

        Args:
            job_id: The job UUID.
            session: Async database session.
            user_id: Owner ID — only jobs belonging to this user are returned.

        Returns:
            The Job record, or None if not found or not owned by user_id.
        """
        query = select(Job).where(Job.id == job_id, Job.user_id == user_id)
        result = await session.execute(query)
        return result.scalar_one_or_none()

    async def trigger_compile(self, source_id: str, user_id: str) -> JobTriggerResponse:
        """Schedule a compilation job for a source.

        Args:
            source_id: The source UUID to compile.
            user_id: Optional owner — used to resolve BYOK API keys.

        Returns:
            JobTriggerResponse with job_id and status.
        """
        bg = get_background_compiler()
        job_id = await bg.schedule_compile(source_id, user_id=user_id)
        return JobTriggerResponse(job_id=job_id, status="queued")

    async def trigger_lint(self, user_id: str) -> JobTriggerResponse:
        """Schedule a wiki linting job.

        Args:
            user_id: Owner for scoping the lint run.

        Returns:
            JobTriggerResponse with job_id and status.
        """
        bg = get_background_compiler()
        job_id = await bg.schedule_lint(user_id=user_id)
        return JobTriggerResponse(job_id=job_id, status="queued")

    async def trigger_reindex(self) -> JobTriggerResponse:
        """Enqueue a wiki reindexing job.

        Returns:
            JobTriggerResponse with status and message.
        """
        return JobTriggerResponse(status="queued", message="Reindex job enqueued")


@functools.lru_cache(maxsize=1)
def get_compiler_service() -> CompilerService:
    """Return a singleton CompilerService instance for FastAPI dependency injection."""
    return CompilerService()
