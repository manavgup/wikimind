"""Tests for the human-in-the-loop compilation draft feature (issue #418)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from tests.conftest import TEST_USER_ID
from wikimind.errors import NotFoundError
from wikimind.models import (
    CompilationDraft,
    CompilationDraftResponse,
    CompilationResult,
    IngestStatus,
    NormalizedDocument,
    Source,
    SourceType,
)
from wikimind.services.draft import DraftService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_source(session, user_id: str = TEST_USER_ID) -> Source:
    """Create a test source row."""
    source = Source(
        user_id=user_id,
        source_type=SourceType.TEXT,
        title="Test Source",
        status=IngestStatus.PROCESSING,
        file_path="test.txt",
    )
    session.add(source)
    return source


def _make_result() -> CompilationResult:
    """Create a test compilation result."""
    return CompilationResult(
        title="Test Article",
        summary="A test summary.",
        key_claims=[],
        concepts=["testing"],
        backlink_suggestions=[],
        open_questions=["What is next?"],
        article_body="# Test\n\nThis is test content.",
    )


def _make_doc(source_id: str) -> NormalizedDocument:
    """Create a test normalized document."""
    return NormalizedDocument(
        raw_source_id=source_id,
        clean_text="Some test content for compilation.",
        title="Test Source",
        estimated_tokens=50,
    )


# ---------------------------------------------------------------------------
# DraftService unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_draft(db_session):
    """DraftService.create_draft persists a draft and updates source status."""
    service = DraftService()
    source = _make_source(db_session)
    await db_session.commit()
    await db_session.refresh(source)

    result = _make_result()
    takeaways = ["Takeaway 1", "Takeaway 2", "Takeaway 3"]

    doc = _make_doc(source.id)
    draft = await service.create_draft(source, doc, result, takeaways, db_session)

    assert draft.id
    assert draft.source_id == source.id
    assert draft.title == "Test Article"
    assert draft.status == "pending"
    assert json.loads(draft.key_takeaways) == takeaways

    # Source should be in review_pending
    await db_session.refresh(source)
    assert source.status == IngestStatus.REVIEW_PENDING


@pytest.mark.asyncio
async def test_get_draft_for_source(db_session):
    """DraftService.get_draft_for_source retrieves the pending draft."""
    service = DraftService()
    source = _make_source(db_session)
    await db_session.commit()
    await db_session.refresh(source)

    result = _make_result()
    doc = _make_doc(source.id)
    await service.create_draft(source, doc, result, ["t1"], db_session)

    found = await service.get_draft_for_source(source.id, db_session, TEST_USER_ID)
    assert found.source_id == source.id
    assert found.status == "pending"


@pytest.mark.asyncio
async def test_get_draft_not_found(db_session):
    """DraftService raises NotFoundError for missing drafts."""
    service = DraftService()
    with pytest.raises(NotFoundError):
        await service.get_draft_for_source("nonexistent", db_session, TEST_USER_ID)


@pytest.mark.asyncio
async def test_to_response(db_session):
    """DraftService.to_response produces a valid API response."""
    service = DraftService()
    source = _make_source(db_session)
    await db_session.commit()
    await db_session.refresh(source)

    result = _make_result()
    takeaways = ["First point", "Second point"]
    doc = _make_doc(source.id)
    draft = await service.create_draft(source, doc, result, takeaways, db_session)

    response = service.to_response(draft)
    assert isinstance(response, CompilationDraftResponse)
    assert response.key_takeaways == takeaways
    assert response.draft_body == result.article_body
    assert response.status == "pending"


@pytest.mark.asyncio
async def test_reject_draft(db_session):
    """DraftService.reject_draft resets source to pending."""
    service = DraftService()
    source = _make_source(db_session)
    await db_session.commit()
    await db_session.refresh(source)

    result = _make_result()
    doc = _make_doc(source.id)
    await service.create_draft(source, doc, result, ["t1"], db_session)

    resp = await service.reject_draft(source.id, db_session, TEST_USER_ID)
    assert resp.status == "rejected"
    assert resp.source_id == source.id

    # Source should be back to pending
    await db_session.refresh(source)
    assert source.status == IngestStatus.PENDING


@pytest.mark.asyncio
async def test_approve_draft_without_guidance(db_session):
    """DraftService.approve_draft saves the article from the original draft."""
    service = DraftService()
    source = _make_source(db_session)
    await db_session.commit()
    await db_session.refresh(source)

    result = _make_result()
    doc = _make_doc(source.id)
    await service.create_draft(source, doc, result, ["t1"], db_session)

    # Mock the compiler's save_article to avoid LLM calls
    mock_article = AsyncMock()
    mock_article.slug = "test-article"
    mock_article.title = "Test Article"

    with patch("wikimind.services.draft.Compiler") as MockCompiler:
        instance = MockCompiler.return_value
        instance.save_article = AsyncMock(return_value=mock_article)

        resp = await service.approve_draft(source.id, db_session, TEST_USER_ID)

    assert resp.status == "approved"
    assert resp.article_slug == "test-article"


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


def test_ingest_status_review_pending():
    """IngestStatus.REVIEW_PENDING is a valid enum value."""
    assert IngestStatus.REVIEW_PENDING == "review_pending"
    assert IngestStatus("review_pending") == IngestStatus.REVIEW_PENDING


def test_compilation_draft_model():
    """CompilationDraft model validates correctly."""
    draft = CompilationDraft(
        user_id=TEST_USER_ID,
        source_id="src-1",
        title="Test",
        summary="Summary",
        key_takeaways=json.dumps(["a", "b"]),
        draft_result_json="{}",
    )
    assert draft.status == "pending"
    assert draft.user_guidance is None


# ---------------------------------------------------------------------------
# API route tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_draft_endpoint_404(client):
    """GET /api/ingest/sources/{id}/draft returns 404 when no draft exists."""
    resp = await client.get("/api/ingest/sources/nonexistent/draft")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_reject_draft_endpoint_404(client):
    """POST /api/ingest/sources/{id}/draft/reject returns 404 when no draft."""
    resp = await client.post("/api/ingest/sources/nonexistent/draft/reject")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_approve_draft_endpoint_404(client):
    """POST /api/ingest/sources/{id}/draft/approve returns 404 when no draft."""
    resp = await client.post(
        "/api/ingest/sources/nonexistent/draft/approve",
        json={},
    )
    assert resp.status_code == 404
