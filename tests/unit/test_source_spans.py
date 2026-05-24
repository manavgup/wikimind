"""Tests for span-level citation extraction and fingerprinting (issue #450).

Covers the fingerprint utility, span extraction functions for each adapter,
the SourceSpan persistence, re-anchoring on source updates, and the
GET /api/sources/{id}/spans endpoint.
"""

from __future__ import annotations

import uuid

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from tests.conftest import TEST_USER_ID
from wikimind.ingest.spans import (
    compute_fingerprint,
    extract_pdf_spans,
    extract_text_spans,
    extract_url_spans,
    normalize_text,
    persist_spans,
    reanchor_spans,
)
from wikimind.models import LocatorKind, Source, SourceSpan


def _uid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Fingerprint utility tests
# ---------------------------------------------------------------------------


class TestNormalizeText:
    """Verify text normalization for fingerprinting."""

    def test_lowercases(self) -> None:
        assert normalize_text("Hello World") == "hello world"

    def test_strips_punctuation(self) -> None:
        assert normalize_text("Hello, world!") == "hello world"

    def test_collapses_whitespace(self) -> None:
        assert normalize_text("hello   world\n\tfoo") == "hello world foo"

    def test_strips_leading_trailing(self) -> None:
        assert normalize_text("  hello  ") == "hello"

    def test_empty_string(self) -> None:
        assert normalize_text("") == ""

    def test_unicode_preserved(self) -> None:
        result = normalize_text("Café résumé")
        assert "café" in result
        assert "résumé" in result


class TestComputeFingerprint:
    """Verify fingerprint stability and uniqueness."""

    def test_deterministic(self) -> None:
        text = "Machine learning models require large datasets."
        assert compute_fingerprint(text) == compute_fingerprint(text)

    def test_case_insensitive(self) -> None:
        assert compute_fingerprint("Hello World") == compute_fingerprint("hello world")

    def test_whitespace_insensitive(self) -> None:
        assert compute_fingerprint("hello   world") == compute_fingerprint("hello world")

    def test_punctuation_insensitive(self) -> None:
        assert compute_fingerprint("Hello, world!") == compute_fingerprint("Hello world")

    def test_different_text_different_fingerprint(self) -> None:
        assert compute_fingerprint("hello") != compute_fingerprint("goodbye")

    def test_returns_hex_sha256(self) -> None:
        fp = compute_fingerprint("test")
        assert len(fp) == 64  # SHA-256 hex digest length
        assert all(c in "0123456789abcdef" for c in fp)


# ---------------------------------------------------------------------------
# Text span extraction tests
# ---------------------------------------------------------------------------


class TestExtractTextSpans:
    """Verify byte-range span extraction from plain text."""

    def test_single_paragraph(self) -> None:
        text = "This is a single paragraph."
        spans = extract_text_spans(text, "src-1", "user-1")
        assert len(spans) == 1
        assert spans[0].text == text
        assert spans[0].locator_kind == LocatorKind.TEXT_BYTE_RANGE
        assert spans[0].locator["start"] == 0
        assert spans[0].locator["end"] == len(text.encode("utf-8"))

    def test_multiple_paragraphs(self) -> None:
        text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        spans = extract_text_spans(text, "src-1", "user-1")
        assert len(spans) == 3
        assert spans[0].text == "First paragraph."
        assert spans[1].text == "Second paragraph."
        assert spans[2].text == "Third paragraph."

    def test_byte_ranges_are_correct(self) -> None:
        text = "First.\n\nSecond."
        spans = extract_text_spans(text, "src-1", "user-1")
        text_bytes = text.encode("utf-8")
        for span in spans:
            extracted = text_bytes[span.locator["start"] : span.locator["end"]]
            assert extracted.decode("utf-8") == span.text

    def test_empty_text(self) -> None:
        spans = extract_text_spans("", "src-1", "user-1")
        assert spans == []

    def test_fingerprints_are_set(self) -> None:
        text = "A paragraph."
        spans = extract_text_spans(text, "src-1", "user-1")
        assert spans[0].fingerprint == compute_fingerprint("A paragraph.")

    def test_source_and_user_ids(self) -> None:
        text = "Some text."
        spans = extract_text_spans(text, "src-42", "user-99")
        assert spans[0].source_id == "src-42"
        assert spans[0].user_id == "user-99"


