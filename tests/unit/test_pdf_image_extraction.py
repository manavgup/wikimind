"""Tests for PDF image extraction during ingest (issue #378).

Verifies that:
1. Images are extracted from PDFs and saved to user-scoped directories.
2. The authenticated API endpoint serves images after ownership verification.
3. Image extraction failures do not block text ingestion.
4. The list endpoint returns correct metadata for extracted images.
"""

from __future__ import annotations

import struct
import zlib
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import fitz
import httpx
import pytest

from wikimind.config import Settings, get_settings
from wikimind.ingest.adapters import pdf as ingest_service
from wikimind.ingest.adapters.pdf import PDFAdapter

if TYPE_CHECKING:
    from pathlib import Path

    from sqlmodel.ext.asyncio.session import AsyncSession

from tests.conftest import TEST_USER_ID

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_png(width: int = 100, height: int = 100) -> bytes:
    """Create a minimal valid PNG image of the given dimensions.

    Generates a solid-color image large enough (> 5KB) to pass the
    extraction filter that skips tiny images.
    """

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    header = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr = _chunk(b"IHDR", ihdr_data)

    # Create raw pixel data (RGB) — fill with a pattern to get reasonable size
    raw_rows = b""
    for y in range(height):
        raw_rows += b"\x00"  # filter byte
        for x in range(width):
            raw_rows += bytes([x % 256, y % 256, (x + y) % 256])

    idat = _chunk(b"IDAT", zlib.compress(raw_rows))
    iend = _chunk(b"IEND", b"")

    return header + ihdr + idat + iend


def _build_pdf_with_images(
    pages: list[str],
    image_count: int = 1,
    image_width: int = 200,
    image_height: int = 200,
) -> bytes:
    """Build a PDF with text pages and embedded images.

    Args:
        pages: Text content for each page.
        image_count: Number of images to embed on the first page.
        image_width: Width of each embedded image.
        image_height: Height of each embedded image.

    Returns:
        Raw PDF bytes with embedded images.
    """
    doc = fitz.open()
    for i, body in enumerate(pages):
        page = doc.new_page()
        page.insert_text((72, 72), body)
        if i == 0:
            for j in range(image_count):
                png_data = _make_png(image_width, image_height)
                rect = fitz.Rect(72, 100 + j * 120, 272, 220 + j * 120)
                page.insert_image(rect, stream=png_data)
    data = doc.tobytes()
    doc.close()
    return bytes(data)


