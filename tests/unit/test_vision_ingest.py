"""Tests for vision-enhanced slide deck ingestion (issue #68).

Covers:
- Page classification (dense vs sparse based on text threshold)
- Image rendering from PDF pages
- Merge logic combining extracted text with LLM descriptions
- End-to-end vision enhancement pipeline with mocked LLM
- Kill switch (vision_enabled=False disables the feature)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import fitz
import pytest

from wikimind.config import Settings, get_settings
from wikimind.ingest import service as ingest_service
from wikimind.ingest.service import PDFAdapter
from wikimind.models import CompletionResponse, Provider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_pdf_bytes(pages: list[str]) -> bytes:
    """Construct a tiny in-memory PDF with one page per string.

    Args:
        pages: One string per page; the string is rendered as plain text.

    Returns:
        Raw PDF bytes.
    """
    doc = fitz.open()
    for body in pages:
        page = doc.new_page()
        if body:
            page.insert_text((72, 72), body)
    data = doc.tobytes()
    doc.close()
    return bytes(data)


def _build_sparse_and_dense_pdf() -> bytes:
    """Build a PDF with one dense page and two sparse pages."""
    # Dense page: lots of text (> 300 chars)
    dense_text = "This is a long paragraph of text. " * 20  # ~680 chars
    # Sparse pages: minimal text (< 300 chars)
    sparse_text_1 = "Title Slide"
    sparse_text_2 = ""  # Completely empty — pure visual
    return _build_pdf_bytes([dense_text, sparse_text_1, sparse_text_2])


@pytest.fixture
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point settings at a tmp directory for one test."""
    fake_settings = Settings(data_dir=str(tmp_path))
    monkeypatch.setattr(ingest_service, "get_settings", lambda: fake_settings)
    (tmp_path / "raw").mkdir(parents=True, exist_ok=True)
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Page classification tests
# ---------------------------------------------------------------------------


class TestClassifyPages:
    """Tests for PDFAdapter._classify_pages."""

    def test_all_dense(self) -> None:
        """All pages above threshold are classified as dense."""
        texts = ["x" * 400, "y" * 500, "z" * 300]
        dense, sparse = PDFAdapter._classify_pages(texts, threshold=300)
        assert dense == [0, 1, 2]
        assert sparse == []

    def test_all_sparse(self) -> None:
        """All pages below threshold are classified as sparse."""
        texts = ["short", "", "hi"]
        dense, sparse = PDFAdapter._classify_pages(texts, threshold=300)
        assert dense == []
        assert sparse == [0, 1, 2]

    def test_mixed(self) -> None:
        """Mix of dense and sparse pages is correctly separated."""
        texts = ["x" * 400, "short", "y" * 350, ""]
        dense, sparse = PDFAdapter._classify_pages(texts, threshold=300)
        assert dense == [0, 2]
        assert sparse == [1, 3]

    def test_threshold_boundary(self) -> None:
        """Page with exactly threshold chars is classified as dense."""
        texts = ["x" * 300, "x" * 299]
        dense, sparse = PDFAdapter._classify_pages(texts, threshold=300)
        assert dense == [0]
        assert sparse == [1]

    def test_whitespace_only_is_sparse(self) -> None:
        """A page with only whitespace is classified as sparse."""
        texts = ["   \n\t\n   "]
        dense, sparse = PDFAdapter._classify_pages(texts, threshold=300)
        assert dense == []
        assert sparse == [0]


# ---------------------------------------------------------------------------
# Per-page text extraction
# ---------------------------------------------------------------------------