# ---------------------------------------------------------------------------
# PDF span extraction tests
# ---------------------------------------------------------------------------


class TestExtractPdfSpans:
    """Verify PDF page-level span extraction."""

    def test_with_page_texts(self) -> None:
        page_texts = ["Page 1 paragraph 1.\n\nPage 1 paragraph 2.", "Page 2 content."]
        spans = extract_pdf_spans("full text", "src-1", "user-1", page_texts=page_texts)
        assert len(spans) == 3
        assert spans[0].locator_kind == LocatorKind.PDF_PAGE_RECT
        assert spans[0].locator["page"] == 1
        assert spans[0].locator["paragraph"] == 0
        assert spans[0].text == "Page 1 paragraph 1."
        assert spans[1].locator["page"] == 1
        assert spans[1].locator["paragraph"] == 1
        assert spans[2].locator["page"] == 2
        assert spans[2].locator["paragraph"] == 0

    def test_without_page_texts(self) -> None:
        text = "Paragraph 1.\n\nParagraph 2."
        spans = extract_pdf_spans(text, "src-1", "user-1")
        assert len(spans) == 2
        # Falls back to page=1 for all paragraphs
        assert spans[0].locator["page"] == 1
        assert spans[1].locator["page"] == 1

    def test_empty_pages(self) -> None:
        spans = extract_pdf_spans("", "src-1", "user-1", page_texts=[""])
        assert spans == []


# ---------------------------------------------------------------------------
# URL span extraction tests
# ---------------------------------------------------------------------------


class TestExtractUrlSpans:
    """Verify URL paragraph-level span extraction."""

    def test_paragraphs(self) -> None:
        text = "First paragraph.\n\nSecond paragraph."
        spans = extract_url_spans(text, "src-1", "user-1")
        assert len(spans) == 2
        assert spans[0].locator_kind == LocatorKind.HTML_PARAGRAPH_OFFSET
        assert spans[0].locator["paragraph"] == 0
        assert spans[0].locator["length"] == len("First paragraph.")
        assert spans[1].locator["paragraph"] == 1

    def test_empty_text(self) -> None:
        spans = extract_url_spans("", "src-1", "user-1")
        assert spans == []


# ---------------------------------------------------------------------------
# Persistence tests
# ---------------------------------------------------------------------------


class TestPersistSpans:
    """Verify spans are saved to the database."""

    @pytest.mark.asyncio
    async def test_persist_spans(self, db_session: AsyncSession) -> None:
        source_id = _uid()
        source = Source(
            id=source_id,
            user_id=TEST_USER_ID,
            source_type="text",
            title="Test Source",
        )
        db_session.add(source)
        await db_session.flush()

        spans = extract_text_spans("Hello world.\n\nGoodbye world.", source_id, TEST_USER_ID)
        await persist_spans(spans, db_session)
        await db_session.flush()

        # Read back
        from sqlmodel import select

        stmt = select(SourceSpan).where(SourceSpan.source_id == source_id)
        result = (await db_session.exec(stmt)).all()
        assert len(result) == 2
        assert {s.text for s in result} == {"Hello world.", "Goodbye world."}

    @pytest.mark.asyncio
    async def test_persist_empty_list(self, db_session: AsyncSession) -> None:
        # Should be a no-op
        await persist_spans([], db_session)


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


