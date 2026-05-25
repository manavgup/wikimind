"""End-to-end tests: ingest -> compile -> read article.

Each test exercises the full pipeline for a different source type:
  1. Ingest a source via the appropriate adapter (text, URL, PDF, YouTube)
  2. Compile it into a wiki article via the Compiler (LLM mocked)
  3. Read the resulting article back via the FastAPI test client

External services (HTTP fetches, YouTube API, LLM providers) are mocked,
but the real database, file storage, ingest adapters, and compiler
pipeline are exercised end-to-end.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from tests.conftest import TEST_USER_ID
from tests.e2e.conftest import CANNED_COMPILATION, make_fake_completion
from wikimind.engine import base_compiler as base_compiler_mod
from wikimind.engine.compiler import Compiler
from wikimind.ingest.adapters import pdf as pdf_mod
from wikimind.ingest.adapters import url as url_mod
from wikimind.ingest.adapters import youtube as yt_mod
from wikimind.ingest.adapters.pdf import PDFAdapter
from wikimind.ingest.adapters.text import TextAdapter
from wikimind.ingest.adapters.url import URLAdapter
from wikimind.ingest.adapters.youtube import YouTubeAdapter
from wikimind.models import Article, Source, SourceType

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlmodel.ext.asyncio.session import AsyncSession

pytestmark = pytest.mark.e2e


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_settings(data_dir: str) -> SimpleNamespace:
    """Build a minimal settings namespace for the compiler."""
    return SimpleNamespace(
        data_dir=data_dir,
        compiler=SimpleNamespace(
            max_tokens=8192,
            source_text_max_chars=60000,
            guidance_max_length=2000,
            slug_max_attempts=1000,
            interactive=False,
        ),
        billing_enabled=False,
    )


def _make_compiler(data_dir: str) -> Compiler:
    """Create a Compiler with mocked LLM router and settings."""
    with (
        patch.object(base_compiler_mod, "get_llm_router"),
        patch.object(base_compiler_mod, "get_settings", return_value=_fake_settings(data_dir)),
    ):
        compiler = Compiler(user_id=TEST_USER_ID)

    fake_response = make_fake_completion()
    compiler.router.complete = AsyncMock(return_value=fake_response)
    compiler.router.parse_json_response = lambda resp: json.loads(resp.content)
    return compiler


async def _compile_source(
    source: Source,
    doc,
    session: AsyncSession,
    data_dir: str,
) -> Article:
    """Run the compiler on a source and return the saved article."""
    compiler = _make_compiler(data_dir)
    result = await compiler.compile(doc, session)
    assert result is not None, "Compiler returned None — LLM mock may be misconfigured"
    article = await compiler.save_article(result, source, session)
    return article


# ---------------------------------------------------------------------------
# Text ingest -> compile -> read
# ---------------------------------------------------------------------------


async def test_text_ingest_compile_read(client: AsyncClient, db_session: AsyncSession, tmp_path) -> None:
    """Full pipeline: ingest raw text -> compile via LLM -> read article via API."""
    data_dir = str(tmp_path / "wikimind")

    # --- Phase 1: Ingest ---
    adapter = TextAdapter()
    content = (
        "Artificial intelligence is transforming how we process information. "
        "Machine learning models can now understand natural language, generate "
        "images, and write code. The field has seen rapid progress since the "
        "introduction of transformer architectures in 2017."
    )
    source, doc = await adapter.ingest(content, "AI Overview", db_session, user_id=TEST_USER_ID)

    assert source.source_type == SourceType.TEXT
    assert source.title == "AI Overview"
    assert source.clean_text == content

    # --- Phase 2: Compile ---
    article = await _compile_source(source, doc, db_session, data_dir)

    assert article.slug is not None
    assert article.title == CANNED_COMPILATION["title"]
    assert article.summary == CANNED_COMPILATION["summary"]

    # --- Phase 3: Read via API ---
    resp = await client.get(f"/api/wiki/articles/{article.slug}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == CANNED_COMPILATION["title"]
    assert data["summary"] == CANNED_COMPILATION["summary"]
    assert data["slug"] == article.slug
    assert "content" in data
    assert len(data["content"]) > 0

    # Verify source linkage via the sources list endpoint
    resp = await client.get("/api/ingest/sources")
    assert resp.status_code == 200
    sources = resp.json()
    assert any(s["id"] == source.id for s in sources)


# ---------------------------------------------------------------------------
# URL ingest -> compile -> read
# ---------------------------------------------------------------------------


async def test_url_ingest_compile_read(client: AsyncClient, db_session: AsyncSession, tmp_path) -> None:
    """Full pipeline: ingest URL -> compile via LLM -> read article via API."""
    data_dir = str(tmp_path / "wikimind")

    # --- Phase 1: Ingest (mock HTTP fetch + trafilatura) ---
    fake_html = "<html><body><h1>Climate Change</h1><p>Global temperatures are rising.</p></body></html>"
    extracted_text = "# Climate Change\n\nGlobal temperatures are rising due to greenhouse gas emissions."

    fake_response = MagicMock()
    fake_response.text = fake_html
    fake_response.raise_for_status = MagicMock()

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.get = AsyncMock(return_value=fake_response)

    with (
        patch.object(url_mod.httpx, "AsyncClient", return_value=fake_client),
        patch.object(url_mod.trafilatura, "extract", return_value=extracted_text),
        patch.object(
            url_mod.trafilatura,
            "extract_metadata",
            return_value=SimpleNamespace(title="Climate Change Report", author="IPCC"),
        ),
    ):
        adapter = URLAdapter()
        source, doc = await adapter.ingest("http://example.com/climate", db_session, user_id=TEST_USER_ID)

    assert source.source_type == SourceType.URL
    assert source.title == "Climate Change Report"
    assert doc.clean_text == extracted_text

    # --- Phase 2: Compile ---
    article = await _compile_source(source, doc, db_session, data_dir)

    assert article.slug is not None
    assert article.title == CANNED_COMPILATION["title"]

    # --- Phase 3: Read via API ---
    resp = await client.get(f"/api/wiki/articles/{article.slug}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == CANNED_COMPILATION["title"]
    assert data["slug"] == article.slug
    assert len(data["content"]) > 0

    # Verify source is accessible
    resp = await client.get(f"/api/ingest/sources/{source.id}")
    assert resp.status_code == 200
    assert resp.json()["source_type"] == "url"


# ---------------------------------------------------------------------------
# PDF ingest -> compile -> read
# ---------------------------------------------------------------------------


async def test_pdf_ingest_compile_read(client: AsyncClient, db_session: AsyncSession, tmp_path, monkeypatch) -> None:
    """Full pipeline: ingest PDF -> compile via LLM -> read article via API."""
    data_dir = str(tmp_path / "wikimind")

    # --- Phase 1: Ingest (mock fitz PDF extraction) ---
    fake_meta_doc = MagicMock()
    fake_meta_doc.metadata = {
        "title": "Quantum Computing Primer",
        "author": "Dr. Smith",
        "creationDate": "D:20240101120000",
    }
    fake_meta_doc.close = MagicMock()

    page_text = (
        "Quantum computing leverages quantum mechanical phenomena such as "
        "superposition and entanglement to perform computations. Unlike "
        "classical bits, qubits can exist in multiple states simultaneously."
    )
    fake_page = MagicMock()
    fake_page.get_text = MagicMock(return_value=page_text)

    fake_text_doc = MagicMock()
    fake_text_doc.__iter__ = lambda self: iter([fake_page])
    fake_text_doc.close = MagicMock()

    # Disable vision enhancement
    mock_enhance = AsyncMock(side_effect=lambda fb, ct, sid, **kwargs: ct)
    monkeypatch.setattr(PDFAdapter, "_enhance_with_vision", mock_enhance)

    # Mock progress emission
    mock_emit = AsyncMock()
    monkeypatch.setattr(pdf_mod, "emit_source_progress", mock_emit)

    with (
        patch.object(
            pdf_mod,
            "_convert_via_docling_serve",
            AsyncMock(side_effect=httpx.ConnectError("Connection refused")),
        ),
        patch.object(pdf_mod.fitz, "open", side_effect=[fake_meta_doc, fake_text_doc]),
    ):
        adapter = PDFAdapter()
        source, doc = await adapter.ingest(
            b"%PDF-1.4 fake pdf content", "quantum.pdf", db_session, user_id=TEST_USER_ID
        )

    assert source.source_type == SourceType.PDF
    assert source.title == "Quantum Computing Primer"
    assert page_text in doc.clean_text

    # --- Phase 2: Compile ---
    article = await _compile_source(source, doc, db_session, data_dir)

    assert article.slug is not None
    assert article.title == CANNED_COMPILATION["title"]

    # --- Phase 3: Read via API ---
    resp = await client.get(f"/api/wiki/articles/{article.slug}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == CANNED_COMPILATION["title"]
    assert data["slug"] == article.slug
    assert len(data["content"]) > 0

    # Verify the source detail endpoint works
    resp = await client.get(f"/api/ingest/sources/{source.id}/detail")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["source_type"] == "pdf"
    assert detail["title"] == "Quantum Computing Primer"


# ---------------------------------------------------------------------------
# YouTube ingest -> compile -> read
# ---------------------------------------------------------------------------


async def test_youtube_ingest_compile_read(client: AsyncClient, db_session: AsyncSession, tmp_path) -> None:
    """Full pipeline: ingest YouTube transcript -> compile via LLM -> read article via API."""
    data_dir = str(tmp_path / "wikimind")

    # --- Phase 1: Ingest (mock YouTube transcript API) ---
    fake_transcript = [
        {"text": "Welcome to this lecture on neural networks."},
        {"text": "Today we will cover backpropagation."},
        {"text": "Backpropagation is the core algorithm for training deep networks."},
    ]

    with patch.object(
        yt_mod.YouTubeTranscriptApi,
        "get_transcript",
        return_value=fake_transcript,
        create=True,
    ):
        adapter = YouTubeAdapter()
        source, doc = await adapter.ingest("https://youtu.be/dQw4w9WgXcQ", db_session, user_id=TEST_USER_ID)

    assert source.source_type == SourceType.YOUTUBE
    assert "Welcome to this lecture" in doc.clean_text
    assert "backpropagation" in doc.clean_text.lower()

    # --- Phase 2: Compile ---
    article = await _compile_source(source, doc, db_session, data_dir)

    assert article.slug is not None
    assert article.title == CANNED_COMPILATION["title"]

    # --- Phase 3: Read via API ---
    resp = await client.get(f"/api/wiki/articles/{article.slug}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == CANNED_COMPILATION["title"]
    assert data["slug"] == article.slug
    assert len(data["content"]) > 0


# ---------------------------------------------------------------------------
# Multiple sources -> distinct articles
# ---------------------------------------------------------------------------


async def test_multiple_sources_produce_distinct_articles(
    client: AsyncClient, db_session: AsyncSession, tmp_path
) -> None:
    """Ingesting two different text sources produces two separate articles."""
    data_dir = str(tmp_path / "wikimind")

    adapter = TextAdapter()

    # Ingest first source
    source1, doc1 = await adapter.ingest(
        "First source about astronomy and star formation.",
        "Astronomy Notes",
        db_session,
        user_id=TEST_USER_ID,
    )

    # Compile first source
    compiler1 = _make_compiler(data_dir)
    # Override the canned response to produce a unique title
    compilation1 = {**CANNED_COMPILATION, "title": "Astronomy Overview"}
    fake_resp1 = make_fake_completion(compilation1)
    compiler1.router.complete = AsyncMock(return_value=fake_resp1)
    result1 = await compiler1.compile(doc1, db_session)
    assert result1 is not None
    article1 = await compiler1.save_article(result1, source1, db_session)

    # Ingest second source
    source2, doc2 = await adapter.ingest(
        "Second source about marine biology and ocean ecosystems.",
        "Marine Biology Notes",
        db_session,
        user_id=TEST_USER_ID,
    )

    # Compile second source with a different title
    compiler2 = _make_compiler(data_dir)
    compilation2 = {**CANNED_COMPILATION, "title": "Marine Biology Overview"}
    fake_resp2 = make_fake_completion(compilation2)
    compiler2.router.complete = AsyncMock(return_value=fake_resp2)
    result2 = await compiler2.compile(doc2, db_session)
    assert result2 is not None
    article2 = await compiler2.save_article(result2, source2, db_session)

    # Articles should be distinct
    assert article1.id != article2.id
    assert article1.slug != article2.slug

    # Both should be readable via API
    resp1 = await client.get(f"/api/wiki/articles/{article1.slug}")
    resp2 = await client.get(f"/api/wiki/articles/{article2.slug}")
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json()["title"] == "Astronomy Overview"
    assert resp2.json()["title"] == "Marine Biology Overview"

    # Article list should contain both
    resp = await client.get("/api/wiki/articles")
    assert resp.status_code == 200
    slugs = {a["slug"] for a in resp.json()}
    assert article1.slug in slugs
    assert article2.slug in slugs


# ---------------------------------------------------------------------------
# Source content readable after ingest
# ---------------------------------------------------------------------------


async def test_source_content_readable_after_ingest(client: AsyncClient, db_session: AsyncSession, tmp_path) -> None:
    """After ingesting text, the source content endpoint returns the original text."""
    adapter = TextAdapter()
    original_text = "This is the original source material about quantum entanglement."
    source, _ = await adapter.ingest(original_text, "Quantum Notes", db_session, user_id=TEST_USER_ID)

    resp = await client.get(f"/api/ingest/sources/{source.id}/content")
    assert resp.status_code == 200
    data = resp.json()
    assert data["content"] == original_text
    assert data["source_type"] == "text"
    assert data["title"] == "Quantum Notes"