class TestExtractPerPageText:
    """Tests for PDFAdapter._extract_per_page_text."""

    def test_extracts_text_per_page(self) -> None:
        """Each page's text is extracted independently."""
        pdf_bytes = _build_pdf_bytes(["Page one text", "Page two text", "Page three"])
        result = PDFAdapter._extract_per_page_text(pdf_bytes)

        assert len(result) == 3
        assert "Page one text" in result[0]
        assert "Page two text" in result[1]
        assert "Page three" in result[2]

    def test_empty_page_returns_empty_string(self) -> None:
        """A blank page yields an empty or whitespace-only string."""
        pdf_bytes = _build_pdf_bytes(["content", ""])
        result = PDFAdapter._extract_per_page_text(pdf_bytes)

        assert len(result) == 2
        assert "content" in result[0]
        assert result[1].strip() == ""


# ---------------------------------------------------------------------------
# Image rendering
# ---------------------------------------------------------------------------


class TestRenderPagesAsImages:
    """Tests for PDFAdapter._render_pages_as_images."""

    def test_renders_requested_pages(self) -> None:
        """Only requested page indices are rendered."""
        pdf_bytes = _build_pdf_bytes(["p1", "p2", "p3", "p4"])
        images = PDFAdapter._render_pages_as_images(pdf_bytes, [1, 3], dpi=72)

        assert len(images) == 2
        # Each result should be valid PNG bytes (starts with PNG magic)
        for img in images:
            assert img[:8] == b"\x89PNG\r\n\x1a\n"

    def test_empty_indices(self) -> None:
        """No indices means no images rendered."""
        pdf_bytes = _build_pdf_bytes(["p1"])
        images = PDFAdapter._render_pages_as_images(pdf_bytes, [], dpi=72)
        assert images == []

    def test_dpi_affects_size(self) -> None:
        """Higher DPI produces larger images."""
        pdf_bytes = _build_pdf_bytes(["Some text on this page"])
        low_dpi = PDFAdapter._render_pages_as_images(pdf_bytes, [0], dpi=72)
        high_dpi = PDFAdapter._render_pages_as_images(pdf_bytes, [0], dpi=150)

        assert len(high_dpi[0]) > len(low_dpi[0])


# ---------------------------------------------------------------------------
# Merge logic
# ---------------------------------------------------------------------------


class TestMergeTextAndDescriptions:
    """Tests for PDFAdapter._merge_text_and_descriptions."""

    def test_dense_pages_unchanged(self) -> None:
        """Dense pages keep their original text."""
        per_page = ["Dense text here" * 30, "Short"]
        descriptions = {1: "A diagram showing workflow."}
        result = PDFAdapter._merge_text_and_descriptions(per_page, descriptions, [1])

        assert "Dense text here" in result
        assert "[Visual content]: A diagram showing workflow." in result

    def test_sparse_page_with_some_text(self) -> None:
        """Sparse page with minimal text includes both original and description."""
        per_page = ["Title Slide"]
        descriptions = {0: "Company logo and presentation title."}
        result = PDFAdapter._merge_text_and_descriptions(per_page, descriptions, [0])

        assert "Title Slide" in result
        assert "[Visual content]: Company logo and presentation title." in result

    def test_empty_sparse_page(self) -> None:
        """Completely empty sparse page shows only the description."""
        per_page = [""]
        descriptions = {0: "A complex architecture diagram."}
        result = PDFAdapter._merge_text_and_descriptions(per_page, descriptions, [0])

        assert "[Visual content]: A complex architecture diagram." in result

    def test_page_order_preserved(self) -> None:
        """Pages appear in document order regardless of classification."""
        per_page = ["Dense page 1" * 30, "Sparse", "Dense page 3" * 30]
        descriptions = {1: "Chart showing growth metrics."}
        result = PDFAdapter._merge_text_and_descriptions(per_page, descriptions, [1])

        # Verify ordering
        dense1_pos = result.find("Dense page 1")
        chart_pos = result.find("Chart showing growth metrics")
        dense3_pos = result.find("Dense page 3")
        assert dense1_pos < chart_pos < dense3_pos

    def test_no_sparse_pages(self) -> None:
        """When there are no sparse pages, text is unchanged."""
        per_page = ["Page 1 text", "Page 2 text"]
        descriptions: dict[int, str] = {}
        result = PDFAdapter._merge_text_and_descriptions(per_page, descriptions, [])

        assert "Page 1 text" in result
        assert "Page 2 text" in result
        assert "[Visual content]" not in result


