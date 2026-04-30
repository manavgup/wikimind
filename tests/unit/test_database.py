"""Tests for database session lifecycle — commit on success, rollback on error."""

from __future__ import annotations

import contextlib
import json
import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select

from wikimind.database import (
    _cleanup_orphan_concept_rows,
    _repair_json_array,
    _repair_malformed_json_arrays,
    get_session,
)
from wikimind.models import Article, Backlink, ConfidenceLevel, PageType, Source, SourceType

if TYPE_CHECKING:
    from pathlib import Path
from tests.conftest import TEST_USER_ID


@pytest.fixture
def session_factory(async_engine):
    """Override get_session to use the in-memory engine."""
    return async_sessionmaker(async_engine, expire_on_commit=False)


@pytest.fixture
def _patch_session_factory(session_factory, monkeypatch):
    """Monkey-patch get_session_factory to use the test session factory."""
    monkeypatch.setattr("wikimind.database.get_session_factory", lambda: session_factory)


@pytest.mark.usefixtures("_patch_session_factory")
class TestSessionLifecycle:
    async def test_commit_on_success(self, session_factory):
        """Session auto-commits when the block exits normally."""
        gen = get_session()
        session = await gen.__anext__()

        source = Source(source_type=SourceType.URL, source_url="https://example.com", user_id=TEST_USER_ID)
        session.add(source)
        source_id = source.id

        # Close the generator — triggers commit
        with contextlib.suppress(StopAsyncIteration):
            await gen.__anext__()

        # Verify the row was persisted
        async with session_factory() as verify_session:
            result = await verify_session.execute(select(Source).where(Source.id == source_id))
            persisted = result.scalar_one_or_none()
            assert persisted is not None
            assert persisted.source_url == "https://example.com"

    async def test_rollback_on_error(self, session_factory):
        """Session rolls back when an exception is raised."""
        gen = get_session()
        session = await gen.__anext__()

        source = Source(source_type=SourceType.URL, source_url="https://rollback.example.com", user_id=TEST_USER_ID)
        session.add(source)
        source_id = source.id

        # Simulate an error — triggers rollback
        with pytest.raises(RuntimeError, match="simulated"):
            await gen.athrow(RuntimeError("simulated error"))

        # Verify the row was NOT persisted
        async with session_factory() as verify_session:
            result = await verify_session.execute(select(Source).where(Source.id == source_id))
            persisted = result.scalar_one_or_none()
            assert persisted is None


# ---------------------------------------------------------------------------
# _repair_json_array unit tests (issue #112)
# ---------------------------------------------------------------------------


class TestRepairJsonArray:
    def test_valid_json_returns_none(self):
        """Already-valid JSON is left untouched."""
        assert _repair_json_array('["a", "b", "c"]') is None

    def test_malformed_missing_commas(self):
        """The old bug: ["a"b"c"] -> should repair to ["a","b","c"]."""
        repaired = _repair_json_array('["data deduplication"data management"storage optimization"]')
        assert repaired is not None
        parsed = json.loads(repaired)
        assert parsed == ["data deduplication", "data management", "storage optimization"]

    def test_single_item_valid(self):
        """Single-item arrays are already valid."""
        assert _repair_json_array('["only-one"]') is None

    def test_empty_array_valid(self):
        """Empty array is valid JSON."""
        assert _repair_json_array("[]") is None


# ---------------------------------------------------------------------------
# _repair_malformed_json_arrays migration tests (issue #112)
# ---------------------------------------------------------------------------


class TestRepairMalformedJsonArraysMigration:
    async def test_repairs_malformed_concept_ids(self, async_engine, db_session):
        """Migration fixes malformed concept_ids in existing rows."""
        article_id = str(uuid.uuid4())
        malformed = '["data deduplication"data management"storage optimization"]'
        article = Article(
            id=article_id,
            slug="test-malformed",
            title="Test",
            file_path="/tmp/test.md",
            confidence=ConfidenceLevel.SOURCED,
            concept_ids=malformed,
            source_ids='["src-1"]',
            user_id=TEST_USER_ID,
        )
        db_session.add(article)
        await db_session.commit()

        await _repair_malformed_json_arrays(async_engine)

        db_session.expire_all()
        result = await db_session.execute(select(Article).where(Article.id == article_id))
        fixed = result.scalar_one()
        parsed = json.loads(fixed.concept_ids)
        assert parsed == ["data deduplication", "data management", "storage optimization"]

    async def test_leaves_valid_json_unchanged(self, async_engine, db_session):
        """Migration does not alter rows with already-valid JSON."""
        article_id = str(uuid.uuid4())
        valid_concepts = '["alpha", "beta"]'
        valid_sources = '["src-1"]'
        article = Article(
            id=article_id,
            slug="test-valid",
            title="Test Valid",
            file_path="/tmp/test-valid.md",
            confidence=ConfidenceLevel.SOURCED,
            concept_ids=valid_concepts,
            source_ids=valid_sources,
            user_id=TEST_USER_ID,
        )
        db_session.add(article)
        await db_session.commit()

        await _repair_malformed_json_arrays(async_engine)

        db_session.expire_all()
        result = await db_session.execute(select(Article).where(Article.id == article_id))
        fixed = result.scalar_one()
        assert fixed.concept_ids == valid_concepts
        assert fixed.source_ids == valid_sources

    async def test_repairs_malformed_source_ids(self, async_engine, db_session):
        """Migration also repairs malformed source_ids."""
        article_id = str(uuid.uuid4())
        malformed_sources = '["id1"id2"id3"]'
        article = Article(
            id=article_id,
            slug="test-sources",
            title="Test Sources",
            file_path="/tmp/test-sources.md",
            confidence=ConfidenceLevel.SOURCED,
            concept_ids='["valid"]',
            source_ids=malformed_sources,
            user_id=TEST_USER_ID,
        )
        db_session.add(article)
        await db_session.commit()

        await _repair_malformed_json_arrays(async_engine)

        db_session.expire_all()
        result = await db_session.execute(select(Article).where(Article.id == article_id))
        fixed = result.scalar_one()
        parsed = json.loads(fixed.source_ids)
        assert parsed == ["id1", "id2", "id3"]


