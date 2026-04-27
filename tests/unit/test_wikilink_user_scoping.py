"""Tests for user_id scoping in wikilink resolver and backlink enforcer.

Verifies that:
- resolve_backlink_candidates() only returns articles for the given user_id
- The backlink enforcer creates inverse backlinks with correct user_id
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from sqlmodel import select

from wikimind.engine.backlink_enforcer import ensure_bidirectional
from wikimind.engine.wikilink_resolver import resolve_backlink_candidates
from wikimind.models import Article, Backlink, ConfidenceLevel, RelationType

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def _make_article(
    session: AsyncSession,
    title: str,
    user_id: str | None = None,
    slug: str | None = None,
) -> Article:
    article = Article(
        id=str(uuid.uuid4()),
        slug=slug or title.lower().replace(" ", "-"),
        title=title,
        file_path=f"/tmp/{slug or title}.md",
        confidence=ConfidenceLevel.SOURCED,
        user_id=user_id,
    )
    session.add(article)
    await session.commit()
    await session.refresh(article)
    return article


# ---------------------------------------------------------------------------
# resolve_backlink_candidates — user_id scoping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolver_filters_by_user_id(db_session: AsyncSession) -> None:
    """Only articles belonging to the given user_id are resolved."""
    user_a = "user-a"
    user_b = "user-b"
    art_a = await _make_article(db_session, "Machine Learning", user_id=user_a)
    await _make_article(db_session, "Machine Learning", user_id=user_b, slug="ml-b")

    resolved, unresolved = await resolve_backlink_candidates(
        ["Machine Learning"],
        db_session,
        user_id=user_a,
    )
    assert len(resolved) == 1
    assert resolved[0].target_id == art_a.id
    assert unresolved == []


@pytest.mark.asyncio
async def test_resolver_other_user_article_is_unresolved(
    db_session: AsyncSession,
) -> None:
    """An article from a different user is treated as unresolved."""
    await _make_article(db_session, "Quantum Computing", user_id="user-b")

    resolved, unresolved = await resolve_backlink_candidates(
        ["Quantum Computing"],
        db_session,
        user_id="user-a",
    )
    assert resolved == []
    assert unresolved == ["Quantum Computing"]


@pytest.mark.asyncio
async def test_resolver_no_user_id_returns_all(db_session: AsyncSession) -> None:
    """When user_id is None, all articles are considered (backward compat)."""
    art_a = await _make_article(db_session, "React", user_id="user-a")
    art_b = await _make_article(db_session, "Vue", user_id="user-b")

    resolved, unresolved = await resolve_backlink_candidates(
        ["React", "Vue"],
        db_session,
    )
    assert len(resolved) == 2
    resolved_ids = {r.target_id for r in resolved}
    assert art_a.id in resolved_ids
    assert art_b.id in resolved_ids
    assert unresolved == []


@pytest.mark.asyncio
async def test_resolver_user_id_with_exclude(db_session: AsyncSession) -> None:
    """user_id filtering and exclude_article_id work together."""
    user = "user-x"
    self_art = await _make_article(db_session, "Self", user_id=user)
    other_art = await _make_article(db_session, "Other", user_id=user)

    resolved, unresolved = await resolve_backlink_candidates(
        ["Self", "Other"],
        db_session,
        exclude_article_id=self_art.id,
        user_id=user,
    )
    assert len(resolved) == 1
    assert resolved[0].target_id == other_art.id
    assert unresolved == ["Self"]


# ---------------------------------------------------------------------------
# ensure_bidirectional — user_id propagation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_bidirectional_propagates_user_id(
    db_session: AsyncSession,
) -> None:
    """Inverse backlink created by ensure_bidirectional carries the source user_id."""
    user = "user-abc"
    art_a = await _make_article(db_session, "Art A", user_id=user, slug="art-a")
    art_b = await _make_article(db_session, "Art B", user_id=user, slug="art-b")

    bl = Backlink(
        source_article_id=art_a.id,
        target_article_id=art_b.id,
        relation_type=RelationType.CONTRADICTS,
        context="claim conflict",
        user_id=user,
    )
    db_session.add(bl)
    await db_session.commit()

    created = await ensure_bidirectional(bl, db_session)
    await db_session.commit()

    assert created is True

    result = await db_session.execute(
        select(Backlink).where(
            Backlink.source_article_id == art_b.id,
            Backlink.target_article_id == art_a.id,
        )
    )
    inverse = result.scalars().first()
    assert inverse is not None
    assert inverse.user_id == user


@pytest.mark.asyncio
async def test_ensure_bidirectional_null_user_id(
    db_session: AsyncSession,
) -> None:
    """Inverse backlink with null user_id is preserved (legacy compat)."""
    art_a = await _make_article(db_session, "Art A", slug="art-a-legacy")
    art_b = await _make_article(db_session, "Art B", slug="art-b-legacy")

    bl = Backlink(
        source_article_id=art_a.id,
        target_article_id=art_b.id,
        relation_type=RelationType.RELATED_TO,
        context="related",
        user_id=None,
    )
    db_session.add(bl)
    await db_session.commit()

    created = await ensure_bidirectional(bl, db_session)
    await db_session.commit()

    assert created is True

    result = await db_session.execute(
        select(Backlink).where(
            Backlink.source_article_id == art_b.id,
            Backlink.target_article_id == art_a.id,
        )
    )
    inverse = result.scalars().first()
    assert inverse is not None
    assert inverse.user_id is None
