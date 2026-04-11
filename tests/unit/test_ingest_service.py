"""Tests for ingest adapters and IngestService orchestration."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wikimind.ingest import service as ingest_mod
from wikimind.ingest.service import (
    IngestService,
    PDFAdapter,
    TextAdapter,
    URLAdapter,
    YouTubeAdapter,
    _extract_pdf_metadata,
    _first_markdown_heading,
    _parse_pdf_date,
    chunk_text,
    estimate_tokens,
)
from wikimind.models import IngestStatus, Source, SourceType


def test_estimate_tokens() -> None:
    assert estimate_tokens("a" * 40) == 10


def test_chunk_text_small_returns_one_chunk() -> None:
    chunks = chunk_text("hello world", "doc-1")
    assert len(chunks) == 1
    assert chunks[0].content == "hello world"


def test_chunk_text_with_headings() -> None:
    text = "# Title\n\n" + ("word " * 5000) + "\n\n## Sub\n\nmore"
    chunks = chunk_text(text, "doc-1", max_chunk_tokens=100)
    assert len(chunks) >= 1


async def test_url_adapter_ingest(db_session, tmp_path) -> None:
    fake_response = MagicMock()
    fake_response.text = "<html><body>Hello world</body></html>"
    fake_response.raise_for_status = MagicMock()

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.get = AsyncMock(return_value=fake_response)

    with (
        patch.object(ingest_mod.httpx, "AsyncClient", return_value=fake_client),
        patch.object(ingest_mod.trafilatura, "extract", return_value="# Hello\n\nWorld"),
        patch.object(ingest_mod.trafilatura, "extract_metadata", return_value=SimpleNamespace(title="T", author="A")),
    ):
        adapter = URLAdapter()
        source, doc = await adapter.ingest("http://example.com", db_session)
    assert source.source_type == SourceType.URL
    assert doc.title == "T"
    assert doc.estimated_tokens > 0


async def test_url_adapter_no_content_raises(db_session) -> None:
    fake_response = MagicMock()
    fake_response.text = "<html></html>"
    fake_response.raise_for_status = MagicMock()
    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.get = AsyncMock(return_value=fake_response)
    with (
        patch.object(ingest_mod.httpx, "AsyncClient", return_value=fake_client),
        patch.object(ingest_mod.trafilatura, "extract", return_value=None),
    ):
        adapter = URLAdapter()
        with pytest.raises(ValueError):
            await adapter.ingest("http://example.com", db_session)


async def test_pdf_adapter_fitz_path(db_session, tmp_path, monkeypatch) -> None:
    fake_page = MagicMock()
    fake_page.get_text = MagicMock(return_value="page text")

    # fitz.open is called twice: once for metadata, once for text extraction.
    fake_meta_doc = MagicMock()
    fake_meta_doc.metadata = {"title": "", "author": "", "creationDate": ""}
    fake_meta_doc.close = MagicMock()

    fake_text_doc = MagicMock()
    fake_text_doc.__iter__ = lambda self: iter([fake_page, fake_page])
    fake_text_doc.close = MagicMock()

    # Disable vision so _enhance_with_vision is a no-op
    mock_enhance = AsyncMock(side_effect=lambda fb, ct, sid: ct)
    monkeypatch.setattr(PDFAdapter, "_enhance_with_vision", mock_enhance)

    with (
        patch.object(ingest_mod, "_DOCLING_AVAILABLE", False),
        patch.object(ingest_mod.fitz, "open", side_effect=[fake_meta_doc, fake_text_doc]),
    ):
        adapter = PDFAdapter()
        source, doc = await adapter.ingest(b"%PDF-1.4...", "test.pdf", db_session)
    assert source.source_type == SourceType.PDF
    assert "page text" in doc.clean_text


async def test_text_adapter(db_session) -> None:
    adapter = TextAdapter()
    source, doc = await adapter.ingest("hello world", "My Note", db_session)
    assert source.source_type == SourceType.TEXT
    assert doc.title == "My Note"


def test_youtube_extract_video_id() -> None:
    a = YouTubeAdapter()
    assert a._extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert a._extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert a._extract_video_id("http://other.com/x") is None


async def test_youtube_adapter_invalid_url(db_session) -> None:
    a = YouTubeAdapter()
    with pytest.raises(ValueError):
        await a.ingest("http://other.com/foo", db_session)


async def test_youtube_adapter_success(db_session) -> None:
    a = YouTubeAdapter()
    with patch.object(
        ingest_mod.YouTubeTranscriptApi,
        "get_transcript",
        return_value=[{"text": "hello"}, {"text": "world"}],
        create=True,
    ):
        source, doc = await a.ingest("https://youtu.be/dQw4w9WgXcQ", db_session)
    assert "hello world" in doc.clean_text
    assert source.source_type == SourceType.YOUTUBE


async def test_ingest_service_routes_youtube(db_session) -> None:
    svc = IngestService()
    with patch.object(svc.youtube_adapter, "ingest", AsyncMock(return_value=(MagicMock(), MagicMock()))) as yt:
        await svc.ingest_url("https://youtu.be/abc", db_session)
        yt.assert_awaited()


async def test_ingest_service_routes_url(db_session) -> None:
    svc = IngestService()

    fake_response = MagicMock()
    fake_response.content = b"<html>hi</html>"
    fake_response.raise_for_status = MagicMock()
    fake_response.headers = {"content-type": "text/html; charset=utf-8"}

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.get = AsyncMock(return_value=fake_response)

    with (
        patch.object(ingest_mod.httpx, "AsyncClient", return_value=fake_client),
        patch.object(svc.url_adapter, "ingest", AsyncMock(return_value=(MagicMock(), MagicMock()))) as u,
    ):
        await svc.ingest_url("https://example.com", db_session)
        u.assert_awaited()


async def test_ingest_service_pdf(db_session) -> None:
    svc = IngestService()
    with patch.object(svc.pdf_adapter, "ingest", AsyncMock(return_value=(MagicMock(), MagicMock()))) as p:
        await svc.ingest_pdf(b"x", "f.pdf", db_session)
        p.assert_awaited()


async def test_ingest_service_text(db_session) -> None:
    svc = IngestService()
    with patch.object(svc.text_adapter, "ingest", AsyncMock(return_value=(MagicMock(), MagicMock()))) as t:
        await svc.ingest_text("c", "t", db_session)
        t.assert_awaited()


# ---------------------------------------------------------------------------
# PDF-URL routing tests (issue #109)
# ---------------------------------------------------------------------------


def _fake_pdf_source() -> Source:
    """Return a minimal Source that can be passed to ``session.add``."""
    return Source(
        source_type=SourceType.PDF,
        title="fake",
        status=IngestStatus.PROCESSING,
    )


async def test_ingest_service_routes_pdf_url(db_session) -> None:
    """A URL whose path ends in .pdf should be routed to the PDF adapter."""
    svc = IngestService()
    fake_response = MagicMock()
    fake_response.content = b"%PDF-1.4 fake pdf bytes"
    fake_response.raise_for_status = MagicMock()

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.get = AsyncMock(return_value=fake_response)

    with (
        patch.object(ingest_mod.httpx, "AsyncClient", return_value=fake_client),
        patch.object(
            svc.pdf_adapter,
            "ingest",
            AsyncMock(return_value=(_fake_pdf_source(), MagicMock())),
        ) as pdf_mock,
    ):
        await svc.ingest_url(
            "https://example.com/papers/GTforSEBookPrefinalDownload.pdf",
            db_session,
        )
        pdf_mock.assert_awaited_once()
        call_args = pdf_mock.call_args
        assert call_args[0][0] == b"%PDF-1.4 fake pdf bytes"
        assert call_args[0][1] == "GTforSEBookPrefinalDownload.pdf"


async def test_ingest_service_routes_pdf_url_case_insensitive(db_session) -> None:
    """URL ending in .PDF (uppercase) should also be routed to the PDF adapter."""
    svc = IngestService()
    fake_response = MagicMock()
    fake_response.content = b"%PDF-1.4 fake"
    fake_response.raise_for_status = MagicMock()

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.get = AsyncMock(return_value=fake_response)

    with (
        patch.object(ingest_mod.httpx, "AsyncClient", return_value=fake_client),
        patch.object(
            svc.pdf_adapter,
            "ingest",
            AsyncMock(return_value=(_fake_pdf_source(), MagicMock())),
        ) as pdf_mock,
    ):
        await svc.ingest_url("https://example.com/REPORT.PDF", db_session)
        pdf_mock.assert_awaited_once()


async def test_ingest_service_routes_pdf_url_with_query_params(db_session) -> None:
    """URL ending in .pdf?token=abc should still be routed to the PDF adapter."""
    svc = IngestService()
    fake_response = MagicMock()
    fake_response.content = b"%PDF-1.4 fake"
    fake_response.raise_for_status = MagicMock()

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.get = AsyncMock(return_value=fake_response)

    with (
        patch.object(ingest_mod.httpx, "AsyncClient", return_value=fake_client),
        patch.object(
            svc.pdf_adapter,
            "ingest",
            AsyncMock(return_value=(_fake_pdf_source(), MagicMock())),
        ) as pdf_mock,
    ):
        await svc.ingest_url("https://example.com/file.pdf?token=abc&v=2", db_session)
        pdf_mock.assert_awaited_once()
        assert pdf_mock.call_args[0][1] == "file.pdf"


async def test_ingest_service_normal_url_still_uses_url_adapter(db_session) -> None:
    """Non-PDF, non-YouTube URLs should still be routed to the URL adapter."""
    svc = IngestService()

    # The fallback helper fetches the URL first, then delegates to url_adapter.
    # We need to mock the httpx client for the pre-fetch AND the url_adapter.
    fake_response = MagicMock()
    fake_response.content = b"<html>hi</html>"
    fake_response.raise_for_status = MagicMock()
    fake_response.headers = {"content-type": "text/html; charset=utf-8"}

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.get = AsyncMock(return_value=fake_response)

    with (
        patch.object(ingest_mod.httpx, "AsyncClient", return_value=fake_client),
        patch.object(
            svc.url_adapter,
            "ingest",
            AsyncMock(return_value=(MagicMock(), MagicMock())),
        ) as url_mock,
    ):
        await svc.ingest_url("https://example.com/article", db_session)
        url_mock.assert_awaited_once()


async def test_ingest_service_youtube_url_still_works(db_session) -> None:
    """YouTube URLs should still be routed to the YouTube adapter."""
    svc = IngestService()
    with patch.object(
        svc.youtube_adapter,
        "ingest",
        AsyncMock(return_value=(MagicMock(), MagicMock())),
    ) as yt:
        await svc.ingest_url("https://www.youtube.com/watch?v=abc", db_session)
        yt.assert_awaited_once()


async def test_ingest_service_content_type_pdf_fallback(db_session) -> None:
    """Content-Type application/pdf fallback routes to PDF adapter."""
    svc = IngestService()
    fake_response = MagicMock()
    fake_response.content = b"%PDF-1.4 dynamic pdf"
    fake_response.raise_for_status = MagicMock()
    fake_response.headers = {"content-type": "application/pdf"}

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.get = AsyncMock(return_value=fake_response)

    with (
        patch.object(ingest_mod.httpx, "AsyncClient", return_value=fake_client),
        patch.object(
            svc.pdf_adapter,
            "ingest",
            AsyncMock(return_value=(_fake_pdf_source(), MagicMock())),
        ) as pdf_mock,
    ):
        await svc.ingest_url("https://example.com/download?id=12345", db_session)
        pdf_mock.assert_awaited_once()


def test_looks_like_pdf_url() -> None:
    """Unit test for the static helper _looks_like_pdf_url."""
    assert IngestService._looks_like_pdf_url("https://x.com/a.pdf") is True
    assert IngestService._looks_like_pdf_url("https://x.com/a.PDF") is True
    assert IngestService._looks_like_pdf_url("https://x.com/a.Pdf") is True
    assert IngestService._looks_like_pdf_url("https://x.com/a.pdf?t=1") is True
    assert IngestService._looks_like_pdf_url("https://x.com/a.pdf#p=3") is True
    assert IngestService._looks_like_pdf_url("https://x.com/article") is False
    assert IngestService._looks_like_pdf_url("https://x.com/a.html") is False


def test_get_docling_converter_unavailable() -> None:
    with patch.object(ingest_mod, "_DocumentConverter", None):
        ingest_mod._docling_converter = None
        with pytest.raises(RuntimeError):
            ingest_mod._get_docling_converter()


# ---------------------------------------------------------------------------
# PDF metadata extraction tests (issue #124)
# ---------------------------------------------------------------------------


def test_extract_pdf_metadata_with_title() -> None:
    """Fitz metadata with a real title populates the result."""
    fake_doc = MagicMock()
    fake_doc.metadata = {
        "title": "Attention Is All You Need",
        "author": "Vaswani et al.",
        "creationDate": "D:20170612120000",
    }
    fake_doc.close = MagicMock()
    with patch.object(ingest_mod.fitz, "open", return_value=fake_doc):
        meta = _extract_pdf_metadata(b"fake-pdf-bytes")
    assert meta.title == "Attention Is All You Need"
    assert meta.author == "Vaswani et al."
    assert meta.published_date is not None
    assert meta.published_date.year == 2017
    assert meta.published_date.month == 6
    assert meta.published_date.day == 12


def test_extract_pdf_metadata_empty_title() -> None:
    """Empty or whitespace-only title returns None."""
    fake_doc = MagicMock()
    fake_doc.metadata = {"title": "  ", "author": "", "creationDate": ""}
    fake_doc.close = MagicMock()
    with patch.object(ingest_mod.fitz, "open", return_value=fake_doc):
        meta = _extract_pdf_metadata(b"fake-pdf-bytes")
    assert meta.title is None
    assert meta.author is None
    assert meta.published_date is None


def test_extract_pdf_metadata_no_metadata_dict() -> None:
    """PDF with no metadata dict at all doesn't crash."""
    fake_doc = MagicMock()
    fake_doc.metadata = None
    fake_doc.close = MagicMock()
    with patch.object(ingest_mod.fitz, "open", return_value=fake_doc):
        meta = _extract_pdf_metadata(b"fake-pdf-bytes")
    assert meta.title is None
    assert meta.author is None
    assert meta.published_date is None


