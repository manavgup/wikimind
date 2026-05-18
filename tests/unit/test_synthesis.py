"""Tests for synthesis page creation, listing, and preview/refine/confirm workflow."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import TEST_USER_ID
from wikimind.engine.synthesis_compiler import (
    SynthesisCompiler,
    _find_relevant_articles,
)
from wikimind.models import (
    Article,
    CompletionResponse,
    PageType,
    Provider,
    SynthesisCompilationResult,
)

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def two_articles(db_session: AsyncSession) -> list[Article]:
    """Create two articles for synthesis testing."""
    a1 = Article(
        slug="attention-is-all-you-need",
        title="Attention Is All You Need",
        file_path="transformers/attention.md",
        summary="Introduces the transformer architecture",
        concept_ids=json.dumps(["transformers", "attention"]),
        page_type=PageType.SOURCE,
        user_id=TEST_USER_ID,
    )
    a2 = Article(
        slug="bert-pretraining",
        title="BERT: Pre-training of Deep Bidirectional Transformers",
        file_path="transformers/bert.md",
        summary="Pre-training bidirectional transformers for NLP",
        concept_ids=json.dumps(["transformers", "bert", "nlp"]),
        page_type=PageType.SOURCE,
        user_id=TEST_USER_ID,
    )
    db_session.add(a1)
    db_session.add(a2)
    await db_session.commit()
    await db_session.refresh(a1)
    await db_session.refresh(a2)
    return [a1, a2]


# ---------------------------------------------------------------------------
# Unit: _find_relevant_articles
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_relevant_articles_by_ids(
    db_session: AsyncSession,
    two_articles: list[Article],
) -> None:
    """When article_ids are provided, return those exact articles."""
    ids = [a.id for a in two_articles]
    found = await _find_relevant_articles(
        "transformers",
        db_session,
        TEST_USER_ID,
        article_ids=ids,
    )
    assert len(found) == 2
    assert {a.id for a in found} == set(ids)


@pytest.mark.asyncio
async def test_find_relevant_articles_by_keyword(
    db_session: AsyncSession,
    two_articles: list[Article],
) -> None:
    """Keyword search matches articles by title and concepts."""
    found = await _find_relevant_articles(
        "transformers attention",
        db_session,
        TEST_USER_ID,
    )
    assert len(found) >= 1
    slugs = {a.slug for a in found}
    assert "attention-is-all-you-need" in slugs


@pytest.mark.asyncio
async def test_find_relevant_articles_no_match(
    db_session: AsyncSession,
    two_articles: list[Article],
) -> None:
    """Returns empty list when no articles match."""
    found = await _find_relevant_articles(
        "quantum computing",
        db_session,
        TEST_USER_ID,
    )
    assert len(found) == 0


# ---------------------------------------------------------------------------
# Unit: SynthesisCompiler.synthesize
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_not_enough_articles(
    db_session: AsyncSession,
) -> None:
    """Returns None when fewer than 2 articles match."""
    compiler = SynthesisCompiler(TEST_USER_ID)
    result = await compiler.synthesize("nonexistent topic", db_session)
    assert result is None


MOCK_SYNTHESIS_JSON = json.dumps(
    {
        "title": "Transformer Architecture Evolution",
        "summary": "Analysis of transformer development across papers.",
        "themes": ["Self-attention", "Pre-training"],
        "comparisons": "Both papers use attention mechanisms but differ in scope.",
        "contradictions": "No major contradictions found.",
        "timeline": "2017: Attention paper. 2018: BERT.",
        "gaps": ["Multi-modal transformers not covered"],
        "open_questions": ["How will transformers scale?"],
        "article_body": "## Themes\n\nBoth papers...\n\n" + "x " * 300,
        "concepts": ["transformers", "attention"],
    }
)


@pytest.mark.asyncio
async def test_synthesize_success(
    db_session: AsyncSession,
    two_articles: list[Article],
    tmp_path,
    monkeypatch,
) -> None:
    """Successful synthesis creates an article with page_type=synthesis."""
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path / "wikimind"))

    from wikimind.config import get_settings

    get_settings.cache_clear()

    mock_response = CompletionResponse(
        content=MOCK_SYNTHESIS_JSON,
        provider_used=Provider.MOCK,
        model_used="mock-1",
        input_tokens=100,
        output_tokens=200,
        cost_usd=0.01,
        latency_ms=500,
    )
    mock_router = MagicMock()
    mock_router.complete = AsyncMock(return_value=mock_response)
    mock_router.parse_json_response = MagicMock(
        return_value=json.loads(MOCK_SYNTHESIS_JSON),
    )

    with patch(
        "wikimind.engine.base_compiler.get_llm_router",
        return_value=mock_router,
    ):
        compiler = SynthesisCompiler(TEST_USER_ID)
        ids = [a.id for a in two_articles]
        result = await compiler.synthesize(
            "Compare transformer architectures",
            db_session,
            article_ids=ids,
        )

    assert result is not None
    article, compilation = result
    assert article.page_type == PageType.SYNTHESIS
    assert article.slug.startswith("synthesis-")
    assert compilation.themes == ["Self-attention", "Pre-training"]
    assert len(compilation.source_article_ids) == 2


# ---------------------------------------------------------------------------
# API: POST /api/wiki/synthesize
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_synthesis_api_no_articles(client: AsyncClient) -> None:
    """POST /api/wiki/synthesize returns 422 when no matching articles exist."""
    resp = await client.post(
        "/api/wiki/synthesize",
        json={"query": "nonexistent topic xyz"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_synthesis_api_validation(client: AsyncClient) -> None:
    """POST /api/wiki/synthesize rejects too-short queries."""
    resp = await client.post(
        "/api/wiki/synthesize",
        json={"query": "ab"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_synthesis_pages_empty(client: AsyncClient) -> None:
    """GET /api/wiki/synthesis returns empty list initially."""
    resp = await client.get("/api/wiki/synthesis")
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


def test_synthesis_compilation_result_model() -> None:
    """SynthesisCompilationResult validates correctly."""
    result = SynthesisCompilationResult(
        title="Test Synthesis",
        query="Compare approaches",
        summary="A synthesis of approaches.",
        themes=["Theme A", "Theme B"],
        comparisons="Sources differ on X.",
        contradictions="Source A says X, Source B says Y.",
        timeline="2020: A. 2021: B.",
        gaps=["Gap 1"],
        open_questions=["Question 1"],
        article_body="Full markdown body here.",
        source_article_ids=["id-1", "id-2"],
        concepts=["concept-1"],
    )
    assert result.page_type == PageType.SYNTHESIS
    assert len(result.themes) == 2
    assert len(result.source_article_ids) == 2


# ---------------------------------------------------------------------------
# Unit: SynthesisCompiler.preview
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preview_not_enough_articles(
    db_session: AsyncSession,
) -> None:
    """Preview returns None when fewer than 2 articles are found."""
    compiler = SynthesisCompiler(TEST_USER_ID)
    result = await compiler.preview(
        session=db_session,
        article_ids=["nonexistent-id"],
    )
    assert result is None


@pytest.mark.asyncio
async def test_preview_success(
    db_session: AsyncSession,
    two_articles: list[Article],
    tmp_path,
    monkeypatch,
) -> None:
    """Preview returns a SynthesisCompilationResult without saving anything."""
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path / "wikimind"))

    from wikimind.config import get_settings

    get_settings.cache_clear()

    mock_response = CompletionResponse(
        content=MOCK_SYNTHESIS_JSON,
        provider_used=Provider.MOCK,
        model_used="mock-1",
        input_tokens=100,
        output_tokens=200,
        cost_usd=0.01,
        latency_ms=500,
    )
    mock_router = MagicMock()
    mock_router.complete = AsyncMock(return_value=mock_response)
    mock_router.parse_json_response = MagicMock(
        return_value=json.loads(MOCK_SYNTHESIS_JSON),
    )

    with patch(
        "wikimind.engine.base_compiler.get_llm_router",
        return_value=mock_router,
    ):
        compiler = SynthesisCompiler(TEST_USER_ID)
        ids = [a.id for a in two_articles]
        result = await compiler.preview(
            session=db_session,
            article_ids=ids,
            guidance="Compare transformer architectures",
        )

    assert result is not None
    assert result.title == "Transformer Architecture Evolution"
    assert result.themes == ["Self-attention", "Pre-training"]
    assert len(result.source_article_ids) == 2


# ---------------------------------------------------------------------------
# Unit: SynthesisCompiler.refine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refine_not_enough_articles(
    db_session: AsyncSession,
) -> None:
    """Refine returns None when fewer than 2 articles are found."""
    compiler = SynthesisCompiler(TEST_USER_ID)
    result = await compiler.refine(
        session=db_session,
        article_ids=["nonexistent-id"],
        previous_draft="Some draft content",
        guidance="Focus more on attention mechanisms",
    )
    assert result is None


@pytest.mark.asyncio
async def test_refine_success(
    db_session: AsyncSession,
    two_articles: list[Article],
    tmp_path,
    monkeypatch,
) -> None:
    """Refine returns a refined SynthesisCompilationResult."""
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path / "wikimind"))

    from wikimind.config import get_settings

    get_settings.cache_clear()

    mock_response = CompletionResponse(
        content=MOCK_SYNTHESIS_JSON,
        provider_used=Provider.MOCK,
        model_used="mock-1",
        input_tokens=100,
        output_tokens=200,
        cost_usd=0.01,
        latency_ms=500,
    )
    mock_router = MagicMock()
    mock_router.complete = AsyncMock(return_value=mock_response)
    mock_router.parse_json_response = MagicMock(
        return_value=json.loads(MOCK_SYNTHESIS_JSON),
    )

    with patch(
        "wikimind.engine.base_compiler.get_llm_router",
        return_value=mock_router,
    ):
        compiler = SynthesisCompiler(TEST_USER_ID)
        ids = [a.id for a in two_articles]
        result = await compiler.refine(
            session=db_session,
            article_ids=ids,
            previous_draft="## Old draft\n\nSome content here",
            guidance="Focus more on attention mechanisms",
        )

    assert result is not None
    assert result.title == "Transformer Architecture Evolution"
    assert result.themes == ["Self-attention", "Pre-training"]


# ---------------------------------------------------------------------------
# Unit: SynthesisCompiler.confirm
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirm_not_enough_articles(
    db_session: AsyncSession,
) -> None:
    """Confirm returns None when fewer than 2 articles are found."""
    compiler = SynthesisCompiler(TEST_USER_ID)
    result = await compiler.confirm(
        session=db_session,
        title="My Synthesis",
        draft_content="## Draft\n\nContent",
        article_ids=["nonexistent-id"],
    )
    assert result is None


@pytest.mark.asyncio
async def test_confirm_success(
    db_session: AsyncSession,
    two_articles: list[Article],
    tmp_path,
    monkeypatch,
) -> None:
    """Confirm saves the draft as a synthesis article."""
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path / "wikimind"))

    from wikimind.config import get_settings

    get_settings.cache_clear()

    with patch(
        "wikimind.engine.base_compiler.get_llm_router",
        return_value=MagicMock(),
    ):
        compiler = SynthesisCompiler(TEST_USER_ID)
        ids = [a.id for a in two_articles]
        article = await compiler.confirm(
            session=db_session,
            title="Transformer Architecture Evolution",
            draft_content="## Themes\n\nBoth papers use attention...",
            article_ids=ids,
        )

    assert article is not None
    assert article.page_type == PageType.SYNTHESIS
    assert article.slug.startswith("synthesis-")
    assert article.title == "Transformer Architecture Evolution"
    assert article.file_path == f"synthesis/{article.slug}.md"


# ---------------------------------------------------------------------------
# API: POST /api/wiki/synthesis/preview
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preview_api_not_enough_articles(client: AsyncClient) -> None:
    """POST /api/wiki/synthesis/preview returns 422 when articles don't exist."""
    resp = await client.post(
        "/api/wiki/synthesis/preview",
        json={"article_ids": ["fake-id-1", "fake-id-2"]},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_preview_api_validation_too_few_ids(client: AsyncClient) -> None:
    """POST /api/wiki/synthesis/preview rejects fewer than 2 article_ids."""
    resp = await client.post(
        "/api/wiki/synthesis/preview",
        json={"article_ids": ["only-one"]},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# API: POST /api/wiki/synthesis/refine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refine_api_not_enough_articles(client: AsyncClient) -> None:
    """POST /api/wiki/synthesis/refine returns 422 when articles don't exist."""
    resp = await client.post(
        "/api/wiki/synthesis/refine",
        json={
            "draft_content": "## Draft\n\nContent",
            "article_ids": ["fake-id-1", "fake-id-2"],
            "guidance": "More focus on attention",
        },
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# API: POST /api/wiki/synthesis/confirm
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirm_api_not_enough_articles(client: AsyncClient) -> None:
    """POST /api/wiki/synthesis/confirm returns 422 when articles don't exist."""
    resp = await client.post(
        "/api/wiki/synthesis/confirm",
        json={
            "title": "My Synthesis",
            "draft_content": "## Draft\n\nContent",
            "article_ids": ["fake-id-1", "fake-id-2"],
        },
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Integration: full preview → refine → confirm flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preview_refine_confirm_flow(
    db_session: AsyncSession,
    two_articles: list[Article],
    tmp_path,
    monkeypatch,
) -> None:
    """Full preview → refine → confirm creates a persisted synthesis article."""
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path / "wikimind"))

    from wikimind.config import get_settings

    get_settings.cache_clear()

    mock_response = CompletionResponse(
        content=MOCK_SYNTHESIS_JSON,
        provider_used=Provider.MOCK,
        model_used="mock-1",
        input_tokens=100,
        output_tokens=200,
        cost_usd=0.01,
        latency_ms=500,
    )
    mock_router = MagicMock()
    mock_router.complete = AsyncMock(return_value=mock_response)
    mock_router.parse_json_response = MagicMock(
        return_value=json.loads(MOCK_SYNTHESIS_JSON),
    )

    ids = [a.id for a in two_articles]

    with patch(
        "wikimind.engine.base_compiler.get_llm_router",
        return_value=mock_router,
    ):
        compiler = SynthesisCompiler(TEST_USER_ID)

        # Step 1: Preview
        preview_result = await compiler.preview(
            session=db_session,
            article_ids=ids,
            guidance="Compare transformer architectures",
        )
        assert preview_result is not None
        assert preview_result.article_body

        # Step 2: Refine
        refined = await compiler.refine(
            session=db_session,
            article_ids=ids,
            previous_draft=preview_result.article_body,
            guidance="Focus more on attention mechanisms",
        )
        assert refined is not None
        assert refined.article_body

        # Step 3: Confirm
        article = await compiler.confirm(
            session=db_session,
            title=refined.title,
            draft_content=refined.article_body,
            article_ids=ids,
        )

    assert article is not None
    assert article.page_type == PageType.SYNTHESIS
    assert article.title == "Transformer Architecture Evolution"
    assert article.slug.startswith("synthesis-")