# ---------------------------------------------------------------------------
# LLM description (mocked)
# ---------------------------------------------------------------------------


class TestDescribeImagesViaLLM:
    """Tests for PDFAdapter._describe_images_via_llm with mocked router."""

    async def test_single_batch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """All images fit in one batch — single LLM call."""
        mock_response = CompletionResponse(
            content="[Page 2]: A pie chart.\n\n[Page 4]: A workflow diagram.",
            provider_used=Provider.MOCK,
            model_used="mock-1",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.0,
            latency_ms=10,
        )
        mock_router = MagicMock()
        mock_router.complete_multimodal = AsyncMock(return_value=mock_response)
        monkeypatch.setattr(ingest_service, "get_llm_router", lambda: mock_router)

        images = [b"fake-png-1", b"fake-png-2"]
        page_indices = [1, 3]

        result = await PDFAdapter._describe_images_via_llm(images, page_indices, max_per_batch=20)

        assert 1 in result
        assert 3 in result
        assert "pie chart" in result[1]
        assert "workflow diagram" in result[3]
        mock_router.complete_multimodal.assert_awaited_once()

    async def test_multiple_batches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Images exceeding batch size are split into multiple LLM calls."""
        responses = [
            CompletionResponse(
                content="[Page 1]: Batch one description.",
                provider_used=Provider.MOCK,
                model_used="mock-1",
                input_tokens=50,
                output_tokens=25,
                cost_usd=0.0,
                latency_ms=5,
            ),
            CompletionResponse(
                content="[Page 3]: Batch two description.",
                provider_used=Provider.MOCK,
                model_used="mock-1",
                input_tokens=50,
                output_tokens=25,
                cost_usd=0.0,
                latency_ms=5,
            ),
        ]
        mock_router = MagicMock()
        mock_router.complete_multimodal = AsyncMock(side_effect=responses)
        monkeypatch.setattr(ingest_service, "get_llm_router", lambda: mock_router)

        images = [b"img-1", b"img-2"]
        page_indices = [0, 2]

        result = await PDFAdapter._describe_images_via_llm(images, page_indices, max_per_batch=1)

        assert mock_router.complete_multimodal.await_count == 2
        assert 0 in result
        assert 2 in result


# ---------------------------------------------------------------------------
# End-to-end _enhance_with_vision
# ---------------------------------------------------------------------------


class TestEnhanceWithVision:
    """Tests for the full _enhance_with_vision pipeline."""

    async def test_disabled_returns_original(
        self,
        monkeypatch: pytest.MonkeyPatch,
        isolated_data_dir: Path,
    ) -> None:
        """When vision_enabled=False, original text is returned unchanged."""
        fake_settings = Settings(data_dir=str(isolated_data_dir), vision_enabled=False)
        monkeypatch.setattr(ingest_service, "get_settings", lambda: fake_settings)

        adapter = PDFAdapter()
        pdf_bytes = _build_sparse_and_dense_pdf()

        result = await adapter._enhance_with_vision(pdf_bytes, "original text", "src-1")
        assert result == "original text"

    async def test_no_sparse_pages_returns_original(
        self,
        monkeypatch: pytest.MonkeyPatch,
        isolated_data_dir: Path,
    ) -> None:
        """When all pages are dense, no LLM call is made."""
        fake_settings = Settings(
            data_dir=str(isolated_data_dir),
            vision_enabled=True,
            vision_text_threshold=10,  # Very low threshold so all pages are dense
        )
        monkeypatch.setattr(ingest_service, "get_settings", lambda: fake_settings)

        mock_emit = AsyncMock()
        monkeypatch.setattr(ingest_service, "emit_source_progress", mock_emit)

        adapter = PDFAdapter()
        dense_text = "x" * 400
        pdf_bytes = _build_pdf_bytes([dense_text])

        result = await adapter._enhance_with_vision(pdf_bytes, dense_text, "src-2")
        assert result == dense_text

    async def test_sparse_pages_get_descriptions(
        self,
        monkeypatch: pytest.MonkeyPatch,
        isolated_data_dir: Path,
    ) -> None:
        """Sparse pages are described by the LLM and merged back in."""
        fake_settings = Settings(
            data_dir=str(isolated_data_dir),
            vision_enabled=True,
            vision_text_threshold=300,
            vision_dpi=72,
            vision_max_pages_per_batch=20,
        )
        monkeypatch.setattr(ingest_service, "get_settings", lambda: fake_settings)

        mock_emit = AsyncMock()
        monkeypatch.setattr(ingest_service, "emit_source_progress", mock_emit)

        mock_response = CompletionResponse(
            content="[Page 2]: A title slide with company logo.\n\n[Page 3]: Architecture diagram.",
            provider_used=Provider.MOCK,
            model_used="mock-1",
            input_tokens=200,
            output_tokens=100,
            cost_usd=0.0,
            latency_ms=50,
        )
        mock_router = MagicMock()
        mock_router.complete_multimodal = AsyncMock(return_value=mock_response)
        monkeypatch.setattr(ingest_service, "get_llm_router", lambda: mock_router)

        adapter = PDFAdapter()
        pdf_bytes = _build_sparse_and_dense_pdf()

        clean_text = "Original docling markdown with headings and structure."
        result = await adapter._enhance_with_vision(pdf_bytes, clean_text, "src-3")

        # The original clean_text is preserved (not rebuilt from fitz)
        assert "Original docling markdown" in result
        # The sparse pages should have LLM descriptions appended
        assert "[Visual content" in result
        assert "title slide with company logo" in result
        assert "Architecture diagram" in result
        # Progress was emitted
        mock_emit.assert_awaited()


# ---------------------------------------------------------------------------
# Integration with ingest() method
# ---------------------------------------------------------------------------


class TestVisionIntegrationWithIngest:
    """Test that the vision path is invoked during PDF ingest."""

    async def test_ingest_calls_enhance_with_vision(
        self,
        db_session,
        isolated_data_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The ingest method calls _enhance_with_vision after extraction."""
        monkeypatch.setattr(ingest_service, "_DOCLING_AVAILABLE", False)

        mock_enhance = AsyncMock(return_value="enhanced text from vision")
        monkeypatch.setattr(PDFAdapter, "_enhance_with_vision", mock_enhance)

        mock_emit = AsyncMock()
        monkeypatch.setattr(ingest_service, "emit_source_progress", mock_emit)

        pdf_bytes = _build_pdf_bytes(["Some page content"])
        adapter = PDFAdapter()

        _source, doc = await adapter.ingest(pdf_bytes, "vision-test.pdf", db_session)

        mock_enhance.assert_awaited_once()
        assert doc.clean_text == "enhanced text from vision"

    async def test_ingest_with_vision_disabled(
        self,
        db_session,
        isolated_data_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When vision is disabled, ingest still works (returns fitz text)."""
        monkeypatch.setattr(ingest_service, "_DOCLING_AVAILABLE", False)

        fake_settings = Settings(
            data_dir=str(isolated_data_dir),
            vision_enabled=False,
        )
        monkeypatch.setattr(ingest_service, "get_settings", lambda: fake_settings)

        mock_emit = AsyncMock()
        monkeypatch.setattr(ingest_service, "emit_source_progress", mock_emit)

        pdf_bytes = _build_pdf_bytes(["Original fitz extracted text"])
        adapter = PDFAdapter()

        _source, doc = await adapter.ingest(pdf_bytes, "no-vision.pdf", db_session)

        assert "Original fitz extracted text" in doc.clean_text
        # No multimodal calls should have been made