def test_parse_pdf_date_valid() -> None:
    assert _parse_pdf_date("D:20230115093000") == date(2023, 1, 15)


def test_parse_pdf_date_no_prefix() -> None:
    assert _parse_pdf_date("20230115") == date(2023, 1, 15)


def test_parse_pdf_date_too_short() -> None:
    assert _parse_pdf_date("D:2023") is None


def test_parse_pdf_date_garbage() -> None:
    assert _parse_pdf_date("not-a-date") is None


def test_parse_pdf_date_none() -> None:
    assert _parse_pdf_date(None) is None


def test_parse_pdf_date_empty() -> None:
    assert _parse_pdf_date("") is None


def test_first_markdown_heading_found() -> None:
    text = "Some intro text\n\n# My Great Title\n\nBody content here."
    assert _first_markdown_heading(text) == "My Great Title"


def test_first_markdown_heading_first_line() -> None:
    text = "# First Heading\n\n## Sub heading\n\nContent."
    assert _first_markdown_heading(text) == "First Heading"


def test_first_markdown_heading_none() -> None:
    text = "No headings at all.\n\nJust plain text."
    assert _first_markdown_heading(text) is None


def test_first_markdown_heading_skips_h2() -> None:
    """Only top-level (h1) headings should be returned."""
    text = "## Sub Heading\n\n### Another\n\nContent."
    assert _first_markdown_heading(text) is None