class TestReanchorSpans:
    """Verify re-anchoring preserves span IDs and marks stale spans."""

    @pytest.mark.asyncio
    async def test_matching_fingerprint_preserves_id(self, db_session: AsyncSession) -> None:
        """Spans with matching fingerprints keep their original IDs."""
        source_id = _uid()
        source = Source(
            id=source_id,
            user_id=TEST_USER_ID,
            source_type="text",
            title="Test Source",
        )
        db_session.add(source)
        await db_session.flush()

        # Create original spans
        old_spans = extract_text_spans("Hello world.\n\nGoodbye world.", source_id, TEST_USER_ID)
        for span in old_spans:
            db_session.add(span)
        await db_session.flush()

        original_ids = {s.id for s in old_spans}
        original_fingerprints = {s.fingerprint for s in old_spans}

        # Re-ingest with same paragraphs in different positions
        new_text = "Extra paragraph.\n\nHello world.\n\nGoodbye world."
        new_spans = extract_text_spans(new_text, source_id, TEST_USER_ID)

        result = await reanchor_spans(source_id, new_spans, db_session)
        await db_session.flush()

        # The two matching paragraphs should keep their original IDs
        result_ids = {s.id for s in result if s.fingerprint in original_fingerprints}
        assert result_ids == original_ids

    @pytest.mark.asyncio
    async def test_unmatched_old_spans_become_stale(self, db_session: AsyncSession) -> None:
        """Old spans with no matching fingerprint are marked stale."""
        source_id = _uid()
        source = Source(
            id=source_id,
            user_id=TEST_USER_ID,
            source_type="text",
            title="Test Source",
        )
        db_session.add(source)
        await db_session.flush()

        # Create original spans
        old_spans = extract_text_spans("Will be removed.\n\nStays the same.", source_id, TEST_USER_ID)
        removed_id = old_spans[0].id
        for span in old_spans:
            db_session.add(span)
        await db_session.flush()

        # Re-ingest without the first paragraph
        new_spans = extract_text_spans("Stays the same.\n\nBrand new.", source_id, TEST_USER_ID)
        await reanchor_spans(source_id, new_spans, db_session)
        await db_session.flush()

        # The removed paragraph's span should be stale
        stmt = select(SourceSpan).where(SourceSpan.id == removed_id)
        result = await db_session.execute(stmt)
        stale_span = result.scalar_one()
        assert stale_span.stale is True

    @pytest.mark.asyncio
    async def test_new_spans_are_created(self, db_session: AsyncSession) -> None:
        """Spans with no matching fingerprint in old set are created normally."""
        source_id = _uid()
        source = Source(
            id=source_id,
            user_id=TEST_USER_ID,
            source_type="text",
            title="Test Source",
        )
        db_session.add(source)
        await db_session.flush()

        # Create original spans
        old_spans = extract_text_spans("Old paragraph.", source_id, TEST_USER_ID)
        for span in old_spans:
            db_session.add(span)
        await db_session.flush()

        old_id = old_spans[0].id

        # Re-ingest with a new paragraph added
        new_spans = extract_text_spans("Old paragraph.\n\nBrand new paragraph.", source_id, TEST_USER_ID)
        result = await reanchor_spans(source_id, new_spans, db_session)
        await db_session.flush()

        assert len(result) == 2
        # Old span preserved
        assert any(s.id == old_id for s in result)
        # New span is genuinely new (different ID)
        new_ids = {s.id for s in result} - {old_id}
        assert len(new_ids) == 1

    @pytest.mark.asyncio
    async def test_persist_spans_auto_reanchors(self, db_session: AsyncSession) -> None:
        """persist_spans delegates to reanchor when existing spans are found."""
        source_id = _uid()
        source = Source(
            id=source_id,
            user_id=TEST_USER_ID,
            source_type="text",
            title="Test Source",
        )
        db_session.add(source)
        await db_session.flush()

        # First persist — normal path
        spans_v1 = extract_text_spans("Paragraph A.\n\nParagraph B.", source_id, TEST_USER_ID)
        await persist_spans(spans_v1, db_session)
        await db_session.flush()

        original_ids = {s.id for s in spans_v1}

        # Second persist — should auto-reanchor
        spans_v2 = extract_text_spans("Paragraph A.\n\nParagraph C.", source_id, TEST_USER_ID)
        await persist_spans(spans_v2, db_session)
        await db_session.flush()

        # Check Paragraph A kept its ID
        stmt = select(SourceSpan).where(SourceSpan.source_id == source_id)
        result = await db_session.execute(stmt)
        all_spans = list(result.scalars().all())

        a_spans = [s for s in all_spans if "paragraph a" in s.text.lower()]
        assert len(a_spans) == 1
        assert a_spans[0].id in original_ids
        assert a_spans[0].stale is False

        # Check Paragraph B is stale
        b_spans = [s for s in all_spans if "paragraph b" in s.text.lower()]
        assert len(b_spans) == 1
        assert b_spans[0].stale is True

    @pytest.mark.asyncio
    async def test_reanchor_no_existing_spans(self, db_session: AsyncSession) -> None:
        """When no existing spans exist, reanchor just persists normally."""
        source_id = _uid()
        source = Source(
            id=source_id,
            user_id=TEST_USER_ID,
            source_type="text",
            title="Test Source",
        )
        db_session.add(source)
        await db_session.flush()

        new_spans = extract_text_spans("Brand new text.", source_id, TEST_USER_ID)
        result = await reanchor_spans(source_id, new_spans, db_session)

        assert len(result) == 1
        assert result[0].text == "Brand new text."


