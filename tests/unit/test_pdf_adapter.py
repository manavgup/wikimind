"""Tests for the PDF ingest adapter — covers docling-serve and fitz branches.

The adapter prefers docling-serve (HTTP sidecar) for structured extraction and
falls back to fitz plain-text extraction when the sidecar is unavailable.

Both branches must produce a valid ``NormalizedDocument`` and honour the
dual-file lineage convention from issue #59 (raw ``.pdf`` + cleaned ``.txt``
on disk).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import fitz
import httpx
import pytest

from wikimind.config import Settings, get_settings
from wikimind.ingest.adapters import pdf as ingest_service
from wikimind.ingest.adapters.pdf import PDFAdapter
from wikimind.models import IngestStatus, NormalizedDocument, Source, SourceType

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _build_pdf_bytes(pages: list[str]) -> bytes:
    """Construct a tiny in-memory PDF using fitz with one page per string.

    Args:
        pages: One string per page; the string is rendered as plain text.

    Returns:
        Raw PDF bytes ready to feed to ``PDFAdapter.ingest``.
    """
    doc = fitz.open()
    for body in pages:
        page = doc.new_page()
        page.insert_text((72, 72), body)
    data = doc.tobytes()
    doc.close()
    return bytes(data)


@pytest.fixture
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``get_settings().data_dir`` at a tmp directory for one test.

    The settings function is ``lru_cache``d, so we override it on the
    ``ingest.service`` module attribute the adapter actually calls instead of
    trying to bust the cache.
    """
    fake_settings = Settings(data_dir=str(tmp_path), vision_enabled=False)
    monkeypatch.setattr(ingest_service, "get_settings", lambda: fake_settings)
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    # Pre-create raw_dir so the assertions can rely on it existing.
    (tmp_path / "raw").mkdir(parents=True, exist_ok=True)
    # Drop the global lru_cache too in case anything else hits it during the
    # test (defensive — the monkeypatch above is the primary mechanism).
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Fitz fallback path — when docling-serve is unavailable
# ---------------------------------------------------------------------------


