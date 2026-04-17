"""Tests for the PDF ingest adapter — covers both docling and fitz branches.

The adapter prefers docling when available and falls back to fitz plain-text
extraction otherwise (see issue #57). Both branches must produce a valid
``NormalizedDocument`` and honour the dual-file lineage convention from
issue #59 (raw ``.pdf`` + cleaned ``.txt`` on disk).

Issue #117 adds batched extraction with page-range and WebSocket progress
emission. Those tests verify that the converter is called with page_range
per batch and that ``emit_source_progress`` fires between batches.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call

import fitz
import pytest

from wikimind.config import Settings, get_settings
from wikimind.ingest import service as ingest_service
from wikimind.ingest.service import PDFAdapter
from wikimind.models import IngestStatus, NormalizedDocument, Source, SourceType
from wikimind.storage import get_raw_storage, get_wiki_storage

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
    get_wiki_storage.cache_clear()
    get_raw_storage.cache_clear()
    yield tmp_path
    get_settings.cache_clear()
    get_wiki_storage.cache_clear()
    get_raw_storage.cache_clear()


# ---------------------------------------------------------------------------
# Fitz fallback path — what every CI run exercises today
# ---------------------------------------------------------------------------


class TestPDFAdapterFitzFallback:
    """Behaviour when docling is not installed (the CI default)."""

    async def test_fitz_extract_static_helper(self) -> None:
        """``_extract_via_fitz`` returns plain text and the page count."""
        pdf_bytes = _build_pdf_bytes(["Hello world", "Second page body"])

        clean_text, page_count = PDFAdapter._extract_via_fitz(pdf_bytes)

        assert page_count == 2
        assert "Hello world" in clean_text
        assert "Second page body" in clean_text
        # Pages are joined with a blank line — preserves the pre-#57 format.
        assert "\n\n" in clean_text

    async def test_ingest_uses_fitz_when_docling_missing(
        self,
        db_session,
        isolated_data_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When ``_DOCLING_AVAILABLE`` is False the fitz branch produces a doc."""
        monkeypatch.setattr(ingest_service, "_DOCLING_AVAILABLE", False)

        pdf_bytes = _build_pdf_bytes(["Fallback page text"])
        adapter = PDFAdapter()

        source, doc = await adapter.ingest(pdf_bytes, "fallback.pdf", db_session)

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
        monkeypatch.setattr(ingest_service, "_DOCLING_AVAILABLE", False)

        pdf_bytes = _build_pdf_bytes(["Lineage check page"])
        adapter = PDFAdapter()

        source, _doc = await adapter.ingest(pdf_bytes, "lineage.pdf", db_session)

        raw_pdf = isolated_data_dir / "raw" / f"{source.id}.pdf"
        raw_txt = isolated_data_dir / "raw" / f"{source.id}.txt"

        assert raw_pdf.exists(), "raw .pdf binary should be saved alongside .txt"
        assert raw_pdf.read_bytes() == pdf_bytes
        assert raw_txt.exists(), "cleaned .txt should be saved for the worker"
        assert "Lineage check page" in raw_txt.read_text(encoding="utf-8")
        assert source.file_path == f"{source.id}.txt"


# ---------------------------------------------------------------------------
# Docling path — exercised by mocking the converter (docling not in CI)
# ---------------------------------------------------------------------------


