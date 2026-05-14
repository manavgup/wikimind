"""Tests for job route ownership checks (#642, #661).

Verifies that get_job and trigger_compile are scoped to the requesting
user, returning 404/None for resources belonging to another user.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from wikimind.api.deps import ANONYMOUS_USER_ID
from wikimind.models import Job, JobStatus, JobType, Source, SourceType

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncEngine

OTHER_USER_ID = "other-user"


async def _seed(async_engine: AsyncEngine, model):
    """Insert a model instance and return it refreshed."""
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    async with factory() as session:
        session.add(model)
        await session.commit()
        await session.refresh(model)
        return model


# ---------------------------------------------------------------------------
# get_job ownership (#642)
# ---------------------------------------------------------------------------


class TestGetJobOwnership:
    @pytest.mark.asyncio
    async def test_get_job_own_user(self, client: AsyncClient, async_engine: AsyncEngine):
        """Owner can read their own job."""
        job = await _seed(
            async_engine,
            Job(
                id="job-owned",
                user_id=ANONYMOUS_USER_ID,
                job_type=JobType.COMPILE_SOURCE,
                status=JobStatus.QUEUED,
            ),
        )
        resp = await client.get(f"/api/jobs/{job.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data is not None
        assert data["id"] == "job-owned"

    @pytest.mark.asyncio
    async def test_get_job_other_user_returns_none(self, client: AsyncClient, async_engine: AsyncEngine):
        """A job belonging to another user is invisible (returns None/null)."""
        await _seed(
            async_engine,
            Job(
                id="job-other",
                user_id=OTHER_USER_ID,
                job_type=JobType.COMPILE_SOURCE,
                status=JobStatus.QUEUED,
            ),
        )
        resp = await client.get("/api/jobs/job-other")
        assert resp.status_code == 200
        assert resp.json() is None


# ---------------------------------------------------------------------------
# trigger_compile ownership (#661)
# ---------------------------------------------------------------------------


class TestTriggerCompileOwnership:
    @pytest.mark.asyncio
    async def test_trigger_compile_own_source(self, client: AsyncClient, async_engine: AsyncEngine):
        """Owner can trigger compile on their own source."""
        await _seed(
            async_engine,
            Source(
                id="src-owned",
                source_type=SourceType.TEXT,
                title="Mine",
                file_path="src-owned.txt",
                user_id=ANONYMOUS_USER_ID,
            ),
        )
        mock_bg = MagicMock()
        mock_bg.schedule_compile = AsyncMock(return_value="job-999")
        with patch(
            "wikimind.services.compiler.get_background_compiler",
            return_value=mock_bg,
        ):
            resp = await client.post("/api/jobs/compile/src-owned")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "queued"

    @pytest.mark.asyncio
    async def test_trigger_compile_other_user_returns_404(self, client: AsyncClient, async_engine: AsyncEngine):
        """Triggering compile on another user's source returns 404."""
        await _seed(
            async_engine,
            Source(
                id="src-other",
                source_type=SourceType.TEXT,
                title="Theirs",
                file_path="src-other.txt",
                user_id=OTHER_USER_ID,
            ),
        )
        resp = await client.post("/api/jobs/compile/src-other")
        assert resp.status_code == 404