class TestPDFAdapterFitzFallback:
    """Behaviour when docling-serve is not available (connection refused)."""

    async def test_fitz_extract_static_helper(self) -> None:
        """``_extract_via_fitz`` returns plain text and the page count."""
        pdf_bytes = _build_pdf_bytes(["Hello world", "Second page body"])

        clean_text, page_count = PDFAdapter._extract_via_fitz(pdf_bytes)

        assert page_count == 2
        assert "Hello world" in clean_text
        assert "Second page body" in clean_text
        # Pages are joined with a blank line — preserves the pre-#57 format.
        assert "\n\n" in clean_text

    async def test_ingest_falls_back_to_fitz_when_docling_serve_down(
        self,
        db_session,
        isolated_data_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When docling-serve is unreachable the fitz branch produces a doc."""
        # Make _convert_via_docling_serve raise a connection error
        monkeypatch.setattr(
            ingest_service,
            "_convert_via_docling_serve",
            AsyncMock(side_effect=httpx.ConnectError("Connection refused")),
        )

        mock_emit = AsyncMock()
        monkeypatch.setattr(ingest_service, "emit_source_progress", mock_emit)

        pdf_bytes = _build_pdf_bytes(["Fallback page text"])
        adapter = PDFAdapter()

        source, doc = await adapter.ingest(pdf_bytes, "fallback.pdf", db_session, user_id="test-user")

        assert isinstance(source, Source)
        assert isinstance(doc, NormalizedDocument)
        assert source.source_type == SourceType.PDF
        assert source.title == "fallback"
        assert source.status == IngestStatus.PROCESSING
        assert "Fallback page text" in doc.clean_text
        assert doc.estimated_tokens > 0
        assert doc.chunks  # at least one chunk

    async def test_ingest_writes_dual_files(
        self,
        db_session,
        isolated_data_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Both the raw ``.pdf`` and the cleaned ``.txt`` must be persisted."""
        # Make docling-serve unavailable
        monkeypatch.setattr(
            ingest_service,
            "_convert_via_docling_serve",
            AsyncMock(side_effect=httpx.ConnectError("Connection refused")),
        )

        mock_emit = AsyncMock()
        monkeypatch.setattr(ingest_service, "emit_source_progress", mock_emit)

        pdf_bytes = _build_pdf_bytes(["Lineage check page"])
        adapter = PDFAdapter()

        source, _doc = await adapter.ingest(pdf_bytes, "lineage.pdf", db_session, user_id="test-user")

        raw_pdf = isolated_data_dir / "raw" / "test-user" / f"{source.id}.pdf"
        raw_txt = isolated_data_dir / "raw" / "test-user" / f"{source.id}.txt"

        assert raw_pdf.exists(), "raw .pdf binary should be saved alongside .txt"
        assert raw_pdf.read_bytes() == pdf_bytes
        assert raw_txt.exists(), "cleaned .txt should be saved for the worker"
        assert "Lineage check page" in raw_txt.read_text(encoding="utf-8")
        assert source.file_path == f"{source.id}.txt"


# ---------------------------------------------------------------------------
# Docling-serve path — exercised by mocking the HTTP client
# ---------------------------------------------------------------------------


class TestPDFAdapterDoclingServePath:
    """Behaviour when docling-serve is available — HTTP call is mocked."""

    async def test_extract_via_docling_calls_sidecar(
        self,
        isolated_data_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``_extract_via_docling`` delegates to docling-serve HTTP API."""
        markdown = "# Heading\n\nBody text\n"

        monkeypatch.setattr(
            ingest_service,
            "_convert_via_docling_serve",
            AsyncMock(return_value=markdown),
        )

        mock_emit = AsyncMock()
        monkeypatch.setattr(ingest_service, "emit_source_progress", mock_emit)

        # Create a 3-page PDF to verify page count comes from fitz
        pdf_bytes = _build_pdf_bytes(["p1", "p2", "p3"])
        raw_pdf = isolated_data_dir / "raw" / "fake.pdf"
        raw_pdf.write_bytes(pdf_bytes)

        adapter = PDFAdapter()
        clean_text, page_count = await adapter._extract_via_docling(raw_pdf, "src-123", user_id="test-user")

        assert clean_text == markdown
        assert page_count == 3
        # Progress was emitted
        assert mock_emit.await_count == 2

    async def test_ingest_uses_docling_serve_when_available(
        self,
        db_session,
        isolated_data_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When docling-serve responds, its markdown is used."""
        markdown = "# Slide deck\n\n## Section one\n\nA structured body.\n"

        monkeypatch.setattr(
            ingest_service,
            "_convert_via_docling_serve",
            AsyncMock(return_value=markdown),
        )

        mock_emit = AsyncMock()
        monkeypatch.setattr(ingest_service, "emit_source_progress", mock_emit)

        pdf_bytes = _build_pdf_bytes(["ignored — docling-serve reads the file path"])
        adapter = PDFAdapter()

        source, doc = await adapter.ingest(pdf_bytes, "deck.pdf", db_session, user_id="test-user")

        assert doc.clean_text == markdown
        assert "# Slide deck" in doc.clean_text
        assert source.file_path == f"{source.id}.txt"
        assert (isolated_data_dir / "raw" / "test-user" / f"{source.id}.txt").read_text(encoding="utf-8") == markdown


# ---------------------------------------------------------------------------
# _convert_via_docling_serve unit test (HTTP layer)
# ---------------------------------------------------------------------------


class TestConvertViaDoclingServe:
    """Tests for the HTTP client function."""

    async def test_successful_conversion(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A successful HTTP response extracts md_content."""
        fake_settings = Settings(data_dir=str(tmp_path), docling_serve_url="http://localhost:5001")
        monkeypatch.setattr(ingest_service, "get_settings", lambda: fake_settings)
        get_settings.cache_clear()

        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_build_pdf_bytes(["hello"]))

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"document": {"md_content": "# Converted\n\nBody text."}}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.object(ingest_service.httpx, "AsyncClient", return_value=mock_client):
            result = await ingest_service._convert_via_docling_serve(pdf_path)

        assert result == "# Converted\n\nBody text."
        mock_client.post.assert_awaited_once()

        get_settings.cache_clear()

    async def test_http_error_propagates(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """HTTP errors are propagated to trigger fallback."""
        fake_settings = Settings(data_dir=str(tmp_path), docling_serve_url="http://localhost:5001")
        monkeypatch.setattr(ingest_service, "get_settings", lambda: fake_settings)
        get_settings.cache_clear()

        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_bytes(_build_pdf_bytes(["hello"]))

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500 Internal Server Error",
            request=MagicMock(),
            response=MagicMock(),
        )

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)

        with (
            patch.object(ingest_service.httpx, "AsyncClient", return_value=mock_client),
            pytest.raises(httpx.HTTPStatusError),
        ):
            await ingest_service._convert_via_docling_serve(pdf_path)

        get_settings.cache_clear()
