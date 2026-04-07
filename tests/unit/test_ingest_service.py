"""Tests for ingest adapters and IngestService orchestration."""

from __future__ import annotations

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
    chunk_text,
    estimate_tokens,
)
from wikimind.models import SourceType


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


async def test_pdf_adapter_fitz_path(db_session, tmp_path) -> None:
    fake_page = MagicMock()
    fake_page.get_text = MagicMock(return_value="page text")
    fake_doc = MagicMock()
    fake_doc.__iter__ = lambda self: iter([fake_page, fake_page])
    fake_doc.close = MagicMock()
    with (
        patch.object(ingest_mod, "_DOCLING_AVAILABLE", False),
        patch.object(ingest_mod.fitz, "open", return_value=fake_doc),
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
    with patch.object(svc.url_adapter, "ingest", AsyncMock(return_value=(MagicMock(), MagicMock()))) as u:
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


def test_get_docling_converter_unavailable() -> None:
    with patch.object(ingest_mod, "_DocumentConverter", None):
        ingest_mod._docling_converter = None
        with pytest.raises(RuntimeError):
            ingest_mod._get_docling_converter()
