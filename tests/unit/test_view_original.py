"""Tests for the GET /ingest/sources/{id}/original endpoint."""

from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from wikimind.database import get_session
from wikimind.main import app
from wikimind.models import Source, SourceType
from wikimind.services.ingest import get_ingest_service


@pytest.fixture
def source_with_pdf():
    return Source(
        id="src-pdf",
        source_type=SourceType.PDF,
        file_path="src-pdf.txt",
        title="Test PDF",
    )


@pytest.fixture
def source_text_only():
    return Source(
        id="src-text",
        source_type=SourceType.TEXT,
        file_path="src-text.txt",
        title="Test Text",
    )


async def _fake_session() -> AsyncGenerator:
    """Minimal session override that satisfies FastAPI DI without a real DB."""
    yield AsyncMock()


async def test_original_endpoint_streams_pdf(tmp_path: Path, source_with_pdf: Source) -> None:
    """Endpoint returns PDF bytes with correct Content-Type."""
    pdf_bytes = b"%PDF-1.4 fake pdf content"
    (tmp_path / "src-pdf.txt").write_text("extracted text")
    (tmp_path / "src-pdf.pdf").write_bytes(pdf_bytes)

    mock_svc = AsyncMock()
    mock_svc.get_source = AsyncMock(return_value=source_with_pdf)

    app.dependency_overrides[get_session] = _fake_session
    app.dependency_overrides[get_ingest_service] = lambda: mock_svc

    try:
        with patch(
            "wikimind.api.routes.ingest.resolve_raw_path",
            return_value=tmp_path / "src-pdf.txt",
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/ingest/sources/src-pdf/original")
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_ingest_service, None)

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content == pdf_bytes


async def test_original_endpoint_404_for_text_source(tmp_path: Path, source_text_only: Source) -> None:
    """Endpoint returns 404 when no original sibling exists."""
    (tmp_path / "src-text.txt").write_text("just text")

    mock_svc = AsyncMock()
    mock_svc.get_source = AsyncMock(return_value=source_text_only)

    app.dependency_overrides[get_session] = _fake_session
    app.dependency_overrides[get_ingest_service] = lambda: mock_svc

    try:
        with patch(
            "wikimind.api.routes.ingest.resolve_raw_path",
            return_value=tmp_path / "src-text.txt",
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/ingest/sources/src-text/original")
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_ingest_service, None)

    assert resp.status_code == 404
