"""Integration tests for PostgreSQL backend.

Skipped automatically when WIKIMIND_TEST_POSTGRES_URL is not set.
To run: export WIKIMIND_TEST_POSTGRES_URL=postgresql+asyncpg://user:pass@localhost:5432/wikimind_test
"""

from __future__ import annotations

import json
import os

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from tests.conftest import TEST_USER_ID
from wikimind.database import _backfill_concepts_from_articles
from wikimind.models import Article, Concept, ConfidenceLevel, Query, Source, SourceType, User

POSTGRES_URL = os.environ.get("WIKIMIND_TEST_POSTGRES_URL")
SECOND_USER_ID = "test-user-2"

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(not POSTGRES_URL, reason="WIKIMIND_TEST_POSTGRES_URL not set"),
]


@pytest.fixture
async def pg_engine():
    """Create a Postgres engine and tables for testing, drop after."""
    engine = create_async_engine(POSTGRES_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def pg_session(pg_engine) -> AsyncSession:
    """Async session backed by Postgres test database.

    Seeds the canonical ``TEST_USER_ID`` row before yielding so tests can
    insert rows whose ``user_id`` FK points at it without violating
    Postgres' foreign-key constraints (SQLite tests get away without this
    because FKs are off by default in SQLite).
    """
    factory = async_sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        session.add(
            User(
                id=TEST_USER_ID,
                email=f"{TEST_USER_ID}@test.local",
                name="Postgres Integration Test User",
                auth_provider="jwt",
                auth_provider_id=TEST_USER_ID,
            )
        )
        await session.commit()
        yield session


class TestPostgresBasicOperations:
    async def test_create_and_read_source(self, pg_session):
        """Basic CRUD works on Postgres."""
        source = Source(source_type=SourceType.URL, source_url="https://example.com", user_id=TEST_USER_ID)
        pg_session.add(source)
        await pg_session.commit()

        result = await pg_session.exec(select(Source).where(Source.id == source.id))
        loaded = result.one()
        assert loaded.source_url == "https://example.com"

    async def test_json_column_round_trip(self, pg_session):
        """JSON columns store and retrieve data on Postgres."""
        concepts = json.dumps(["ai", "ml"])
        article = Article(
            slug="pg-json-test",
            title="PG JSON",
            file_path="pg-json-test.md",
            concept_ids=concepts,
            source_ids=json.dumps(["src-1"]),
            confidence=ConfidenceLevel.SOURCED,
            user_id=TEST_USER_ID,
        )
        pg_session.add(article)
        await pg_session.commit()

        result = await pg_session.exec(select(Article).where(Article.slug == "pg-json-test"))
        loaded = result.one()
        assert loaded.concept_ids is not None

    async def test_query_with_json_fields(self, pg_session):
        """Query model JSON fields work on Postgres."""
        q = Query(
            question="What is AI?",
            answer="Artificial Intelligence",
            source_article_ids=json.dumps(["art-1"]),
            related_article_ids=json.dumps(["art-2"]),
            user_id=TEST_USER_ID,
        )
        pg_session.add(q)
        await pg_session.commit()

        result = await pg_session.exec(select(Query).where(Query.id == q.id))
        loaded = result.one()
        assert loaded.question == "What is AI?"


class TestPostgresMigrationHelpers:
    async def test_backfill_concepts_on_postgres(self, pg_engine, pg_session):
        """_backfill_concepts_from_articles creates user-scoped concepts."""
        # Seed two articles for user 1 sharing concept "machine-learning"
        pg_session.add(
            Article(
                slug="pg-backfill-1",
                title="PG Backfill 1",
                file_path="pg-backfill-1.md",
                concept_ids=json.dumps(["Machine Learning", "new-concept"]),
                confidence=ConfidenceLevel.SOURCED,
                user_id=TEST_USER_ID,
            )
        )
        pg_session.add(
            Article(
                slug="pg-backfill-2",
                title="PG Backfill 2",
                file_path="pg-backfill-2.md",
                concept_ids=json.dumps(["Machine Learning"]),
                confidence=ConfidenceLevel.SOURCED,
                user_id=TEST_USER_ID,
            )
        )

        # Seed a second user with an overlapping concept name
        pg_session.add(
            User(
                id=SECOND_USER_ID,
                email=f"{SECOND_USER_ID}@test.local",
                name="Second Test User",
                auth_provider="jwt",
                auth_provider_id=SECOND_USER_ID,
            )
        )
        pg_session.add(
            Article(
                slug="pg-backfill-u2",
                title="PG Backfill U2",
                file_path="pg-backfill-u2.md",
                concept_ids=json.dumps(["Machine Learning", "deep-learning"]),
                confidence=ConfidenceLevel.SOURCED,
                user_id=SECOND_USER_ID,
            )
        )
        await pg_session.commit()

        await _backfill_concepts_from_articles(pg_engine)

        # ---- Assertions for user 1 ----
        result = await pg_session.exec(select(Concept).where(Concept.user_id == TEST_USER_ID).order_by(Concept.name))
        u1_concepts = result.all()
        u1_by_name = {c.name: c for c in u1_concepts}

        assert set(u1_by_name.keys()) == {"machine-learning", "new-concept"}

        ml_u1 = u1_by_name["machine-learning"]
        assert ml_u1.user_id == TEST_USER_ID
        assert ml_u1.article_count == 2  # appears in both articles
        assert ml_u1.concept_kind == "topic"

        nc_u1 = u1_by_name["new-concept"]
        assert nc_u1.user_id == TEST_USER_ID
        assert nc_u1.article_count == 1
        assert nc_u1.concept_kind == "topic"

        # ---- Assertions for user 2 ----
        result = await pg_session.exec(select(Concept).where(Concept.user_id == SECOND_USER_ID).order_by(Concept.name))
        u2_concepts = result.all()
        u2_by_name = {c.name: c for c in u2_concepts}

        assert set(u2_by_name.keys()) == {"machine-learning", "deep-learning"}

        ml_u2 = u2_by_name["machine-learning"]
        assert ml_u2.user_id == SECOND_USER_ID
        assert ml_u2.article_count == 1  # only one article for user 2
        assert ml_u2.concept_kind == "topic"

        dl_u2 = u2_by_name["deep-learning"]
        assert dl_u2.user_id == SECOND_USER_ID
        assert dl_u2.article_count == 1
        assert dl_u2.concept_kind == "topic"

        # ---- Cross-user partitioning ----
        # "machine-learning" exists for both users but they are separate rows
        assert ml_u1.id != ml_u2.id