async def test_pdf_adapter_metadata_title(db_session, monkeypatch) -> None:
    """PDF with metadata title uses it instead of filename."""
    monkeypatch.setattr(PDFAdapter, "_enhance_with_vision", AsyncMock(side_effect=lambda fb, ct, sid: ct))
    fake_meta_doc = MagicMock()
    fake_meta_doc.metadata = {
        "title": "Attention Is All You Need",
        "author": "Vaswani et al.",
        "creationDate": "D:20170612120000",
    }
    fake_meta_doc.close = MagicMock()

    fake_page = MagicMock()
    fake_page.get_text = MagicMock(return_value="page text")
    fake_text_doc = MagicMock()
    fake_text_doc.__iter__ = lambda self: iter([fake_page])
    fake_text_doc.close = MagicMock()

    with (
        patch.object(ingest_mod, "_DOCLING_AVAILABLE", False),
        patch.object(ingest_mod.fitz, "open", side_effect=[fake_meta_doc, fake_text_doc]),
    ):
        adapter = PDFAdapter()
        source, _ = await adapter.ingest(b"%PDF-1.4...", "2604.08016.pdf", db_session)
    assert source.title == "Attention Is All You Need"
    assert source.author == "Vaswani et al."
    assert source.published_date is not None
    assert source.published_date.year == 2017


