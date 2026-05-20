"""Tests for the synthesis compiler engine (engine/synthesis_compiler.py).

Covers _find_relevant_articles scoring, _build_synthesis_material,
and the SynthesisCompiler.synthesize flow with mocked LLM.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import TEST_USER_ID
from wikimind.config import get_settings
from wikimind.engine.synthesis_compiler import (
    SynthesisCompiler,
    _build_synthesis_material,
    _find_relevant_articles,
)
from wikimind.models import (
    Article,
    CompletionResponse,
    PageType,
    Provider,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _wiki_root() -> Path:
    """Return the wiki storage root for TEST_USER_ID and ensure it exists."""
    settings = get_settings()
    root = Path(settings.data_dir) / "wiki" / TEST_USER_ID
    root.mkdir(parents=True, exist_ok=True)
    return root


def _make_article(
    *,
    article_id: str,
    title: str,
    slug: str,
    summary: str = "",
    concept_ids: list[str] | None = None,
    page_type: PageType = PageType.SOURCE,
) -> Article:
    return Article(
        id=article_id,
        slug=slug,
        title=title,
        file_path=f"{slug}.md",
        summary=summary,
        concept_ids=json.dumps(concept_ids) if concept_ids else None,
        page_type=page_type,
        user_id=TEST_USER_ID,
    )


# ---------------------------------------------------------------------------
# _find_relevant_articles — explicit IDs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_relevant_articles_by_ids(db_session: AsyncSession) -> None:
    """When article_ids is provided, returns exactly those articles."""
    a1 = _make_article(article_id="a1", title="Alpha", slug="alpha")
    a2 = _make_article(article_id="a2", title="Beta", slug="beta")
    a3 = _make_article(article_id="a3", title="Gamma", slug="gamma")
    db_session.add_all([a1, a2, a3])
    await db_session.commit()

    result = await _find_relevant_articles(
        "anything",
        db_session,
        TEST_USER_ID,
        article_ids=["a1", "a3"],
    )
    found_ids = {a.id for a in result}
    assert found_ids == {"a1", "a3"}


# ---------------------------------------------------------------------------
# _find_relevant_articles — keyword scoring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_relevant_articles_by_keyword(db_session: AsyncSession) -> None:
    """Without explicit IDs, articles are scored by title/summary/concept overlap."""
    a1 = _make_article(
        article_id="a1",
        title="Machine Learning Basics",
        slug="ml-basics",
        summary="An introduction to machine learning.",
        concept_ids=["machine-learning"],
    )
    a2 = _make_article(
        article_id="a2",
        title="Deep Learning",
        slug="deep-learning",
        summary="Neural network architectures.",
        concept_ids=["deep-learning", "neural-networks"],
    )
    a3 = _make_article(
        article_id="a3",
        title="Cooking Recipes",
        slug="cooking",
        summary="Pasta and pizza recipes.",
        concept_ids=["cooking"],
    )
    db_session.add_all([a1, a2, a3])
    await db_session.commit()

    result = await _find_relevant_articles(
        "machine learning neural",
        db_session,
        TEST_USER_ID,
    )
    # a1 and a2 should be found (matching terms), a3 should not
    found_ids = {a.id for a in result}
    assert "a1" in found_ids
    assert "a2" in found_ids
    assert "a3" not in found_ids


@pytest.mark.asyncio
async def test_find_relevant_articles_excludes_synthesis_pages(db_session: AsyncSession) -> None:
    """Keyword search only considers SOURCE and CONCEPT page types."""
    a1 = _make_article(
        article_id="a1",
        title="Machine Learning",
        slug="ml",
        page_type=PageType.SOURCE,
    )
    a2 = _make_article(
        article_id="a2",
        title="Machine Learning Synthesis",
        slug="ml-synth",
        page_type=PageType.SYNTHESIS,
    )
    db_session.add_all([a1, a2])
    await db_session.commit()

    result = await _find_relevant_articles(
        "machine learning",
        db_session,
        TEST_USER_ID,
    )
    found_ids = {a.id for a in result}
    assert "a1" in found_ids
    assert "a2" not in found_ids


@pytest.mark.asyncio
async def test_find_relevant_articles_no_matches(db_session: AsyncSession) -> None:
    """When no articles match, returns empty list."""
    a1 = _make_article(article_id="a1", title="Cooking Recipes", slug="cooking")
    db_session.add(a1)
    await db_session.commit()

    result = await _find_relevant_articles(
        "quantum computing",
        db_session,
        TEST_USER_ID,
    )
    assert result == []


# ---------------------------------------------------------------------------
# _build_synthesis_material
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_synthesis_material() -> None:
    """Synthesis material includes article titles and content."""
    wiki = _wiki_root()
    (wiki / "alpha.md").write_text("# Alpha\n\nAlpha content here.")
    (wiki / "beta.md").write_text("# Beta\n\nBeta content here.")

    articles = [
        _make_article(article_id="a1", title="Alpha", slug="alpha", summary="Alpha summary"),
        _make_article(article_id="a2", title="Beta", slug="beta", summary="Beta summary"),
    ]

    material = await _build_synthesis_material(articles, TEST_USER_ID)
    assert "Source 1: Alpha" in material
    assert "Source 2: Beta" in material
    assert "Alpha summary" in material
    assert "Alpha content here." in material
    assert "Beta content here." in material


@pytest.mark.asyncio
async def test_build_synthesis_material_missing_file() -> None:
    """Articles with missing files still appear in material (title/summary only)."""
    articles = [
        _make_article(
            article_id="a1",
            title="Missing File",
            slug="missing",
            summary="Summary only",
        ),
    ]

    material = await _build_synthesis_material(articles, TEST_USER_ID)
    assert "Source 1: Missing File" in material
    assert "Summary only" in material


# ---------------------------------------------------------------------------
# SynthesisCompiler.synthesize — mocked LLM
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_requires_at_least_two_articles(db_session: AsyncSession) -> None:
    """Synthesize returns None when fewer than 2 articles are found."""
    a1 = _make_article(article_id="a1", title="Lonely Article", slug="lonely")
    db_session.add(a1)
    await db_session.commit()

    with patch("wikimind.engine.base_compiler.get_llm_router"):
        compiler = SynthesisCompiler(user_id=TEST_USER_ID)
        result = await compiler.synthesize(
            "lonely article",
            db_session,
            article_ids=["a1"],
        )

    assert result is None


@pytest.mark.asyncio
async def test_synthesize_success(db_session: AsyncSession) -> None:
    """Synthesize creates an article and returns the compilation result."""
    wiki = _wiki_root()
    (wiki / "alpha.md").write_text("# Alpha\n\nAlpha body.")
    (wiki / "beta.md").write_text("# Beta\n\nBeta body.")

    a1 = _make_article(
        article_id="a1",
        title="Alpha",
        slug="alpha",
        summary="Alpha summary",
        concept_ids=["testing"],
    )
    a2 = _make_article(
        article_id="a2",
        title="Beta",
        slug="beta",
        summary="Beta summary",
        concept_ids=["testing"],
    )
    db_session.add_all([a1, a2])
    await db_session.commit()

    synthesis_json = json.dumps(
        {
            "title": "Alpha vs Beta",
            "summary": "Comparison of Alpha and Beta.",
            "themes": ["theme1"],
            "comparisons": "Alpha does X, Beta does Y.",
            "contradictions": "None found.",
            "timeline": "Alpha first, then Beta.",
            "gaps": ["gap1"],
            "open_questions": ["question1"],
            "article_body": "Full analysis body.",
            "concepts": ["testing"],
        }
    )

    mock_response = CompletionResponse(
        content=synthesis_json,
        provider_used=Provider.MOCK,
        model_used="mock",
        input_tokens=100,
        output_tokens=200,
        cost_usd=0.0,
        latency_ms=50,
    )

    mock_router = MagicMock()
    mock_router.complete = AsyncMock(return_value=mock_response)
    mock_router.parse_json_response = MagicMock(return_value=json.loads(synthesis_json))
    mock_router.settings = get_settings()

    with (
        patch("wikimind.engine.base_compiler.get_llm_router", return_value=mock_router),
        patch(
            "wikimind.services.plan_routing.plan_aware_complete",
            AsyncMock(return_value=mock_response),
        ),
    ):
        compiler = SynthesisCompiler(user_id=TEST_USER_ID)
        result = await compiler.synthesize(
            "compare alpha beta",
            db_session,
            article_ids=["a1", "a2"],
        )

    assert result is not None
    article, compilation = result
    assert article.page_type == PageType.SYNTHESIS
    assert article.user_id == TEST_USER_ID
    assert compilation.title == "Alpha vs Beta"
    assert len(compilation.source_article_ids) == 2


@pytest.mark.asyncio
async def test_synthesize_llm_returns_none(db_session: AsyncSession) -> None:
    """When LLM call returns None, synthesize returns None."""
    a1 = _make_article(article_id="a1", title="Alpha", slug="alpha")
    a2 = _make_article(article_id="a2", title="Beta", slug="beta")
    db_session.add_all([a1, a2])
    await db_session.commit()

    mock_router = MagicMock()
    mock_router.settings = get_settings()

    with (
        patch("wikimind.engine.base_compiler.get_llm_router", return_value=mock_router),
        patch(
            "wikimind.services.plan_routing.plan_aware_complete",
            AsyncMock(return_value=None),
        ),
    ):
        compiler = SynthesisCompiler(user_id=TEST_USER_ID)
        result = await compiler.synthesize(
            "compare alpha beta",
            db_session,
            article_ids=["a1", "a2"],
        )

    assert result is None