# ---------------------------------------------------------------------------
# Stale-span linter tests
# ---------------------------------------------------------------------------


class TestDetectStaleSpans:
    """Verify stale-span linter detection."""

    @pytest.mark.asyncio
    async def test_no_stale_spans_returns_empty(self, db_session: AsyncSession) -> None:
        from wikimind.engine.linter.stale_spans import detect_stale_spans

        findings = await detect_stale_spans(db_session, "report-1", TEST_USER_ID)
        assert findings == []

    @pytest.mark.asyncio
    async def test_stale_spans_with_claim_refs(self, db_session: AsyncSession) -> None:
        """Claims referencing stale spans produce linter findings."""
        import json

        from wikimind.engine.linter.stale_spans import detect_stale_spans
        from wikimind.models import Article, CompiledClaim

        source_id = _uid()
        source = Source(
            id=source_id,
            user_id=TEST_USER_ID,
            source_type="text",
            title="Test Source",
        )
        db_session.add(source)

        # Create a stale span
        span_id = _uid()
        span = SourceSpan(
            id=span_id,
            source_id=source_id,
            user_id=TEST_USER_ID,
            locator_kind=LocatorKind.TEXT_BYTE_RANGE,
            locator={"start": 0, "end": 10},
            text="Old text.",
            fingerprint=compute_fingerprint("Old text."),
            stale=True,
        )
        db_session.add(span)

        # Create article and claim referencing the stale span
        article_id = _uid()
        article = Article(
            id=article_id,
            user_id=TEST_USER_ID,
            slug="test-article",
            title="Test Article",
            file_path="test.md",
        )
        db_session.add(article)

        claim = CompiledClaim(
            article_id=article_id,
            user_id=TEST_USER_ID,
            text="Some claim text",
            confidence_level="sourced",
            source_span_ids=json.dumps([span_id]),
        )
        db_session.add(claim)
        await db_session.flush()

        findings = await detect_stale_spans(db_session, "report-1", TEST_USER_ID)
        assert len(findings) == 1
        assert findings[0].article_id == article_id
        assert findings[0].violation_type == "stale_source_spans"
        assert "1 claim(s) referencing stale source spans" in findings[0].description


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


class TestSourceSpansEndpoint:
    """Verify GET /api/sources/{id}/spans endpoint."""

    @pytest.mark.asyncio
    async def test_spans_endpoint_not_found(self, client) -> None:
        resp = await client.get("/api/ingest/sources/nonexistent/spans")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_spans_endpoint_empty(self, client, async_engine) -> None:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
        source_id = _uid()
        async with factory() as session:
            source = Source(
                id=source_id,
                user_id=TEST_USER_ID,
                source_type="text",
                title="Empty Source",
            )
            session.add(source)
            await session.commit()

        resp = await client.get(f"/api/ingest/sources/{source_id}/spans")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_spans_endpoint_with_spans(self, client, async_engine) -> None:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

        source_id = _uid()
        span_id = _uid()
        span_text = "A test paragraph."

        async with factory() as session:
            source = Source(
                id=source_id,
                user_id=TEST_USER_ID,
                source_type="text",
                title="Span Source",
            )
            session.add(source)
            await session.flush()

            span = SourceSpan(
                id=span_id,
                source_id=source_id,
                user_id=TEST_USER_ID,
                locator_kind=LocatorKind.TEXT_BYTE_RANGE,
                locator={"start": 0, "end": 17},
                text=span_text,
                fingerprint=compute_fingerprint(span_text),
            )
            session.add(span)
            await session.commit()

        resp = await client.get(f"/api/ingest/sources/{source_id}/spans")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == span_id
        assert data[0]["text"] == span_text
        assert data[0]["locator_kind"] == "text-byte-range"
        assert data[0]["locator"] == {"start": 0, "end": 17}
        assert data[0]["fingerprint"] == compute_fingerprint(span_text)
