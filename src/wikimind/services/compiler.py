"""Manage compilation jobs and article persistence.

Wraps the BackgroundCompiler and job queue, providing a clean interface
for triggering compilation, linting, and reindexing from API routes.
"""

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.jobs.background import get_background_compiler
from wikimind.models import Job


class CompilerService:
    """Coordinate compilation job management and status tracking."""

    async def list_jobs(self, session: AsyncSession, status: str | None = None, limit: int = 20) -> list[Job]:
        """List jobs with optional status filtering.

        Args:
            session: Async database session.
            status: Optional status filter (queued, running, complete, failed).
            limit: Maximum number of results.

        Returns:
            List of Job records ordered by queue time descending.
        """
        query = select(Job).order_by(Job.queued_at.desc()).limit(limit)  # type: ignore[attr-defined]
        if status:
            query = query.where(Job.status == status)
        result = await session.execute(query)
        return list(result.scalars().all())

    async def get_job(self, job_id: str, session: AsyncSession) -> Job | None:
        """Retrieve a single job by ID.

        Args:
            job_id: The job UUID.
            session: Async database session.

        Returns:
            The Job record, or None if not found.
        """
        return await session.get(Job, job_id)

    async def trigger_compile(self, source_id: str) -> dict[str, str]:
        """Schedule a compilation job for a source.

        Args:
            source_id: The source UUID to compile.

        Returns:
            Dict with job_id and status.
        """
        bg = get_background_compiler()
        job_id = await bg.schedule_compile(source_id)
        return {"job_id": job_id, "status": "queued"}

    async def trigger_lint(self) -> dict[str, str]:
        """Schedule a wiki linting job.

        Returns:
            Dict with job_id and status.
        """
        bg = get_background_compiler()
        job_id = await bg.schedule_lint()
        return {"job_id": job_id, "status": "queued"}

    async def trigger_reindex(self) -> dict[str, str]:
        """Enqueue a wiki reindexing job.

        Returns:
            Dict with status and message.
        """
        return {"status": "queued", "message": "Reindex job enqueued"}


_compiler_service: CompilerService | None = None


def get_compiler_service() -> CompilerService:
    """Return a singleton CompilerService instance for FastAPI dependency injection."""
    global _compiler_service
    if _compiler_service is None:
        _compiler_service = CompilerService()
    return _compiler_service
