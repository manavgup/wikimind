"""Golden-file snapshot tests for API response shapes.

Compares actual API responses against recorded snapshots in
``tests/_snapshots/``.  Volatile fields (timestamps, UUIDs, request IDs)
are replaced with deterministic placeholders before comparison so only
structural/semantic changes trigger failures.

Set ``WIKIMIND_UPDATE_SNAPSHOTS=1`` to regenerate all snapshots.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from tests.conftest import TEST_USER_ID
from tests.snapshot_utils import assert_matches_snapshot
from wikimind.api.services import get_ingest_service
from wikimind.models import Article, IngestStatus, PageType, Source, SourceType

# ---------------------------------------------------------------------------
# GET /health — top-level health check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_response_snapshot(client) -> None:
    """GET /health response shape must match the golden file."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert_matches_snapshot(response.json(), "health_response")


# ---------------------------------------------------------------------------
# Error envelope — WikiMindError → JSON error format
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_error_envelope_not_found_snapshot(client) -> None:
    """404 error envelope shape must match the golden file."""
    response = await client.get("/api/wiki/articles/does-not-exist-snapshot-test")
    assert response.status_code == 404
    assert_matches_snapshot(response.json(), "error_envelope_not_found")


@pytest.mark.asyncio
async def test_error_envelope_validation_snapshot(client) -> None:
    """422 validation error shape must match the golden file.

    POST /ingest/text with an empty body triggers Pydantic validation.
    """
    response = await client.post("/api/ingest/text", json={})
    assert response.status_code == 422
    assert_matches_snapshot(response.json(), "error_envelope_validation")


# ---------------------------------------------------------------------------
# GET /api/wiki/articles — list response shape (empty + populated)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_articles_list_empty_snapshot(client) -> None:
    """GET /api/wiki/articles with no articles must match the golden file."""
    response = await client.get("/api/wiki/articles")
    assert response.status_code == 200
    assert_matches_snapshot(response.json(), "articles_list_empty")


@pytest.mark.asyncio
async def test_articles_list_populated_snapshot(client, session_factory) -> None:
    """GET /api/wiki/articles with one article must match the golden file."""
    async with session_factory() as session:
        session.add(
            Article(
                id="snap-art-1",
                slug="snapshot-article",
                title="Snapshot Article",
                file_path="/tmp/snap.md",
                user_id=TEST_USER_ID,
                page_type=PageType.SOURCE,
                summary="A test article for snapshot testing.",
            )
        )
        await session.commit()

    response = await client.get("/api/wiki/articles")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert_matches_snapshot(data, "articles_list_populated")


# ---------------------------------------------------------------------------
# POST /api/ingest/text — response shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_text_response_snapshot(client) -> None:
    """POST /api/ingest/text response shape must match the golden file."""
    fake_src = Source(
        id="snap-src-1",
        source_type=SourceType.TEXT,
        title="Snapshot Note",
        status=IngestStatus.PENDING,
        user_id=TEST_USER_ID,
    )
    svc = get_ingest_service()
    with (
        patch.object(svc, "_adapter") as adapter,
        patch("wikimind.services.ingest.get_background_compiler") as gbc,
    ):
        adapter.ingest_text = AsyncMock(return_value=(fake_src, None))
        gbc.return_value.schedule_compile = AsyncMock(return_value="job-snap-1")
        response = await client.post(
            "/api/ingest/text",
            json={"content": "Snapshot test content", "title": "Snapshot Note"},
        )
    assert response.status_code == 200
    assert_matches_snapshot(response.json(), "ingest_text_response")
