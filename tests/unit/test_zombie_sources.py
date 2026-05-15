"""Tests for zombie source detection and compile retry blocking (#554)."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

from tests.conftest import TEST_USER_ID
from wikimind._datetime import utcnow_naive
from wikimind.models import IngestStatus, Source, SourceType
from wikimind.services.admin import AdminService

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession


# ---------------------------------------------------------------------------
# Admin zombie detection
# ---------------------------------------------------------------------------


async def test_find_zombie_sources_empty(db_session: AsyncSession) -> None:
    """No sources — returns empty list."""
    service = AdminService()
    zombies = await service.find_zombie_sources(db_session, user_id=TEST_USER_ID)
    assert zombies == []


async def test_find_zombie_sources_detects_stuck(db_session: AsyncSession) -> None:
    """Source in processing with no file_path and old ingested_at is a zombie."""
    zombie = Source(
        source_type=SourceType.TEXT,
        title="Zombie",
        status=IngestStatus.PROCESSING,
        file_path=None,
        ingested_at=utcnow_naive() - timedelta(minutes=15),
        user_id=TEST_USER_ID,
    )
    db_session.add(zombie)
    await db_session.commit()

    service = AdminService()
    zombies = await service.find_zombie_sources(db_session, user_id=TEST_USER_ID)
    assert len(zombies) == 1
    assert zombies[0].id == zombie.id
    assert zombies[0].title == "Zombie"


async def test_find_zombie_sources_ignores_recent(db_session: AsyncSession) -> None:
    """Source in processing with no file_path but recent ingested_at is not a zombie."""
    recent = Source(
        source_type=SourceType.TEXT,
        title="Recent",
        status=IngestStatus.PROCESSING,
        file_path=None,
        ingested_at=utcnow_naive() - timedelta(minutes=2),
        user_id=TEST_USER_ID,
    )
    db_session.add(recent)
    await db_session.commit()

    service = AdminService()
    zombies = await service.find_zombie_sources(db_session, user_id=TEST_USER_ID)
    assert zombies == []


async def test_find_zombie_sources_ignores_with_file_path(db_session: AsyncSession) -> None:
    """Source in processing WITH file_path is not a zombie (just slow compile)."""
    normal = Source(
        source_type=SourceType.TEXT,
        title="Normal",
        status=IngestStatus.PROCESSING,
        file_path="abc.txt",
        ingested_at=utcnow_naive() - timedelta(minutes=15),
        user_id=TEST_USER_ID,
    )
    db_session.add(normal)
    await db_session.commit()

    service = AdminService()
    zombies = await service.find_zombie_sources(db_session, user_id=TEST_USER_ID)
    assert zombies == []


# ---------------------------------------------------------------------------
# Compile route blocks zombie sources
# ---------------------------------------------------------------------------


async def test_compile_route_rejects_zombie_source(client) -> None:
    """POST /api/jobs/compile/{id} returns 422 for zombie sources."""
    from wikimind.database import get_session
    from wikimind.main import app

    # Insert a zombie source via the test database
    async for session in app.dependency_overrides[get_session]():
        zombie = Source(
            id="zombie-123",
            source_type=SourceType.TEXT,
            title="Zombie",
            status=IngestStatus.PROCESSING,
            file_path=None,
            user_id=TEST_USER_ID,
        )
        session.add(zombie)
        await session.commit()

    resp = await client.post(
        "/api/jobs/compile/zombie-123",
    )
    assert resp.status_code == 422
    assert "no content file" in resp.json()["error"]["message"].lower()


async def test_compile_route_allows_valid_source(client) -> None:
    """POST /api/jobs/compile/{id} succeeds for sources with file_path."""
    from wikimind.database import get_session
    from wikimind.main import app

    async for session in app.dependency_overrides[get_session]():
        valid = Source(
            id="valid-123",
            source_type=SourceType.TEXT,
            title="Valid",
            status=IngestStatus.PROCESSING,
            file_path="valid-123.txt",
            user_id=TEST_USER_ID,
        )
        session.add(valid)
        await session.commit()

    with patch(
        "wikimind.services.compiler.CompilerService.trigger_compile",
        new_callable=AsyncMock,
        return_value={"job_id": "j-1", "status": "queued"},
    ):
        resp = await client.post(
            "/api/jobs/compile/valid-123",
        )
    assert resp.status_code == 200


async def test_compile_route_returns_404_for_missing_source(client) -> None:
    """POST /api/jobs/compile/{id} returns 404 for non-existent source."""
    resp = await client.post(
        "/api/jobs/compile/nonexistent-id",
        headers={"X-User-Id": TEST_USER_ID},
    )
    assert resp.status_code == 404
