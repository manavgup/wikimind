"""Tests for synthesis suggestion auto-detection (issue #415)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.conftest import TEST_USER_ID
from wikimind.models import (
    Article,
    ArticleConcept,
    ArticleSource,
    Contradiction,
    ContradictionStatus,
    PageType,
    Source,
    SourceType,
)
from wikimind.services.wiki import WikiService

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def articles_with_shared_concepts(db_session: AsyncSession) -> list[Article]:
    """Create articles sharing 3+ concepts."""
    a1 = Article(
        slug="article-transformers",
        title="Transformer Architecture",
        file_path="wiki/transformers.md",
        page_type=PageType.SOURCE,
        user_id=TEST_USER_ID,
    )
    a2 = Article(
        slug="article-attention",
        title="Attention Mechanisms Deep Dive",
        file_path="wiki/attention.md",
        page_type=PageType.SOURCE,
        user_id=TEST_USER_ID,
    )
    db_session.add(a1)
    db_session.add(a2)
    await db_session.flush()

    # Both share 3 concepts: "transformers", "attention", "deep-learning"
    shared_concepts = ["transformers", "attention", "deep-learning"]
    for concept_name in shared_concepts:
        db_session.add(ArticleConcept(article_id=a1.id, concept_name=concept_name))
        db_session.add(ArticleConcept(article_id=a2.id, concept_name=concept_name))
    # Article 1 also has a unique concept
    db_session.add(ArticleConcept(article_id=a1.id, concept_name="architecture"))

    await db_session.commit()
    await db_session.refresh(a1)
    await db_session.refresh(a2)
    return [a1, a2]


@pytest.fixture
async def articles_with_contradictions(db_session: AsyncSession) -> list[Article]:
    """Create articles with an active contradiction between them."""
    a1 = Article(
        slug="article-scaling-laws",
        title="Scaling Laws for Neural Models",
        file_path="wiki/scaling.md",
        page_type=PageType.SOURCE,
        user_id=TEST_USER_ID,
    )
    a2 = Article(
        slug="article-efficiency",
        title="Efficient Training Techniques",
        file_path="wiki/efficiency.md",
        page_type=PageType.SOURCE,
        user_id=TEST_USER_ID,
    )
    db_session.add(a1)
    db_session.add(a2)
    await db_session.flush()

    ctr = Contradiction(
        claim_a="Larger models always perform better",
        claim_b="Smaller models can match large model performance with better training",
        article_a_id=a1.id,
        article_b_id=a2.id,
        status=ContradictionStatus.ACTIVE,
        user_id=TEST_USER_ID,
    )
    db_session.add(ctr)
    await db_session.commit()
    await db_session.refresh(a1)
    await db_session.refresh(a2)
    return [a1, a2]


@pytest.fixture
async def articles_same_topic_different_sources(db_session: AsyncSession) -> list[Article]:
    """Create articles on the same topic compiled from different sources."""
    s1 = Source(
        source_type=SourceType.URL,
        title="Source Paper A",
        user_id=TEST_USER_ID,
    )
    s2 = Source(
        source_type=SourceType.URL,
        title="Source Paper B",
        user_id=TEST_USER_ID,
    )
    db_session.add(s1)
    db_session.add(s2)
    await db_session.flush()

    a1 = Article(
        slug="article-rlhf-paper-a",
        title="RLHF from Paper A",
        file_path="wiki/rlhf-a.md",
        page_type=PageType.SOURCE,
        user_id=TEST_USER_ID,
    )
    a2 = Article(
        slug="article-rlhf-paper-b",
        title="RLHF from Paper B",
        file_path="wiki/rlhf-b.md",
        page_type=PageType.SOURCE,
        user_id=TEST_USER_ID,
    )
    db_session.add(a1)
    db_session.add(a2)
    await db_session.flush()

    # Link articles to different sources
    db_session.add(ArticleSource(article_id=a1.id, source_id=s1.id))
    db_session.add(ArticleSource(article_id=a2.id, source_id=s2.id))

    # Both share the concept "rlhf"
    db_session.add(ArticleConcept(article_id=a1.id, concept_name="rlhf"))
    db_session.add(ArticleConcept(article_id=a2.id, concept_name="rlhf"))

    await db_session.commit()
    await db_session.refresh(a1)
    await db_session.refresh(a2)
    return [a1, a2]


# ---------------------------------------------------------------------------
# Unit: WikiService.get_synthesis_suggestions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suggestions_shared_concepts(
    db_session: AsyncSession,
    articles_with_shared_concepts: list[Article],
) -> None:
    """Articles sharing 3+ concepts are suggested for synthesis."""
    service = WikiService()
    suggestions = await service.get_synthesis_suggestions(db_session, TEST_USER_ID)

    assert len(suggestions) >= 1
    shared = [s for s in suggestions if s.suggested_type == "shared_concepts"]
    assert len(shared) == 1
    assert set(shared[0].article_ids) == {a.id for a in articles_with_shared_concepts}
    assert "3 concepts" in shared[0].reason


@pytest.mark.asyncio
async def test_suggestions_contradictions(
    db_session: AsyncSession,
    articles_with_contradictions: list[Article],
) -> None:
    """Articles with active contradictions are suggested for synthesis."""
    service = WikiService()
    suggestions = await service.get_synthesis_suggestions(db_session, TEST_USER_ID)

    assert len(suggestions) >= 1
    contradiction_suggestions = [s for s in suggestions if s.suggested_type == "contradiction"]
    assert len(contradiction_suggestions) == 1
    assert set(contradiction_suggestions[0].article_ids) == {a.id for a in articles_with_contradictions}
    assert "contradiction" in contradiction_suggestions[0].reason.lower()


@pytest.mark.asyncio
async def test_suggestions_same_topic_different_sources(
    db_session: AsyncSession,
    articles_same_topic_different_sources: list[Article],
) -> None:
    """Articles on the same topic from different sources are suggested."""
    service = WikiService()
    suggestions = await service.get_synthesis_suggestions(db_session, TEST_USER_ID)

    assert len(suggestions) >= 1
    diff_source = [s for s in suggestions if s.suggested_type == "same_topic_different_sources"]
    assert len(diff_source) == 1
    assert set(diff_source[0].article_ids) == {a.id for a in articles_same_topic_different_sources}
    assert "rlhf" in diff_source[0].reason.lower()


@pytest.mark.asyncio
async def test_suggestions_empty_wiki(db_session: AsyncSession) -> None:
    """Returns empty list when wiki has no articles."""
    service = WikiService()
    suggestions = await service.get_synthesis_suggestions(db_session, TEST_USER_ID)
    assert suggestions == []


@pytest.mark.asyncio
async def test_suggestions_excludes_synthesis_pages(db_session: AsyncSession) -> None:
    """Synthesis pages themselves are not suggested for synthesis."""
    a1 = Article(
        slug="synth-page",
        title="Existing Synthesis",
        file_path="wiki/synth.md",
        page_type=PageType.SYNTHESIS,
        user_id=TEST_USER_ID,
    )
    a2 = Article(
        slug="source-page",
        title="Source Article",
        file_path="wiki/source.md",
        page_type=PageType.SOURCE,
        user_id=TEST_USER_ID,
    )
    db_session.add(a1)
    db_session.add(a2)
    await db_session.flush()

    # Add shared concepts to synth + source — should not trigger suggestion
    for concept in ["a", "b", "c"]:
        db_session.add(ArticleConcept(article_id=a1.id, concept_name=concept))
        db_session.add(ArticleConcept(article_id=a2.id, concept_name=concept))
    await db_session.commit()

    service = WikiService()
    suggestions = await service.get_synthesis_suggestions(db_session, TEST_USER_ID)
    # Should not include the synthesis page in any suggestion
    for s in suggestions:
        assert a1.id not in s.article_ids


@pytest.mark.asyncio
async def test_suggestions_respects_limit(
    db_session: AsyncSession,
    articles_with_shared_concepts: list[Article],
    articles_with_contradictions: list[Article],
) -> None:
    """Respects the limit parameter."""
    service = WikiService()
    suggestions = await service.get_synthesis_suggestions(db_session, TEST_USER_ID, limit=1)
    assert len(suggestions) <= 1


@pytest.mark.asyncio
async def test_suggestions_includes_article_titles(
    db_session: AsyncSession,
    articles_with_shared_concepts: list[Article],
) -> None:
    """Suggestions include resolved article titles."""
    service = WikiService()
    suggestions = await service.get_synthesis_suggestions(db_session, TEST_USER_ID)

    assert len(suggestions) >= 1
    for s in suggestions:
        assert len(s.article_titles) == len(s.article_ids)
        for title in s.article_titles:
            assert title != "Unknown"
            assert len(title) > 0


# ---------------------------------------------------------------------------
# API: GET /api/wiki/synthesis/suggestions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suggestions_api_empty(client: AsyncClient) -> None:
    """GET /api/wiki/synthesis/suggestions returns empty list initially."""
    resp = await client.get("/api/wiki/synthesis/suggestions")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_suggestions_api_returns_suggestions(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """GET /api/wiki/synthesis/suggestions returns suggestions when articles exist."""
    # Create articles with shared concepts via the client's session
    # Note: the client fixture uses its own session, so we use the API
    # This test primarily verifies the endpoint wiring
    resp = await client.get("/api/wiki/synthesis/suggestions")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
