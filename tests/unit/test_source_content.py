"""Tests for the GET /ingest/sources/{id}/content endpoint."""

from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import TEST_USER_ID
from wikimind.api.deps import get_current_user_id
from wikimind.database import get_session
from wikimind.errors import NotFoundError
from wikimind.main import app
from wikimind.models import Source, SourceContentResponse, SourceType
from wikimind.services.ingest import IngestService, get_ingest_service
from wikimind.storage import LocalFileStorage


@pytest.fixture
def source_with_content():
    return Source(
        id="src-abc",
        source_type=SourceType.URL,
        file_path="src-abc.txt",
        title="Test Article",
        user_id=TEST_USER_ID,
    )


@pytest.fixture
def source_no_file():
    return Source(
        id="src-nofile",
        source_type=SourceType.TEXT,
        file_path=None,
        title="No File Source",
        user_id=TEST_USER_ID,
    )


async def _fake_session() -> AsyncGenerator:
    """Minimal session override that satisfies FastAPI DI without a real DB."""
    yield AsyncMock()


async def test_content_endpoint_returns_text(tmp_path: Path, source_with_content: Source) -> None:
    """Endpoint returns the raw text content with metadata."""
    raw_text = "This is the original source text.\n\nSecond paragraph."
    (tmp_path / "src-abc.txt").write_text(raw_text)

    mock_svc = AsyncMock()
    mock_svc.get_source = AsyncMock(return_value=source_with_content)
    mock_svc.get_source_content = AsyncMock(
        return_value=SourceContentResponse(
            content=raw_text,
            source_type=SourceType.URL,
            title="Test Article",
        )
    )

    app.dependency_overrides[get_session] = _fake_session
    app.dependency_overrides[get_ingest_service] = lambda: mock_svc
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/ingest/sources/src-abc/content")
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_ingest_service, None)
        app.dependency_overrides.pop(get_current_user_id, None)

    assert resp.status_code == 200
    data = resp.json()
    assert data["content"] == raw_text
    assert data["source_type"] == "url"
    assert data["title"] == "Test Article"


async def test_content_endpoint_404_when_source_not_found() -> None:
    """Endpoint returns 404 when source does not exist."""
    mock_svc = AsyncMock()
    mock_svc.get_source_content = AsyncMock(side_effect=NotFoundError("Source not found"))

    app.dependency_overrides[get_session] = _fake_session
    app.dependency_overrides[get_ingest_service] = lambda: mock_svc
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/ingest/sources/nonexistent/content")
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_ingest_service, None)
        app.dependency_overrides.pop(get_current_user_id, None)

    assert resp.status_code == 404


async def test_content_endpoint_404_when_wrong_user() -> None:
    """Endpoint returns 404 when source belongs to a different user."""
    mock_svc = AsyncMock()
    mock_svc.get_source_content = AsyncMock(side_effect=NotFoundError("Source not found"))

    app.dependency_overrides[get_session] = _fake_session
    app.dependency_overrides[get_ingest_service] = lambda: mock_svc
    app.dependency_overrides[get_current_user_id] = lambda: "other-user"

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/ingest/sources/src-abc/content")
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_ingest_service, None)
        app.dependency_overrides.pop(get_current_user_id, None)

    assert resp.status_code == 404


async def test_content_endpoint_passes_user_id() -> None:
    """The /content endpoint forwards user_id from the auth dependency."""
    mock_svc = AsyncMock()
    mock_svc.get_source_content = AsyncMock(
        return_value=SourceContentResponse(
            content="text",
            source_type=SourceType.TEXT,
            title="Test",
        )
    )

    app.dependency_overrides[get_session] = _fake_session
    app.dependency_overrides[get_ingest_service] = lambda: mock_svc
    app.dependency_overrides[get_current_user_id] = lambda: "test-user-456"

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/ingest/sources/src-abc/content")
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_ingest_service, None)
        app.dependency_overrides.pop(get_current_user_id, None)

    assert resp.status_code == 200
    mock_svc.get_source_content.assert_awaited_once()
    call_kwargs = mock_svc.get_source_content.call_args
    assert call_kwargs[0][0] == "src-abc"
    assert call_kwargs[1]["user_id"] == "test-user-456"


async def test_service_get_source_content_reads_file(tmp_path: Path) -> None:
    """IngestService.get_source_content reads the text file from storage."""
    raw_text = "Original source text here."
    (tmp_path / "src-xyz.txt").write_text(raw_text)

    source = Source(
        id="src-xyz",
        source_type=SourceType.URL,
        file_path="src-xyz.txt",
        title="My Source",
        user_id=TEST_USER_ID,
    )

    service = IngestService()

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=source)

    with patch(
        "wikimind.services.ingest.get_raw_storage",
        return_value=LocalFileStorage(root=tmp_path),
    ):
        result = await service.get_source_content("src-xyz", mock_session, user_id=TEST_USER_ID)

    assert result.content == raw_text
    assert result.source_type == SourceType.URL
    assert result.title == "My Source"


async def test_service_get_source_content_no_file_path() -> None:
    """IngestService.get_source_content raises NotFoundError when file_path is None."""
    source = Source(
        id="src-nofile",
        source_type=SourceType.TEXT,
        file_path=None,
        title="No File",
        user_id=TEST_USER_ID,
    )

    service = IngestService()

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=source)

    with pytest.raises(NotFoundError, match="no stored content"):
        await service.get_source_content("src-nofile", mock_session, user_id=TEST_USER_ID)


async def test_service_get_source_content_missing_file(tmp_path: Path) -> None:
    """IngestService.get_source_content raises NotFoundError when file doesn't exist on disk."""
    source = Source(
        id="src-gone",
        source_type=SourceType.URL,
        file_path="src-gone.txt",
        title="Gone",
        user_id=TEST_USER_ID,
    )

    service = IngestService()

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=source)

    with (
        patch(
            "wikimind.services.ingest.get_raw_storage",
            return_value=LocalFileStorage(root=tmp_path),
        ),
        pytest.raises(NotFoundError, match="content file not found"),
    ):
        await service.get_source_content("src-gone", mock_session, user_id=TEST_USER_ID)