async def test_pdf_adapter_heading_fallback(db_session, monkeypatch) -> None:
    """When PDF has no metadata title, falls back to first markdown heading."""
    monkeypatch.setattr(PDFAdapter, "_enhance_with_vision", AsyncMock(side_effect=lambda fb, ct, sid: ct))
    fake_meta_doc = MagicMock()
    fake_meta_doc.metadata = {"title": "", "author": "", "creationDate": ""}
    fake_meta_doc.close = MagicMock()

    fake_page = MagicMock()
    fake_page.get_text = MagicMock(return_value="# A Great Paper\n\nContent here.")
    fake_text_doc = MagicMock()
    fake_text_doc.__iter__ = lambda self: iter([fake_page])
    fake_text_doc.close = MagicMock()

    with (
        patch.object(ingest_mod, "_DOCLING_AVAILABLE", False),
        patch.object(ingest_mod.fitz, "open", side_effect=[fake_meta_doc, fake_text_doc]),
    ):
        adapter = PDFAdapter()
        source, _ = await adapter.ingest(b"%PDF-1.4...", "2604.08016.pdf", db_session)
    assert source.title == "A Great Paper"


async def test_pdf_adapter_filename_fallback(db_session, monkeypatch) -> None:
    """When no metadata title and no heading, falls back to filename."""
    monkeypatch.setattr(PDFAdapter, "_enhance_with_vision", AsyncMock(side_effect=lambda fb, ct, sid: ct))
    fake_meta_doc = MagicMock()
    fake_meta_doc.metadata = {"title": "", "author": "", "creationDate": ""}
    fake_meta_doc.close = MagicMock()

    fake_page = MagicMock()
    fake_page.get_text = MagicMock(return_value="Plain text with no headings.")
    fake_text_doc = MagicMock()
    fake_text_doc.__iter__ = lambda self: iter([fake_page])
    fake_text_doc.close = MagicMock()

    with (
        patch.object(ingest_mod, "_DOCLING_AVAILABLE", False),
        patch.object(ingest_mod.fitz, "open", side_effect=[fake_meta_doc, fake_text_doc]),
    ):
        adapter = PDFAdapter()
        source, _ = await adapter.ingest(b"%PDF-1.4...", "report.pdf", db_session)
    assert source.title == "report"