class TestPDFAdapterDoclingPath:
    """Behaviour when docling is available — converter is mocked."""

    async def test_extract_via_docling_calls_converter(
        self,
        isolated_data_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``_extract_via_docling`` delegates to the singleton converter."""
        fake_doc = MagicMock()
        fake_doc.export_to_markdown.return_value = "# Heading\n\nBody text\n"
        fake_doc.pages = [object(), object(), object()]

        fake_result = MagicMock()
        fake_result.document = fake_doc

        fake_converter = MagicMock()
        fake_converter.convert.return_value = fake_result

        monkeypatch.setattr(
            ingest_service,
            "_get_docling_converter",
            lambda: fake_converter,
        )

        raw_pdf = isolated_data_dir / "raw" / "fake.pdf"
        raw_pdf.write_bytes(b"%PDF-1.4 fake")

        clean_text, page_count = PDFAdapter._extract_via_docling(raw_pdf)

        fake_converter.convert.assert_called_once_with(str(raw_pdf))
        assert clean_text == "# Heading\n\nBody text\n"
        assert page_count == 3

    async def test_ingest_uses_docling_when_available(
        self,
        db_session,
        isolated_data_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When ``_DOCLING_AVAILABLE`` is True the batched docling branch is taken."""
        monkeypatch.setattr(ingest_service, "_DOCLING_AVAILABLE", True)

        markdown = "# Slide deck\n\n## Section one\n\nA structured body.\n"
        fake_doc = MagicMock()
        fake_doc.export_to_markdown.return_value = markdown
        fake_doc.pages = [object()]
        fake_result = MagicMock()
        fake_result.document = fake_doc
        fake_converter = MagicMock()
        fake_converter.convert.return_value = fake_result
        monkeypatch.setattr(
            ingest_service,
            "_get_docling_converter",
            lambda: fake_converter,
        )

        mock_emit = AsyncMock()
        monkeypatch.setattr(ingest_service, "emit_source_progress", mock_emit)

        pdf_bytes = _build_pdf_bytes(["ignored — docling reads the file path"])
        adapter = PDFAdapter()

        source, doc = await adapter.ingest(pdf_bytes, "deck.pdf", db_session)

        # The converter must have been invoked against the saved raw .pdf
        # with a page_range kwarg (batched path).
        raw_pdf_path = isolated_data_dir / "raw" / f"{source.id}.pdf"
        fake_converter.convert.assert_called_once_with(str(raw_pdf_path), page_range=(1, 1))

        assert doc.clean_text == markdown
        assert "# Slide deck" in doc.clean_text
        assert source.file_path == f"{source.id}.txt"
        assert (isolated_data_dir / "raw" / f"{source.id}.txt").read_text(encoding="utf-8") == markdown


# ---------------------------------------------------------------------------
# Module-level detection flag
# ---------------------------------------------------------------------------


class TestDoclingDetectionFlag:
    def test_module_constant_is_boolean(self) -> None:
        """``_DOCLING_AVAILABLE`` is set at import time and is a bool."""
        assert isinstance(ingest_service._DOCLING_AVAILABLE, bool)

    def test_get_converter_raises_when_unavailable(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Calling ``_get_docling_converter`` without docling raises clearly."""
        monkeypatch.setattr(ingest_service, "_DocumentConverter", None)
        monkeypatch.setattr(ingest_service, "_docling_converter", None)

        with pytest.raises(RuntimeError, match="Docling is not installed"):
            ingest_service._get_docling_converter()


# ---------------------------------------------------------------------------
# Batched Docling extraction with progress (issue #117)
# ---------------------------------------------------------------------------


def _make_fake_converter(markdown_per_call: list[str]) -> MagicMock:
    """Build a mock Docling converter that returns successive markdown strings.

    Each call to ``converter.convert(...)`` pops the next string from the
    list and wraps it in the expected result object shape.
    """
    call_iter = iter(markdown_per_call)
    converter = MagicMock()

    def _side_effect(*args, **kwargs):
        md = next(call_iter)
        fake_doc = MagicMock()
        fake_doc.export_to_markdown.return_value = md
        fake_result = MagicMock()
        fake_result.document = fake_doc
        return fake_result

    converter.convert.side_effect = _side_effect
    return converter


class TestBatchedDoclingExtraction:
    """Tests for ``_extract_via_docling_batched`` (issue #117)."""

    async def test_single_batch_small_pdf(
        self,
        isolated_data_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A PDF with fewer pages than batch_size converts in one call."""
        # Create a 3-page PDF
        pdf_bytes = _build_pdf_bytes(["p1", "p2", "p3"])
        raw_pdf = isolated_data_dir / "raw" / "small.pdf"
        raw_pdf.write_bytes(pdf_bytes)

        fake_converter = _make_fake_converter(["# Batch1\n\nAll three pages."])
        monkeypatch.setattr(ingest_service, "_get_docling_converter", lambda: fake_converter)

        fake_settings = Settings(data_dir=str(isolated_data_dir), docling_batch_pages=10)
        monkeypatch.setattr(ingest_service, "get_settings", lambda: fake_settings)

        mock_emit = AsyncMock()
        monkeypatch.setattr(ingest_service, "emit_source_progress", mock_emit)

        adapter = PDFAdapter()
        markdown, page_count = await adapter._extract_via_docling_batched(raw_pdf, "src-123")

        assert page_count == 3
        assert "# Batch1" in markdown
        # Single batch: converter called once with page_range=(1, 3)
        fake_converter.convert.assert_called_once_with(str(raw_pdf), page_range=(1, 3))
        # Progress: initial message + one batch message
        assert mock_emit.await_count == 2
        assert mock_emit.call_args_list[0] == call("src-123", "Extracting PDF (3 pages)...")
        assert mock_emit.call_args_list[1] == call("src-123", "Extracting pages 3/3...")

    async def test_multiple_batches(
        self,
        isolated_data_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A PDF with more pages than batch_size is split into batches."""
        # Create a 5-page PDF with batch_size=2 => 3 batches: (1,2), (3,4), (5,5)
        pdf_bytes = _build_pdf_bytes(["p1", "p2", "p3", "p4", "p5"])
        raw_pdf = isolated_data_dir / "raw" / "multi.pdf"
        raw_pdf.write_bytes(pdf_bytes)

        fake_converter = _make_fake_converter(
            [
                "# Batch 1\n",
                "# Batch 2\n",
                "# Batch 3\n",
            ]
        )
        monkeypatch.setattr(ingest_service, "_get_docling_converter", lambda: fake_converter)

        fake_settings = Settings(data_dir=str(isolated_data_dir), docling_batch_pages=2)
        monkeypatch.setattr(ingest_service, "get_settings", lambda: fake_settings)

        mock_emit = AsyncMock()
        monkeypatch.setattr(ingest_service, "emit_source_progress", mock_emit)

        adapter = PDFAdapter()
        markdown, page_count = await adapter._extract_via_docling_batched(raw_pdf, "src-456")

        assert page_count == 5
        assert "# Batch 1" in markdown
        assert "# Batch 2" in markdown
        assert "# Batch 3" in markdown

        # Converter called 3 times with correct page ranges
        assert fake_converter.convert.call_count == 3
        calls = fake_converter.convert.call_args_list
        assert calls[0] == call(str(raw_pdf), page_range=(1, 2))
        assert calls[1] == call(str(raw_pdf), page_range=(3, 4))
        assert calls[2] == call(str(raw_pdf), page_range=(5, 5))

        # Progress: initial message + 3 batch messages
        assert mock_emit.await_count == 4
        assert mock_emit.call_args_list[0] == call("src-456", "Extracting PDF (5 pages)...")
        assert mock_emit.call_args_list[1] == call("src-456", "Extracting pages 2/5...")
        assert mock_emit.call_args_list[2] == call("src-456", "Extracting pages 4/5...")
        assert mock_emit.call_args_list[3] == call("src-456", "Extracting pages 5/5...")

    async def test_ingest_uses_batched_when_docling_available(
        self,
        db_session,
        isolated_data_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``ingest()`` calls the batched method when docling is available."""
        monkeypatch.setattr(ingest_service, "_DOCLING_AVAILABLE", True)

        markdown = "# Batched output\n\nStructured body.\n"
        fake_converter = _make_fake_converter([markdown])
        monkeypatch.setattr(ingest_service, "_get_docling_converter", lambda: fake_converter)

        mock_emit = AsyncMock()
        monkeypatch.setattr(ingest_service, "emit_source_progress", mock_emit)

        pdf_bytes = _build_pdf_bytes(["single page"])
        adapter = PDFAdapter()

        source, doc = await adapter.ingest(pdf_bytes, "batched.pdf", db_session)

        assert isinstance(source, Source)
        assert isinstance(doc, NormalizedDocument)
        assert "# Batched output" in doc.clean_text
        # The emit function was called (progress was emitted)
        assert mock_emit.await_count >= 2  # at least start + completion
