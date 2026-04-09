"""Tests for the two-stage wikilink resolution algorithm."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind._datetime import utcnow_naive
from wikimind.engine.wikilink_resolver import resolve_backlink_candidates
from wikimind.models import Article, ConfidenceLevel


async def _make_article(
    session: AsyncSession,
    title: str,
    slug: str | None = None,
    created_at: datetime | None = None,
) -> Article:
    article = Article(
        id=str(uuid.uuid4()),
        slug=slug or title.lower().replace(" ", "-"),
        title=title,
        file_path=f"/tmp/{slug or title}.md",
        confidence=ConfidenceLevel.SOURCED,
        created_at=created_at or utcnow_naive(),
    )
    session.add(article)
    await session.commit()
    await session.refresh(article)
    return article


@pytest.mark.asyncio
async def test_exact_match_resolves(db_session: AsyncSession) -> None:
    existing = await _make_article(db_session, "Machine Learning")
    resolved, unresolved = await resolve_backlink_candidates(["Machine Learning"], db_session)
    assert len(resolved) == 1
    assert resolved[0].target_id == existing.id
    assert resolved[0].candidate_text == "Machine Learning"
    assert resolved[0].target_title == "Machine Learning"
    assert unresolved == []


@pytest.mark.asyncio
async def test_case_insensitive_exact_match_resolves(db_session: AsyncSession) -> None:
    existing = await _make_article(db_session, "Machine Learning")
    resolved, unresolved = await resolve_backlink_candidates(["machine learning"], db_session)
    assert len(resolved) == 1
    assert resolved[0].target_id == existing.id
    assert unresolved == []


@pytest.mark.asyncio
async def test_normalized_match_resolves(db_session: AsyncSession) -> None:
    """Stage 2: candidate differs from title by punctuation only."""
    existing = await _make_article(db_session, "Karpathy's Wiki Pattern")
    resolved, unresolved = await resolve_backlink_candidates(["Karpathys Wiki Pattern"], db_session)
    assert len(resolved) == 1
    assert resolved[0].target_id == existing.id
    assert unresolved == []


@pytest.mark.asyncio
async def test_underscore_to_space_resolves_via_normalizer(db_session: AsyncSession) -> None:
    existing = await _make_article(db_session, "Machine Learning Ops")
    resolved, _unresolved = await resolve_backlink_candidates(["machine_learning_ops"], db_session)
    assert len(resolved) == 1
    assert resolved[0].target_id == existing.id


@pytest.mark.asyncio
async def test_no_match_stays_unresolved(db_session: AsyncSession) -> None:
    await _make_article(db_session, "Machine Learning")
    resolved, unresolved = await resolve_backlink_candidates(["Quantum Computing"], db_session)
    assert resolved == []
    assert unresolved == ["Quantum Computing"]


@pytest.mark.asyncio
async def test_similar_but_distinct_does_not_match(db_session: AsyncSession) -> None:
    """Reject 'Machine Learning Ops' as a match for 'Machine Learning' — no fuzzy."""
    await _make_article(db_session, "Machine Learning")
    resolved, unresolved = await resolve_backlink_candidates(["Machine Learning Ops"], db_session)
    assert resolved == []
    assert unresolved == ["Machine Learning Ops"]


@pytest.mark.asyncio
async def test_mixed_resolved_and_unresolved(db_session: AsyncSession) -> None:
    await _make_article(db_session, "React")
    await _make_article(db_session, "TypeScript")
    resolved, unresolved = await resolve_backlink_candidates(["React", "Redux", "TypeScript", "Zustand"], db_session)
    assert len(resolved) == 2
    assert sorted(unresolved) == ["Redux", "Zustand"]
    resolved_titles = sorted(r.target_title for r in resolved)
    assert resolved_titles == ["React", "TypeScript"]


@pytest.mark.asyncio
async def test_duplicate_candidates_deduped_in_resolved(db_session: AsyncSession) -> None:
    """Two candidates resolving to the same target produce ONE ResolvedBacklink."""
    await _make_article(db_session, "React")
    resolved, unresolved = await resolve_backlink_candidates(["React", "react"], db_session)
    assert len(resolved) == 1
    assert unresolved == []


@pytest.mark.asyncio
async def test_ambiguous_normalized_match_picks_earliest(db_session: AsyncSession) -> None:
    """Two articles with the same normalized form → pick the earliest created_at."""
    older = await _make_article(
        db_session,
        "Machine Learning",
        slug="machine-learning-older",
        created_at=datetime(2026, 1, 1),
    )
    await _make_article(
        db_session,
        "machine-learning",
        slug="machine-learning-newer",
        created_at=datetime(2026, 2, 1),
    )
    resolved, _ = await resolve_backlink_candidates(["Machine Learning"], db_session)
    assert len(resolved) == 1
    assert resolved[0].target_id == older.id


@pytest.mark.asyncio
async def test_exclude_self_reference(db_session: AsyncSession) -> None:
    """A candidate that matches the article currently being compiled is excluded."""
    self_article = await _make_article(db_session, "Self Article")
    other = await _make_article(db_session, "Other Article")
    resolved, unresolved = await resolve_backlink_candidates(
        ["Self Article", "Other Article"],
        db_session,
        exclude_article_id=self_article.id,
    )
    assert len(resolved) == 1
    assert resolved[0].target_id == other.id
    assert unresolved == ["Self Article"]


@pytest.mark.asyncio
async def test_empty_candidate_list(db_session: AsyncSession) -> None:
    resolved, unresolved = await resolve_backlink_candidates([], db_session)
    assert resolved == []
    assert unresolved == []


@pytest.mark.asyncio
async def test_empty_string_candidate_is_unresolved(db_session: AsyncSession) -> None:
    resolved, unresolved = await resolve_backlink_candidates(["", "   "], db_session)
    assert resolved == []
    # Empty strings are dropped, not passed through as unresolved
    assert unresolved == []
