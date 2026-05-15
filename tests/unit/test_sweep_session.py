"""Tests for sweep session isolation fix (issue #163).

Verifies that:
1. Sweep creates backlinks for articles with unresolved wikilinks.
2. Sweep handles pre-existing (duplicate) backlinks without identity-map
   conflicts or IntegrityError.
3. sweep_wikilinks(user_id="test-user") uses isolated per-article sessions via
   get_session_factory().
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from sqlmodel import select

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.conftest import TEST_USER_ID
from wikimind._datetime import utcnow_naive
from wikimind.config import get_settings
from wikimind.jobs.sweep import _sweep_single_article, sweep_wikilinks
from wikimind.models import Article, Backlink, ConfidenceLevel


def _wiki_root() -> Path:
    """Return the wiki storage root for TEST_USER_ID and ensure it exists."""
    settings = get_settings()
    root = Path(settings.data_dir) / "wiki" / TEST_USER_ID
    root.mkdir(parents=True, exist_ok=True)
    return root


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
        user_id=TEST_USER_ID,
    )
    session.add(article)
    await session.commit()
    await session.refresh(article)
    return article


@pytest.mark.asyncio
async def test_sweep_creates_backlinks(db_session: AsyncSession, tmp_path: Path) -> None:
    """Sweep resolves [[brackets]] and creates corresponding Backlink rows."""
    wiki = _wiki_root()
    target = await _make_article(db_session, "Quantum Computing", "qc.md")

    (wiki / "source.md").write_text("Research on [[Quantum Computing]] is advancing.\n")
    source = await _make_article(db_session, "Physics Overview", "source.md")

    changed = await _sweep_single_article(source.id, db_session)

    assert changed is True
    content = (wiki / "source.md").read_text()
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
async def test_sweep_handles_duplicate_backlinks(session_factory, tmp_path: Path) -> None:
    """When a Backlink already exists, sweep uses merge() without SAWarning or error.

    Uses separate sessions (as production code does): one for setup, one
    for the sweep. This mirrors the real scenario where the compiler
    created the Backlink in a prior session.
    """
    wiki = _wiki_root()
    factory = session_factory

    # Setup: create articles and a pre-existing backlink.
    async with factory() as setup_session:
        target = await _make_article(setup_session, "Machine Learning", "ml.md")

        (wiki / "source.md").write_text("Exploring [[Machine Learning]] techniques.\n")
        source = await _make_article(setup_session, "AI Guide", "source.md")

        # Pre-create the backlink (simulates prior compilation)
        existing_bl = Backlink(
            source_article_id=source.id,
            target_article_id=target.id,
            context="pre-existing",
            user_id=TEST_USER_ID,
        )
        setup_session.add(existing_bl)
        await setup_session.commit()
        source_id = source.id
        target_id = target.id

    # Sweep in a fresh session — no SAWarning or IntegrityError should occur.
    # The function now re-loads the article internally, so we just pass the ID.
    async with factory() as sweep_session:
        changed = await _sweep_single_article(source_id, sweep_session)

    assert changed is True
    content = (wiki / "source.md").read_text()
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
    session_factory,
    tmp_path: Path,
) -> None:
    """sweep_wikilinks(user_id="test-user") creates a separate session per article via get_session_factory().

    We mock get_session_factory to return a counting wrapper, then verify
    multiple sessions are created (one for the job + one per article).
    """
    wiki = _wiki_root()
    factory = session_factory

    # Pre-populate: one article with an unresolved bracket, one target
    async with factory() as setup_session:
        target = Article(
            id=str(uuid.uuid4()),
            slug="deep-learning",
            title="Deep Learning",
            file_path="dl.md",
            confidence=ConfidenceLevel.SOURCED,
            created_at=utcnow_naive(),
            user_id=TEST_USER_ID,
        )
        (wiki / "intro.md").write_text("Introduction to [[Deep Learning]] methods.\n")
        source = Article(
            id=str(uuid.uuid4()),
            slug="intro-ai",
            title="Intro to AI",
            file_path="intro.md",
            confidence=ConfidenceLevel.SOURCED,
            created_at=utcnow_naive(),
            user_id=TEST_USER_ID,
        )
        setup_session.add_all([target, source])
        await setup_session.commit()
        source_id = source.id
        target_id = target.id

    counting_factory = _CountingSessionFactory(factory)

    with patch("wikimind.jobs.sweep.get_session_factory", return_value=counting_factory):
        await sweep_wikilinks(None, user_id=TEST_USER_ID)

    # Should have at least 5 calls: 1 job session + 1 cleanup session
    # + 1 list session + 2 per-article sessions. The key assertion is > 1.
    assert counting_factory.call_count >= 5, (
        f"Expected at least 5 session factory calls, got {counting_factory.call_count}"
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
