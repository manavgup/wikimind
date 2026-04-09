"""Integration test for the incremental wikilink resolution sweep (B3 backfill).

Scenario:
    1. Seed articles A and B where A's .md has [[B's Title]] as unresolved.
    2. Run the sweep. Assert B's bracket resolved + Backlink row exists.
    3. Add article C whose title matches another bracket in A's .md.
    4. Re-run the sweep. Assert the second bracket is now also resolved.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlmodel import select

from wikimind._datetime import utcnow_naive
from wikimind.jobs.sweep import sweep_wikilinks
from wikimind.models import Article, Backlink, ConfidenceLevel, Job, JobStatus, JobType


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
async def test_sweep_resolves_incrementally(db_session: AsyncSession, async_engine, tmp_path: Path) -> None:
    """Full sweep resolves brackets as target articles appear over time."""
    # --- Setup: article B exists, article C does not yet exist ---
    article_b = await _make_article(db_session, "Machine Learning", str(tmp_path / "ml.md"), slug="machine-learning")

    # Article A has brackets for both B and C (C does not exist yet)
    a_md = tmp_path / "overview.md"
    a_md.write_text(
        "# AI Overview\n\n"
        "See [[Machine Learning]] for the basics.\n\n"
        "Also check [[Deep Learning]] for advanced topics.\n"
    )
    article_a = await _make_article(db_session, "AI Overview", str(a_md), slug="ai-overview")

    # Build a real session factory backed by the same in-memory engine
    factory = async_sessionmaker(async_engine, expire_on_commit=False)

    # --- Phase 1: run sweep --- only Machine Learning should resolve ---
    with patch("wikimind.jobs.sweep.get_session_factory", return_value=factory):
        await sweep_wikilinks({})

    # Assert: Machine Learning bracket resolved
    content_after_phase1 = a_md.read_text()
    assert f"[Machine Learning](/wiki/{article_b.id})" in content_after_phase1
    assert "[[Machine Learning]]" not in content_after_phase1

    # Assert: Deep Learning bracket still unresolved
    assert "[[Deep Learning]]" in content_after_phase1

    # Assert: Backlink A -> B exists (use a fresh session from factory to see committed data)
    async with factory() as check_session:
        bl_result = await check_session.execute(
            select(Backlink).where(
                Backlink.source_article_id == article_a.id,
                Backlink.target_article_id == article_b.id,
            )
        )
        assert bl_result.scalar_one_or_none() is not None

        # Assert: Job row was created
        job_result = await check_session.execute(select(Job).where(Job.job_type == JobType.SWEEP_WIKILINKS))
        jobs = list(job_result.scalars().all())
        assert len(jobs) >= 1
        assert jobs[0].status == JobStatus.COMPLETE

    # --- Phase 2: add article C, re-run sweep ---
    async with factory() as seed_session:
        article_c = Article(
            id=str(uuid.uuid4()),
            slug="deep-learning",
            title="Deep Learning",
            file_path=str(tmp_path / "dl.md"),
            confidence=ConfidenceLevel.SOURCED,
            created_at=utcnow_naive(),
        )
        seed_session.add(article_c)
        await seed_session.commit()
        await seed_session.refresh(article_c)

    with patch("wikimind.jobs.sweep.get_session_factory", return_value=factory):
        await sweep_wikilinks({})

    # Assert: Deep Learning bracket now resolved
    content_after_phase2 = a_md.read_text()
    assert f"[Deep Learning](/wiki/{article_c.id})" in content_after_phase2
    assert "[[Deep Learning]]" not in content_after_phase2

    # Assert: Machine Learning link still intact
    assert f"[Machine Learning](/wiki/{article_b.id})" in content_after_phase2

    # Assert: Backlink A -> C exists
    async with factory() as check_session2:
        bl_result2 = await check_session2.execute(
            select(Backlink).where(
                Backlink.source_article_id == article_a.id,
                Backlink.target_article_id == article_c.id,
            )
        )
        assert bl_result2.scalar_one_or_none() is not None

    # --- Phase 3: re-run again --- should be a complete no-op ---
    with patch("wikimind.jobs.sweep.get_session_factory", return_value=factory):
        await sweep_wikilinks({})

    # Content unchanged
    assert a_md.read_text() == content_after_phase2
