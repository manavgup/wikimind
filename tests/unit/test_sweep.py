"""Tests for the incremental wikilink resolution sweep job (B3 backfill)."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlmodel import select

from tests.conftest import TEST_USER_ID
from wikimind._datetime import utcnow_naive
from wikimind.config import get_settings
from wikimind.jobs.sweep import _sweep_single_article
from wikimind.models import Article, Backlink, ConfidenceLevel

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession


def _wiki_root(tmp_path: Path) -> Path:
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
async def test_resolves_bracket_and_creates_backlink(db_session: AsyncSession, tmp_path: Path) -> None:
    """An article with [[Existing Title]] -> file rewritten + Backlink row created."""
    wiki = _wiki_root(tmp_path)
    target = await _make_article(db_session, "Machine Learning", "ml.md")

    (wiki / "source.md").write_text("Some text about [[Machine Learning]] in the body.\n")
    source = await _make_article(db_session, "AI Overview", "source.md", slug="ai-overview")

    changed = await _sweep_single_article(source.id, db_session)

    assert changed is True
    content = (wiki / "source.md").read_text()
    assert f"[Machine Learning](/wiki/{target.id})" in content
    assert "[[Machine Learning]]" not in content

    result = await db_session.execute(
        select(Backlink).where(
            Backlink.source_article_id == source.id,
            Backlink.target_article_id == target.id,
        )
    )
    bl = result.scalar_one_or_none()
    assert bl is not None


@pytest.mark.asyncio
async def test_no_brackets_no_write(db_session: AsyncSession, tmp_path: Path) -> None:
    """An article with no [[brackets]] -> NOT rewritten (idempotency)."""
    wiki = _wiki_root(tmp_path)
    original = "This article has no brackets at all.\n"
    (wiki / "clean.md").write_text(original)
    article = await _make_article(db_session, "Clean Article", "clean.md")

    changed = await _sweep_single_article(article.id, db_session)

    assert changed is False
    assert (wiki / "clean.md").read_text() == original


@pytest.mark.asyncio
async def test_unknown_bracket_stays(db_session: AsyncSession, tmp_path: Path) -> None:
    """An article with [[Unknown Title]] -> bracket stays, no Backlink row."""
    wiki = _wiki_root(tmp_path)
    (wiki / "unknown.md").write_text("See also [[Nonexistent Topic]] for more.\n")
    article = await _make_article(db_session, "Some Article", "unknown.md")

    changed = await _sweep_single_article(article.id, db_session)

    assert changed is False
    content = (wiki / "unknown.md").read_text()
    assert "[[Nonexistent Topic]]" in content

    result = await db_session.execute(select(Backlink).where(Backlink.source_article_id == article.id))
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_already_resolved_link_not_rewritten(db_session: AsyncSession, tmp_path: Path) -> None:
    """An article with [Title](/wiki/{id}) from a fresh compile -> NOT rewritten."""
    wiki = _wiki_root(tmp_path)
    target = await _make_article(db_session, "Machine Learning", "ml.md")
    original = f"Read about [Machine Learning](/wiki/{target.id}) here.\n"
    (wiki / "resolved.md").write_text(original)
    article = await _make_article(db_session, "Resolved Article", "resolved.md")

    changed = await _sweep_single_article(article.id, db_session)

    assert changed is False
    assert (wiki / "resolved.md").read_text() == original


@pytest.mark.asyncio
async def test_idempotent_rerun_after_sweep(db_session: AsyncSession, tmp_path: Path) -> None:
    """Re-running the sweep after a previous sweep -> no changes."""
    wiki = _wiki_root(tmp_path)
    await _make_article(db_session, "Machine Learning", "ml.md")
    (wiki / "source.md").write_text("Text about [[Machine Learning]] here.\n")
    source = await _make_article(db_session, "AI Overview", "source.md", slug="ai-overview")

    # First run: should make changes
    changed1 = await _sweep_single_article(source.id, db_session)
    assert changed1 is True

    # Second run: no changes (bracket already resolved, Backlink already exists)
    changed2 = await _sweep_single_article(source.id, db_session)
    assert changed2 is False


@pytest.mark.asyncio
async def test_multiple_brackets_partial_resolution(db_session: AsyncSession, tmp_path: Path) -> None:
    """Multiple brackets: some resolve, some stay. Only resolved ones are replaced."""
    wiki = _wiki_root(tmp_path)
    target = await _make_article(db_session, "React", "react.md")
    (wiki / "multi.md").write_text("Uses [[React]] and [[Unknown Framework]] for UI.\n")
    source = await _make_article(db_session, "Frontend Guide", "multi.md")

    changed = await _sweep_single_article(source.id, db_session)

    assert changed is True
    content = (wiki / "multi.md").read_text()
    assert f"[React](/wiki/{target.id})" in content
    assert "[[Unknown Framework]]" in content


@pytest.mark.asyncio
async def test_self_link_excluded(db_session: AsyncSession, tmp_path: Path) -> None:
    """A bracket matching the article's own title is not resolved (no self-link)."""
    wiki = _wiki_root(tmp_path)
    (wiki / "self.md").write_text("This article about [[Self Referencing]] itself.\n")
    article = await _make_article(db_session, "Self Referencing", "self.md", slug="self-referencing")

    changed = await _sweep_single_article(article.id, db_session)

    assert changed is False
    content = (wiki / "self.md").read_text()
    assert "[[Self Referencing]]" in content


@pytest.mark.asyncio
async def test_missing_file_handled_gracefully(db_session: AsyncSession, tmp_path: Path) -> None:
    """Article whose file_path doesn't exist -> skip gracefully."""
    _wiki_root(tmp_path)
    article = await _make_article(db_session, "Missing File", "does-not-exist.md")

    changed = await _sweep_single_article(article.id, db_session)
    assert changed is False