# ---------------------------------------------------------------------------
# _cleanup_orphan_concept_rows migration tests (issue #169)
# ---------------------------------------------------------------------------


class TestCleanupOrphanConceptRows:
    async def test_deletes_concept_article_with_missing_file(self, db_session, tmp_path: Path):
        """Concept article whose .md file doesn't exist on disk is deleted."""
        article = Article(
            id=str(uuid.uuid4()),
            slug="concept-stale-topic",
            title="Stale Topic",
            file_path=str(tmp_path / "concept-stale-topic" / "concept-stale-topic.md"),
            page_type=PageType.CONCEPT,
            user_id=TEST_USER_ID,
        )
        db_session.add(article)
        await db_session.commit()

        await _cleanup_orphan_concept_rows(db_session)

        result = await db_session.execute(select(Article).where(Article.id == article.id))
        assert result.scalar_one_or_none() is None

    async def test_keeps_concept_article_with_existing_file(self, db_session, tmp_path: Path):
        """Concept article whose .md file exists on disk is preserved."""
        md_dir = tmp_path / "concept-active-topic"
        md_dir.mkdir(parents=True)
        md_file = md_dir / "concept-active-topic.md"
        md_file.write_text("# Active Topic\n")

        article = Article(
            id=str(uuid.uuid4()),
            slug="concept-active-topic",
            title="Active Topic",
            file_path=str(md_file),
            page_type=PageType.CONCEPT,
            user_id=TEST_USER_ID,
        )
        db_session.add(article)
        await db_session.commit()

        await _cleanup_orphan_concept_rows(db_session)

        result = await db_session.execute(select(Article).where(Article.id == article.id))
        assert result.scalar_one_or_none() is not None

    async def test_leaves_source_articles_untouched(self, db_session, tmp_path: Path):
        """Source articles with missing files are NOT cleaned up (only concepts)."""
        article = Article(
            id=str(uuid.uuid4()),
            slug="some-source",
            title="Some Source",
            file_path=str(tmp_path / "missing-source.md"),
            page_type=PageType.SOURCE,
            user_id=TEST_USER_ID,
        )
        db_session.add(article)
        await db_session.commit()

        await _cleanup_orphan_concept_rows(db_session)

        result = await db_session.execute(select(Article).where(Article.id == article.id))
        assert result.scalar_one_or_none() is not None

    async def test_deletes_associated_backlinks(self, db_session, tmp_path: Path):
        """Backlinks referencing an orphaned concept article are also deleted."""
        orphan = Article(
            id=str(uuid.uuid4()),
            slug="concept-orphan",
            title="Orphan Concept",
            file_path=str(tmp_path / "concept-orphan" / "concept-orphan.md"),
            page_type=PageType.CONCEPT,
            user_id=TEST_USER_ID,
        )
        # A surviving article that links to the orphan
        md_file = tmp_path / "surviving.md"
        md_file.write_text("# Surviving\n")
        survivor = Article(
            id=str(uuid.uuid4()),
            slug="surviving-article",
            title="Surviving Article",
            file_path=str(md_file),
            page_type=PageType.SOURCE,
            user_id=TEST_USER_ID,
        )
        db_session.add_all([orphan, survivor])
        await db_session.flush()

        backlink = Backlink(
            source_article_id=survivor.id,
            target_article_id=orphan.id,
            context="link to orphan",
            user_id=TEST_USER_ID,
        )
        db_session.add(backlink)
        await db_session.commit()

        await _cleanup_orphan_concept_rows(db_session)

        # Orphan article gone
        result = await db_session.execute(select(Article).where(Article.id == orphan.id))
        assert result.scalar_one_or_none() is None

        # Backlink also gone
        result = await db_session.execute(
            select(Backlink).where(
                Backlink.source_article_id == survivor.id,
                Backlink.target_article_id == orphan.id,
            )
        )
        assert result.scalar_one_or_none() is None

        # Survivor remains
        result = await db_session.execute(select(Article).where(Article.id == survivor.id))
        assert result.scalar_one_or_none() is not None

    async def test_idempotent_no_orphans(self, db_session, tmp_path: Path):
        """Running with zero concept articles is a no-op."""
        await _cleanup_orphan_concept_rows(db_session)
        # No error, no crash — just a no-op