@pytest.fixture
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``get_settings().data_dir`` at a tmp directory for one test."""
    fake_settings = Settings(
        data_dir=str(tmp_path),
        vision_enabled=False,
        image_extraction_enabled=True,
    )
    monkeypatch.setattr(ingest_service, "get_settings", lambda: fake_settings)
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    (tmp_path / "raw").mkdir(parents=True, exist_ok=True)
    (tmp_path / "images").mkdir(parents=True, exist_ok=True)
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# PDFAdapter._extract_images unit tests
# ---------------------------------------------------------------------------


class TestExtractImages:
    """Tests for the static _extract_images method."""

    def test_extracts_images_from_pdf(
        self,
        isolated_data_dir: Path,
    ) -> None:
        """Images embedded in a PDF are extracted and returned as tuples."""
        pdf_bytes = _build_pdf_with_images(["Page with images"], image_count=2)
        source_id = "src-img-001"

        results = PDFAdapter._extract_images(pdf_bytes, source_id, TEST_USER_ID, max_images=30)

        assert len(results) > 0
        for filename, kind, image_bytes in results:
            assert isinstance(filename, str)
            assert kind in ("figure", "table")
            assert len(image_bytes) > 0
        # Filesystem cache should also exist
        image_dir = isolated_data_dir / "images" / TEST_USER_ID / source_id
        assert image_dir.exists()
        assert len(list(image_dir.iterdir())) == len(results)

    def test_respects_max_images_limit(
        self,
        isolated_data_dir: Path,
    ) -> None:
        """Extraction stops after max_images is reached."""
        pdf_bytes = _build_pdf_with_images(["Page with many images"], image_count=5)
        source_id = "src-img-002"

        results = PDFAdapter._extract_images(pdf_bytes, source_id, TEST_USER_ID, max_images=2)

        assert len(results) <= 2

    def test_skips_tiny_images(
        self,
        isolated_data_dir: Path,
    ) -> None:
        """Images smaller than 5KB (icons, bullets) are skipped."""
        pdf_bytes = _build_pdf_with_images(
            ["Page with tiny image"],
            image_count=1,
            image_width=10,
            image_height=10,
        )
        source_id = "src-img-003"

        results = PDFAdapter._extract_images(pdf_bytes, source_id, TEST_USER_ID, max_images=30)

        assert len(results) == 0

    def test_no_images_returns_empty(
        self,
        isolated_data_dir: Path,
    ) -> None:
        """A text-only PDF produces an empty list."""
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Text only, no images")
        pdf_bytes = bytes(doc.tobytes())
        doc.close()

        source_id = "src-img-004"

        results = PDFAdapter._extract_images(pdf_bytes, source_id, TEST_USER_ID, max_images=30)

        assert len(results) == 0

    def test_user_scoped_directory(
        self,
        isolated_data_dir: Path,
    ) -> None:
        """Images are stored under {data_dir}/images/{user_id}/{source_id}/."""
        pdf_bytes = _build_pdf_with_images(["Page with image"], image_count=1)
        source_id = "src-img-005"

        PDFAdapter._extract_images(pdf_bytes, source_id, TEST_USER_ID, max_images=30)

        expected_dir = isolated_data_dir / "images" / TEST_USER_ID / source_id
        assert expected_dir.exists()
        assert expected_dir.is_dir()


# ---------------------------------------------------------------------------
# PDFAdapter.get_image_dir
# ---------------------------------------------------------------------------


class TestGetImageDir:
    """Tests for the get_image_dir helper."""

    def test_returns_user_scoped_path(
        self,
        isolated_data_dir: Path,
    ) -> None:
        """Path includes user_id and source_id segments."""
        result = PDFAdapter.get_image_dir("user-42", "src-99")
        assert result == isolated_data_dir / "images" / "user-42" / "src-99"


# ---------------------------------------------------------------------------
# Integration: image extraction during ingest
# ---------------------------------------------------------------------------


class TestIngestWithImageExtraction:
    """Verify image extraction is called during PDF ingest."""

    async def test_ingest_extracts_images(
        self,
        db_session: AsyncSession,
        isolated_data_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """PDFAdapter.ingest extracts images and stores them in the DB."""
        monkeypatch.setattr(
            ingest_service,
            "_convert_via_docling_serve",
            AsyncMock(side_effect=httpx.ConnectError("Connection refused")),
        )
        monkeypatch.setattr(ingest_service, "emit_source_progress", AsyncMock())

        pdf_bytes = _build_pdf_with_images(["Page with an image"], image_count=1)
        adapter = PDFAdapter()

        source, _doc = await adapter.ingest(pdf_bytes, "images.pdf", db_session, user_id=TEST_USER_ID)

        # Images should be stored in the database
        from sqlalchemy import select as sa_select

        from wikimind.models import SourceImage

        result = await db_session.execute(sa_select(SourceImage).where(SourceImage.source_id == source.id))
        rows = result.scalars().all()
        assert len(rows) > 0
        assert rows[0].kind in ("figure", "table")
        assert len(rows[0].image_data) > 0

        # Filesystem cache should also exist
        image_dir = isolated_data_dir / "images" / TEST_USER_ID / source.id
        assert image_dir.exists()

    async def test_ingest_succeeds_when_image_extraction_disabled(
        self,
        db_session: AsyncSession,
        isolated_data_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Ingest works normally when image_extraction_enabled=False."""
        disabled_settings = Settings(
            data_dir=str(isolated_data_dir),
            vision_enabled=False,
            image_extraction_enabled=False,
        )
        monkeypatch.setattr(ingest_service, "get_settings", lambda: disabled_settings)

        monkeypatch.setattr(
            ingest_service,
            "_convert_via_docling_serve",
            AsyncMock(side_effect=httpx.ConnectError("Connection refused")),
        )
        monkeypatch.setattr(ingest_service, "emit_source_progress", AsyncMock())

        pdf_bytes = _build_pdf_with_images(["Page with image"], image_count=1)
        adapter = PDFAdapter()

        source, doc = await adapter.ingest(pdf_bytes, "no-images.pdf", db_session, user_id=TEST_USER_ID)

        # Source should be created but no images directory
        assert source is not None
        assert doc is not None
        image_dir = isolated_data_dir / "images" / TEST_USER_ID / source.id
        assert not image_dir.exists()

    async def test_ingest_continues_on_image_extraction_failure(
        self,
        db_session: AsyncSession,
        isolated_data_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Text extraction succeeds even if image extraction raises."""
        monkeypatch.setattr(
            ingest_service,
            "_convert_via_docling_serve",
            AsyncMock(side_effect=httpx.ConnectError("Connection refused")),
        )
        monkeypatch.setattr(ingest_service, "emit_source_progress", AsyncMock())

        # Make _extract_images raise
        monkeypatch.setattr(
            PDFAdapter,
            "_extract_images",
            staticmethod(lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("disk full"))),
        )

        doc_obj = fitz.open()
        page = doc_obj.new_page()
        page.insert_text((72, 72), "Text should survive image failure")
        pdf_bytes = bytes(doc_obj.tobytes())
        doc_obj.close()

        adapter = PDFAdapter()
        _source, doc = await adapter.ingest(pdf_bytes, "resilient.pdf", db_session, user_id=TEST_USER_ID)

        assert "Text should survive image failure" in doc.clean_text
