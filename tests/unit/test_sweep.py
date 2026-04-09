"""Tests for the incremental wikilink resolution sweep job (B3 backfill)."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind._datetime import utcnow_naive
from wikimind.jobs.sweep import _sweep_single_article
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
async def test_resolves_bracket_and_creates_backlink(db_session: AsyncSession, tmp_path: Path) -> None:
    """An article with [[Existing Title]] -> file rewritten + Backlink row created."""
    target = await _make_article(db_session, "Machine Learning", str(tmp_path / "ml.md"))

    md_path = tmp_path / "source.md"
    md_path.write_text("Some text about [[Machine Learning]] in the body.\n")
    source = await _make_article(db_session, "AI Overview", str(md_path), slug="ai-overview")

    changed = await _sweep_single_article(source, db_session)

    assert changed is True
    content = md_path.read_text()
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
    md_path = tmp_path / "clean.md"
    original = "This article has no brackets at all.\n"
    md_path.write_text(original)
    article = await _make_article(db_session, "Clean Article", str(md_path))

    changed = await _sweep_single_article(article, db_session)

    assert changed is False
    assert md_path.read_text() == original


@pytest.mark.asyncio
async def test_unknown_bracket_stays(db_session: AsyncSession, tmp_path: Path) -> None:
    """An article with [[Unknown Title]] -> bracket stays, no Backlink row."""
    md_path = tmp_path / "unknown.md"
    md_path.write_text("See also [[Nonexistent Topic]] for more.\n")
    article = await _make_article(db_session, "Some Article", str(md_path))

    changed = await _sweep_single_article(article, db_session)

    assert changed is False
    content = md_path.read_text()
    assert "[[Nonexistent Topic]]" in content

    result = await db_session.execute(select(Backlink).where(Backlink.source_article_id == article.id))
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_already_resolved_link_not_rewritten(db_session: AsyncSession, tmp_path: Path) -> None:
    """An article with [Title](/wiki/{id}) from a fresh compile -> NOT rewritten."""
    target = await _make_article(db_session, "Machine Learning", str(tmp_path / "ml.md"))
    md_path = tmp_path / "resolved.md"
    original = f"Read about [Machine Learning](/wiki/{target.id}) here.\n"
    md_path.write_text(original)
    article = await _make_article(db_session, "Resolved Article", str(md_path))

    changed = await _sweep_single_article(article, db_session)

    assert changed is False
    assert md_path.read_text() == original


@pytest.mark.asyncio
async def test_idempotent_rerun_after_sweep(db_session: AsyncSession, tmp_path: Path) -> None:
    """Re-running the sweep after a previous sweep -> no changes."""
    await _make_article(db_session, "Machine Learning", str(tmp_path / "ml.md"))
    md_path = tmp_path / "source.md"
    md_path.write_text("Text about [[Machine Learning]] here.\n")
    source = await _make_article(db_session, "AI Overview", str(md_path), slug="ai-overview")

    # First run: should make changes
    changed1 = await _sweep_single_article(source, db_session)
    assert changed1 is True

    # Second run: no changes (bracket already resolved, Backlink already exists)
    changed2 = await _sweep_single_article(source, db_session)
    assert changed2 is False


@pytest.mark.asyncio
async def test_multiple_brackets_partial_resolution(db_session: AsyncSession, tmp_path: Path) -> None:
    """Multiple brackets: some resolve, some stay. Only resolved ones are replaced."""
    target = await _make_article(db_session, "React", str(tmp_path / "react.md"))
    md_path = tmp_path / "multi.md"
    md_path.write_text("Uses [[React]] and [[Unknown Framework]] for UI.\n")
    source = await _make_article(db_session, "Frontend Guide", str(md_path))

    changed = await _sweep_single_article(source, db_session)

    assert changed is True
    content = md_path.read_text()
    assert f"[React](/wiki/{target.id})" in content
    assert "[[Unknown Framework]]" in content


@pytest.mark.asyncio
async def test_self_link_excluded(db_session: AsyncSession, tmp_path: Path) -> None:
    """A bracket matching the article's own title is not resolved (no self-link)."""
    md_path = tmp_path / "self.md"
    md_path.write_text("This article about [[Self Referencing]] itself.\n")
    article = await _make_article(db_session, "Self Referencing", str(md_path), slug="self-referencing")

    changed = await _sweep_single_article(article, db_session)

    assert changed is False
    content = md_path.read_text()
    assert "[[Self Referencing]]" in content


@pytest.mark.asyncio
async def test_missing_file_handled_gracefully(db_session: AsyncSession, tmp_path: Path) -> None:
    """Article whose file_path doesn't exist -> skip gracefully."""
    article = await _make_article(db_session, "Missing File", str(tmp_path / "does-not-exist.md"))

    changed = await _sweep_single_article(article, db_session)
    assert changed is False
