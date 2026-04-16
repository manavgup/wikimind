"""Tests for sweep session isolation fix (issue #163).

Verifies that:
1. Sweep creates backlinks for articles with unresolved wikilinks.
2. Sweep handles pre-existing (duplicate) backlinks without identity-map
   conflicts or IntegrityError.
3. sweep_wikilinks() uses isolated per-article sessions via
   get_session_factory().
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlmodel import select

from wikimind._datetime import utcnow_naive
from wikimind.jobs.sweep import _sweep_single_article, sweep_wikilinks
from wikimind.models import Article, Backlink, ConfidenceLevel


async def _make_article(
    session: AsyncSession,
    title: str,
    file_path: str,
    slug: str | None = None,
) -> Article:
    """Create and persist a test article."""
    article = Article(
        id=str(uuid.uuid4()),
        slug=slug or title.lower().replace(" ", "-"),
        title=title,
        file_path=file_path,
        confidence=ConfidenceLevel.SOURCED,
        created_at=utcnow_naive(),
    )
    session.add(article)
    await session.commit()
    await session.refresh(article)
    return article


@pytest.mark.asyncio
async def test_sweep_creates_backlinks(db_session: AsyncSession, tmp_path: Path) -> None:
    """Sweep resolves [[brackets]] and creates corresponding Backlink rows."""
    target = await _make_article(db_session, "Quantum Computing", str(tmp_path / "qc.md"))

    md_path = tmp_path / "source.md"
    md_path.write_text("Research on [[Quantum Computing]] is advancing.\n")
    source = await _make_article(db_session, "Physics Overview", str(md_path))

    changed = await _sweep_single_article(source, db_session)

    assert changed is True
    content = md_path.read_text()
    assert f"[Quantum Computing](/wiki/{target.id})" in content

    result = await db_session.execute(
        select(Backlink).where(
            Backlink.source_article_id == source.id,
            Backlink.target_article_id == target.id,
        )
    )
    bl = result.scalar_one_or_none()
    assert bl is not None
    assert bl.context == "Quantum Computing"


@pytest.mark.asyncio
async def test_sweep_handles_duplicate_backlinks(async_engine: AsyncEngine, tmp_path: Path) -> None:
    """When a Backlink already exists, sweep uses merge() without SAWarning or error.

    Uses separate sessions (as production code does): one for setup, one
    for the sweep. This mirrors the real scenario where the compiler
    created the Backlink in a prior session.
    """
    factory = async_sessionmaker(async_engine, expire_on_commit=False)

    # Setup: create articles and a pre-existing backlink.
    async with factory() as setup_session:
        target = await _make_article(setup_session, "Machine Learning", str(tmp_path / "ml.md"))

        md_path = tmp_path / "source.md"
        md_path.write_text("Exploring [[Machine Learning]] techniques.\n")
        source = await _make_article(setup_session, "AI Guide", str(md_path))

        # Pre-create the backlink (simulates prior compilation)
        existing_bl = Backlink(
            source_article_id=source.id,
            target_article_id=target.id,
            context="pre-existing",
        )
        setup_session.add(existing_bl)
        await setup_session.commit()
        source_id = source.id
        target_id = target.id

    # Sweep in a fresh session — no SAWarning or IntegrityError should occur.
    async with factory() as sweep_session:
        # Re-load the article in this session's identity map.
        result = await sweep_session.execute(select(Article).where(Article.id == source_id))
        source_reloaded = result.scalar_one()

        changed = await _sweep_single_article(source_reloaded, sweep_session)

    assert changed is True
    content = md_path.read_text()
    assert f"[Machine Learning](/wiki/{target_id})" in content

    # Verify exactly one backlink row exists (not two).
    async with factory() as verify_session:
        result = await verify_session.execute(
            select(Backlink).where(
                Backlink.source_article_id == source_id,
                Backlink.target_article_id == target_id,
            )
        )
        links = list(result.scalars().all())
        assert len(links) == 1


class _CountingSessionFactory:
    """Wraps an async_sessionmaker to count how many sessions are created."""

    def __init__(self, real_factory: async_sessionmaker):
        self._real = real_factory
        self.call_count = 0

    def __call__(self):
        self.call_count += 1
        return self._real()


@pytest.mark.asyncio
async def test_sweep_wikilinks_uses_isolated_sessions(
    async_engine: AsyncEngine,
    tmp_path: Path,
) -> None:
    """sweep_wikilinks() creates a separate session per article via get_session_factory().

    We mock get_session_factory to return a counting wrapper, then verify
    multiple sessions are created (one for the job + one per article).
    """
    factory = async_sessionmaker(async_engine, expire_on_commit=False)

    # Pre-populate: one article with an unresolved bracket, one target
    async with factory() as setup_session:
        target = Article(
            id=str(uuid.uuid4()),
            slug="deep-learning",
            title="Deep Learning",
            file_path=str(tmp_path / "dl.md"),
            confidence=ConfidenceLevel.SOURCED,
            created_at=utcnow_naive(),
        )
        md_path = tmp_path / "intro.md"
        md_path.write_text("Introduction to [[Deep Learning]] methods.\n")
        source = Article(
            id=str(uuid.uuid4()),
            slug="intro-ai",
            title="Intro to AI",
            file_path=str(md_path),
            confidence=ConfidenceLevel.SOURCED,
            created_at=utcnow_naive(),
        )
        setup_session.add_all([target, source])
        await setup_session.commit()
        source_id = source.id
        target_id = target.id

    counting_factory = _CountingSessionFactory(factory)

    with patch("wikimind.jobs.sweep.get_session_factory", return_value=counting_factory):
        await sweep_wikilinks(ctx=None)

    # Should have at least 3 calls: 1 job session + 2 per article
    # (one per article in the loop). The key assertion is > 1.
    assert counting_factory.call_count >= 3, (
        f"Expected at least 3 session factory calls (1 job + 2 articles), got {counting_factory.call_count}"
    )

    # Verify the backlink was actually created.
    async with factory() as verify_session:
        result = await verify_session.execute(
            select(Backlink).where(
                Backlink.source_article_id == source_id,
                Backlink.target_article_id == target_id,
            )
        )
        bl = result.scalar_one_or_none()
        assert bl is not None
