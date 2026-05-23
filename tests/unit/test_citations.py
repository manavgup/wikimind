"""Tests for span-level citations (issue #450).

Covers the SourceSpan model, the CompiledClaim.source_span_ids field,
the CitationService, the GET /api/wiki/articles/{id}/citations endpoint,
and Phase 2 claim-span linkage in the compiler.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from tests.conftest import TEST_USER_ID
from wikimind.engine import base_compiler as base_compiler_mod
from wikimind.models import (
    Article,
    CompilationResult,
    CompiledClaim,
    CompiledClaimDTO,
    ConfidenceLevel,
    LocatorKind,
    NormalizedDocument,
    Source,
    SourceSpan,
)
from wikimind.services.citation import CitationService
from wikimind.services.wiki import WikiService


def _uid() -> str:
    return str(uuid.uuid4())


def _fingerprint(text: str) -> str:
    normalized = " ".join(text.lower().split())
    return hashlib.sha256(normalized.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestSourceSpanModel:
    """Verify SourceSpan can be persisted and read back."""

    @pytest.mark.asyncio
    async def test_create_and_read_source_span(self, db_session: AsyncSession) -> None:
        source_id = _uid()
        source = Source(
            id=source_id,
            user_id=TEST_USER_ID,
            source_type="url",
            title="Test Source",
        )
        db_session.add(source)
        await db_session.flush()

        span_id = _uid()
        text = "Machine learning models require large datasets."
        span = SourceSpan(
            id=span_id,
            source_id=source_id,
            user_id=TEST_USER_ID,
            locator_kind=LocatorKind.TEXT_BYTE_RANGE,
            locator={"start": 0, "end": 47},
            text=text,
            fingerprint=_fingerprint(text),
        )
        db_session.add(span)
        await db_session.flush()
        await db_session.refresh(span)

        assert span.id == span_id
        assert span.source_id == source_id
        assert span.locator_kind == LocatorKind.TEXT_BYTE_RANGE
        assert span.locator == {"start": 0, "end": 47}
        assert span.text == text
        assert span.fingerprint == _fingerprint(text)

    @pytest.mark.asyncio
    async def test_locator_kinds(self, db_session: AsyncSession) -> None:
        """All LocatorKind values should be valid."""
        assert LocatorKind.PDF_PAGE_RECT == "pdf-page-rect"
        assert LocatorKind.HTML_PARAGRAPH_OFFSET == "html-paragraph-offset"
        assert LocatorKind.TEXT_BYTE_RANGE == "text-byte-range"
        assert LocatorKind.YOUTUBE_TIMESTAMP == "youtube-timestamp"


class TestCompiledClaimSourceSpanIds:
    """Verify CompiledClaim.source_span_ids field."""

    @pytest.mark.asyncio
    async def test_default_empty_list(self, db_session: AsyncSession) -> None:
        article_id = _uid()
        article = Article(
            id=article_id,
            user_id=TEST_USER_ID,
            slug="test-article",
            title="Test Article",
            file_path="wiki/test-article.md",
        )
        db_session.add(article)
        await db_session.flush()

        claim = CompiledClaim(
            id=_uid(),
            article_id=article_id,
            user_id=TEST_USER_ID,
            text="Some claim.",
            confidence_level="sourced",
        )
        db_session.add(claim)
        await db_session.flush()
        await db_session.refresh(claim)

        assert claim.source_span_ids == "[]"
        assert json.loads(claim.source_span_ids) == []

    @pytest.mark.asyncio
    async def test_stores_span_ids(self, db_session: AsyncSession) -> None:
        article_id = _uid()
        article = Article(
            id=article_id,
            user_id=TEST_USER_ID,
            slug="test-article-2",
            title="Test Article 2",
            file_path="wiki/test-article-2.md",
        )
        db_session.add(article)
        await db_session.flush()

        span_ids = [_uid(), _uid()]
        claim = CompiledClaim(
            id=_uid(),
            article_id=article_id,
            user_id=TEST_USER_ID,
            text="Another claim.",
            confidence_level="mixed",
            source_span_ids=json.dumps(span_ids),
        )
        db_session.add(claim)
        await db_session.flush()
        await db_session.refresh(claim)

        assert json.loads(claim.source_span_ids) == span_ids


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------


class TestCitationService:
    """Verify CitationService.get_article_citations."""

    @pytest.mark.asyncio
    async def test_article_not_found(self, db_session: AsyncSession) -> None:
        service = CitationService()
        wiki_service = WikiService()
        with pytest.raises(Exception, match="Article not found"):
            await service.get_article_citations(
                "nonexistent",
                db_session,
                user_id=TEST_USER_ID,
                wiki_service=wiki_service,
            )

    @pytest.mark.asyncio
    async def test_article_with_no_claims(self, db_session: AsyncSession) -> None:
        article_id = _uid()
        article = Article(
            id=article_id,
            user_id=TEST_USER_ID,
            slug="empty-article",
            title="Empty Article",
            file_path="wiki/empty-article.md",
        )
        db_session.add(article)
        await db_session.flush()

        service = CitationService()
        wiki_service = WikiService()
        result = await service.get_article_citations(
            article_id,
            db_session,
            user_id=TEST_USER_ID,
            wiki_service=wiki_service,
        )

        assert result.article_id == article_id
        assert result.article_title == "Empty Article"
        assert result.claims == []

    @pytest.mark.asyncio
    async def test_claims_with_source_spans(self, db_session: AsyncSession) -> None:
        # Create source
        source_id = _uid()
        source = Source(
            id=source_id,
            user_id=TEST_USER_ID,
            source_type="pdf",
            title="Research Paper",
        )
        db_session.add(source)
        await db_session.flush()

        # Create source spans
        span_1_id = _uid()
        span_1_text = "Neural networks improve accuracy."
        span_1 = SourceSpan(
            id=span_1_id,
            source_id=source_id,
            user_id=TEST_USER_ID,
            locator_kind=LocatorKind.PDF_PAGE_RECT,
            locator={"page": 3, "rect": [10, 20, 300, 40]},
            text=span_1_text,
            fingerprint=_fingerprint(span_1_text),
        )

        span_2_id = _uid()
        span_2_text = "Training requires GPU resources."
        span_2 = SourceSpan(
            id=span_2_id,
            source_id=source_id,
            user_id=TEST_USER_ID,
            locator_kind=LocatorKind.PDF_PAGE_RECT,
            locator={"page": 5, "rect": [10, 50, 300, 70]},
            text=span_2_text,
            fingerprint=_fingerprint(span_2_text),
        )
        db_session.add_all([span_1, span_2])
        await db_session.flush()

        # Create article and claim
        article_id = _uid()
        article = Article(
            id=article_id,
            user_id=TEST_USER_ID,
            slug="neural-nets",
            title="Neural Networks",
            file_path="wiki/neural-nets.md",
        )
        db_session.add(article)
        await db_session.flush()

        claim = CompiledClaim(
            id=_uid(),
            article_id=article_id,
            user_id=TEST_USER_ID,
            text="Neural networks need GPUs and improve accuracy.",
            confidence_level="sourced",
            source_ids=json.dumps([source_id]),
            source_span_ids=json.dumps([span_1_id, span_2_id]),
        )
        db_session.add(claim)
        await db_session.flush()

        service = CitationService()
        wiki_service = WikiService()
        result = await service.get_article_citations(
            article_id,
            db_session,
            user_id=TEST_USER_ID,
            wiki_service=wiki_service,
        )

        assert result.article_id == article_id
        assert result.article_title == "Neural Networks"
        assert len(result.claims) == 1

        claim_resp = result.claims[0]
        assert claim_resp.text == "Neural networks need GPUs and improve accuracy."
        assert claim_resp.confidence_level == "sourced"
        assert len(claim_resp.source_spans) == 2
        assert {s.id for s in claim_resp.source_spans} == {span_1_id, span_2_id}

    @pytest.mark.asyncio
    async def test_resolve_by_slug(self, db_session: AsyncSession) -> None:
        article_id = _uid()
        article = Article(
            id=article_id,
            user_id=TEST_USER_ID,
            slug="slug-resolve-test",
            title="Slug Resolve Test",
            file_path="wiki/slug-resolve-test.md",
        )
        db_session.add(article)
        await db_session.flush()

        service = CitationService()
        wiki_service = WikiService()
        result = await service.get_article_citations(
            "slug-resolve-test",
            db_session,
            user_id=TEST_USER_ID,
            wiki_service=wiki_service,
        )

        assert result.article_id == article_id
        assert result.article_title == "Slug Resolve Test"


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


class TestCitationsEndpoint:
    """Verify GET /api/wiki/articles/{id}/citations endpoint."""

    @pytest.mark.asyncio
    async def test_citations_endpoint_not_found(self, client) -> None:
        resp = await client.get("/api/wiki/articles/nonexistent/citations")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_citations_endpoint_empty_article(self, client, async_engine) -> None:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
        article_id = _uid()
        async with factory() as session:
            article = Article(
                id=article_id,
                user_id=TEST_USER_ID,
                slug="endpoint-test",
                title="Endpoint Test",
                file_path="wiki/endpoint-test.md",
            )
            session.add(article)
            await session.commit()

        resp = await client.get(f"/api/wiki/articles/{article_id}/citations")
        assert resp.status_code == 200
        data = resp.json()
        assert data["article_id"] == article_id
        assert data["article_title"] == "Endpoint Test"
        assert data["claims"] == []

    @pytest.mark.asyncio
    async def test_citations_endpoint_with_spans(self, client, async_engine) -> None:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

        source_id = _uid()
        span_id = _uid()
        article_id = _uid()
        span_text = "Important finding here."

        async with factory() as session:
            source = Source(
                id=source_id,
                user_id=TEST_USER_ID,
                source_type="url",
                title="Web Source",
            )
            session.add(source)
            await session.flush()

            span = SourceSpan(
                id=span_id,
                source_id=source_id,
                user_id=TEST_USER_ID,
                locator_kind=LocatorKind.HTML_PARAGRAPH_OFFSET,
                locator={"xpath": "//p[3]", "offset": 0, "length": 23},
                text=span_text,
                fingerprint=_fingerprint(span_text),
            )
            session.add(span)

            article = Article(
                id=article_id,
                user_id=TEST_USER_ID,
                slug="span-endpoint-test",
                title="Span Endpoint Test",
                file_path="wiki/span-endpoint-test.md",
            )
            session.add(article)
            await session.flush()

            claim = CompiledClaim(
                id=_uid(),
                article_id=article_id,
                user_id=TEST_USER_ID,
                text="An important finding.",
                confidence_level="sourced",
                source_ids=json.dumps([source_id]),
                source_span_ids=json.dumps([span_id]),
            )
            session.add(claim)
            await session.commit()

        resp = await client.get(f"/api/wiki/articles/{article_id}/citations")
        assert resp.status_code == 200
        data = resp.json()
        assert data["article_id"] == article_id
        assert len(data["claims"]) == 1
        assert len(data["claims"][0]["source_spans"]) == 1
        assert data["claims"][0]["source_spans"][0]["id"] == span_id
        assert data["claims"][0]["source_spans"][0]["locator_kind"] == "html-paragraph-offset"


# ---------------------------------------------------------------------------
# Phase 2: Compiler claim-span linkage tests (issue #450)
# ---------------------------------------------------------------------------


def _fake_settings() -> SimpleNamespace:
    return SimpleNamespace(
        data_dir="/tmp/wm-test",
        compiler=SimpleNamespace(
            max_tokens=8192,
            source_text_max_chars=60000,
            guidance_max_length=2000,
            slug_max_attempts=1000,
        ),
    )


def _make_compiler():
    from wikimind.engine.compiler import Compiler

    with (
        patch.object(base_compiler_mod, "get_llm_router"),
        patch.object(base_compiler_mod, "get_settings", return_value=_fake_settings()),
    ):
        return Compiler(user_id=TEST_USER_ID)


class TestBuildUserPromptWithSpans:
    """Verify _build_user_prompt includes span IDs when available."""

    def test_prompt_without_spans(self) -> None:
        c = _make_compiler()
        doc = NormalizedDocument(
            raw_source_id="src-1",
            clean_text="Hello world",
            title="Test",
            estimated_tokens=10,
        )
        prompt = c._build_user_prompt(doc)
        assert "Source Spans" not in prompt
        assert "Compile this into a wiki article" in prompt

    def test_prompt_with_spans(self) -> None:
        c = _make_compiler()
        doc = NormalizedDocument(
            raw_source_id="src-1",
            clean_text="Hello world",
            title="Test",
            estimated_tokens=10,
        )
        span = SourceSpan(
            id="span-abc",
            source_id="src-1",
            user_id=TEST_USER_ID,
            locator_kind=LocatorKind.TEXT_BYTE_RANGE,
            locator={"start": 0, "end": 11},
            text="Hello world",
            fingerprint=_fingerprint("Hello world"),
        )
        prompt = c._build_user_prompt(doc, spans=[span])
        assert "## Source Spans" in prompt
        assert "span-abc" in prompt
        assert "Hello world" in prompt


class TestCompiledClaimDTOSpanIds:
    """Verify CompiledClaimDTO accepts source_span_ids."""

    def test_default_empty(self) -> None:
        dto = CompiledClaimDTO(claim="X", confidence=ConfidenceLevel.SOURCED)
        assert dto.source_span_ids == []

    def test_with_span_ids(self) -> None:
        dto = CompiledClaimDTO(
            claim="X",
            confidence=ConfidenceLevel.SOURCED,
            source_span_ids=["span-1", "span-2"],
        )
        assert dto.source_span_ids == ["span-1", "span-2"]

    def test_parsed_from_json(self) -> None:
        data = {
            "claim": "X",
            "confidence": "sourced",
            "source_span_ids": ["span-a"],
        }
        dto = CompiledClaimDTO(**data)
        assert dto.source_span_ids == ["span-a"]


class TestPersistClaimsWithSpanValidation:
    """Verify _persist_claims validates and stores span IDs."""

    @pytest.mark.asyncio
    async def test_valid_span_ids_are_persisted(self, db_session: AsyncSession) -> None:
        # Set up source, article, and spans
        source_id = _uid()
        source = Source(id=source_id, user_id=TEST_USER_ID, source_type="text", title="S")
        db_session.add(source)
        await db_session.flush()

        article_id = _uid()
        article = Article(
            id=article_id,
            user_id=TEST_USER_ID,
            slug="persist-test",
            title="Persist Test",
            file_path="wiki/persist-test.md",
        )
        db_session.add(article)
        await db_session.flush()

        span_id = _uid()
        span = SourceSpan(
            id=span_id,
            source_id=source_id,
            user_id=TEST_USER_ID,
            locator_kind=LocatorKind.TEXT_BYTE_RANGE,
            locator={"start": 0, "end": 10},
            text="Some text.",
            fingerprint=_fingerprint("Some text."),
        )
        db_session.add(span)
        await db_session.flush()

        # Create compiler with valid spans loaded
        c = _make_compiler()
        c._source_spans = [span]

        result = CompilationResult(
            title="T",
            summary="S. S.",
            key_claims=[
                CompiledClaimDTO(
                    claim="Claim one",
                    confidence=ConfidenceLevel.SOURCED,
                    source_span_ids=[span_id],
                ),
            ],
            concepts=[],
            backlink_suggestions=[],
            open_questions=[],
            article_body="body",
        )

        await c._persist_claims(article_id, result, source, db_session)

        # Verify the claim was persisted with span IDs
        from sqlmodel import select

        stmt = select(CompiledClaim).where(CompiledClaim.article_id == article_id)
        claims = (await db_session.exec(stmt)).all()
        assert len(claims) == 1
        assert json.loads(claims[0].source_span_ids) == [span_id]

    @pytest.mark.asyncio
    async def test_invalid_span_ids_are_rejected(self, db_session: AsyncSession) -> None:
        source_id = _uid()
        source = Source(id=source_id, user_id=TEST_USER_ID, source_type="text", title="S")
        db_session.add(source)
        await db_session.flush()

        article_id = _uid()
        article = Article(
            id=article_id,
            user_id=TEST_USER_ID,
            slug="reject-test",
            title="Reject Test",
            file_path="wiki/reject-test.md",
        )
        db_session.add(article)
        await db_session.flush()

        valid_span_id = _uid()
        span = SourceSpan(
            id=valid_span_id,
            source_id=source_id,
            user_id=TEST_USER_ID,
            locator_kind=LocatorKind.TEXT_BYTE_RANGE,
            locator={"start": 0, "end": 5},
            text="Valid",
            fingerprint=_fingerprint("Valid"),
        )
        db_session.add(span)
        await db_session.flush()

        c = _make_compiler()
        c._source_spans = [span]

        fake_span_id = _uid()
        result = CompilationResult(
            title="T",
            summary="S. S.",
            key_claims=[
                CompiledClaimDTO(
                    claim="Claim with mixed IDs",
                    confidence=ConfidenceLevel.SOURCED,
                    source_span_ids=[valid_span_id, fake_span_id],
                ),
            ],
            concepts=[],
            backlink_suggestions=[],
            open_questions=[],
            article_body="body",
        )

        await c._persist_claims(article_id, result, source, db_session)

        from sqlmodel import select

        stmt = select(CompiledClaim).where(CompiledClaim.article_id == article_id)
        claims = (await db_session.exec(stmt)).all()
        assert len(claims) == 1
        persisted_span_ids = json.loads(claims[0].source_span_ids)
        # Only the valid span ID should be persisted
        assert persisted_span_ids == [valid_span_id]
        assert fake_span_id not in persisted_span_ids

    @pytest.mark.asyncio
    async def test_no_spans_loaded_all_rejected(self, db_session: AsyncSession) -> None:
        source_id = _uid()
        source = Source(id=source_id, user_id=TEST_USER_ID, source_type="text", title="S")
        db_session.add(source)
        await db_session.flush()

        article_id = _uid()
        article = Article(
            id=article_id,
            user_id=TEST_USER_ID,
            slug="empty-spans-test",
            title="Empty Spans Test",
            file_path="wiki/empty-spans-test.md",
        )
        db_session.add(article)
        await db_session.flush()

        c = _make_compiler()
        c._source_spans = []  # No spans loaded

        result = CompilationResult(
            title="T",
            summary="S. S.",
            key_claims=[
                CompiledClaimDTO(
                    claim="Claim with hallucinated spans",
                    confidence=ConfidenceLevel.SOURCED,
                    source_span_ids=[_uid()],
                ),
            ],
            concepts=[],
            backlink_suggestions=[],
            open_questions=[],
            article_body="body",
        )

        await c._persist_claims(article_id, result, source, db_session)

        from sqlmodel import select

        stmt = select(CompiledClaim).where(CompiledClaim.article_id == article_id)
        claims = (await db_session.exec(stmt)).all()
        assert len(claims) == 1
        assert json.loads(claims[0].source_span_ids) == []
