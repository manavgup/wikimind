"""Unit tests for faceted search — facet computation and filter application."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from tests.conftest import TEST_USER_ID
from wikimind.models import (
    Article,
    ArticleConcept,
    FacetBucket,
    FacetGroup,
    FacetResponse,
    User,
)
from wikimind.services.search import (
    SearchService,
    _matches_staleness_bucket,
    create_fts_table,
    index_article,
)

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession


@pytest.fixture
async def fts_engine() -> AsyncEngine:
    """In-memory SQLite engine with FTS5 table created."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    await create_fts_table(engine)
    return engine


@pytest.fixture
async def fts_session(fts_engine: AsyncEngine) -> AsyncSession:
    """Session backed by the FTS-enabled in-memory engine."""
    factory = async_sessionmaker(fts_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


async def _ensure_user(session: AsyncSession, user_id: str = TEST_USER_ID) -> None:
    """Make sure the test user exists."""
    existing = await session.get(User, user_id)
    if not existing:
        session.add(
            User(
                id=user_id,
                email=f"{user_id}@test.com",
                auth_provider="test",
                auth_provider_id=user_id,
            )
        )
        await session.commit()


async def _create_article(
    session: AsyncSession,
    title: str,
    slug: str,
    content: str,
    user_id: str = TEST_USER_ID,
    page_type: str = "source",
) -> Article:
    """Create an Article row and index it in FTS."""
    await _ensure_user(session, user_id)

    article = Article(
        title=title,
        slug=slug,
        file_path=f"{slug}/{slug}.md",
        user_id=user_id,
        summary=content[:200],
        page_type=page_type,
    )
    session.add(article)
    await session.commit()
    await session.refresh(article)

    await index_article(session, article.id, title, content)
    await session.commit()
    return article


# ---------------------------------------------------------------------------
# Facet model tests
# ---------------------------------------------------------------------------


class TestFacetModels:
    def test_facet_bucket(self):
        bucket = FacetBucket(value="pdf", count=12)
        assert bucket.value == "pdf"
        assert bucket.count == 12

    def test_facet_group(self):
        group = FacetGroup(
            name="source_kind",
            buckets=[FacetBucket(value="pdf", count=12)],
        )
        assert group.name == "source_kind"
        assert len(group.buckets) == 1

    def test_facet_response(self):
        resp = FacetResponse(
            facets=[
                FacetGroup(
                    name="page_type",
                    buckets=[FacetBucket(value="source", count=5)],
                )
            ],
            total=5,
            query="test",
        )
        assert resp.total == 5
        assert len(resp.facets) == 1


# ---------------------------------------------------------------------------
# Staleness bucket helper
# ---------------------------------------------------------------------------


class TestMatchesStalnessBucket:
    def test_low(self):
        assert _matches_staleness_bucket("low", 0.1) is True
        assert _matches_staleness_bucket("low", 0.3) is False

    def test_medium(self):
        assert _matches_staleness_bucket("medium", 0.5) is True
        assert _matches_staleness_bucket("medium", 0.1) is False

    def test_high(self):
        assert _matches_staleness_bucket("high", 0.8) is True
        assert _matches_staleness_bucket("high", 0.5) is False

    def test_unknown(self):
        assert _matches_staleness_bucket("unknown", 0.5) is False


# ---------------------------------------------------------------------------
# Faceted search integration
# ---------------------------------------------------------------------------


class TestFacetedSearch:
    @pytest.mark.asyncio
    async def test_search_with_page_type_filter(self, fts_session: AsyncSession):
        """Filtering by page_type narrows results."""
        await _create_article(
            fts_session,
            title="ML Source Article",
            slug="ml-source",
            content="Machine learning is about learning from data.",
            page_type="source",
        )
        await _create_article(
            fts_session,
            title="ML Concept Page",
            slug="ml-concept",
            content="Machine learning concept overview.",
            page_type="concept",
        )

        service = SearchService()

        # Without filter: both results
        resp = await service.search(
            "machine learning",
            fts_session,
            user_id=TEST_USER_ID,
        )
        assert resp.total == 2

        # With page_type filter
        resp = await service.search(
            "machine learning",
            fts_session,
            user_id=TEST_USER_ID,
            page_type="source",
        )
        assert resp.total == 1
        assert resp.results[0].slug == "ml-source"

    @pytest.mark.asyncio
    async def test_search_with_concept_filter(self, fts_session: AsyncSession):
        """Filtering by concept narrows results."""
        art1 = await _create_article(
            fts_session,
            title="Python for Data Science",
            slug="python-data",
            content="Python is widely used for data science applications.",
        )
        await _create_article(
            fts_session,
            title="Python Web Development",
            slug="python-web",
            content="Python is also used for web development.",
        )

        # Tag art1 with a concept
        fts_session.add(ArticleConcept(article_id=art1.id, concept_name="data-science"))
        await fts_session.commit()

        service = SearchService()

        # Filter by concept
        resp = await service.search(
            "python",
            fts_session,
            user_id=TEST_USER_ID,
            concept="data-science",
        )
        assert resp.total == 1
        assert resp.results[0].slug == "python-data"

    @pytest.mark.asyncio
    async def test_get_facets_returns_page_type(self, fts_session: AsyncSession):
        """get_facets should include page_type group."""
        await _create_article(
            fts_session,
            title="Testing Guide",
            slug="testing-guide",
            content="A guide about testing software.",
            page_type="source",
        )

        service = SearchService()
        facets = await service.get_facets(
            "testing",
            fts_session,
            user_id=TEST_USER_ID,
        )

        assert facets.total == 1
        page_type_facet = next(
            (f for f in facets.facets if f.name == "page_type"),
            None,
        )
        assert page_type_facet is not None
        assert page_type_facet.buckets[0].value == "source"
        assert page_type_facet.buckets[0].count == 1

    @pytest.mark.asyncio
    async def test_get_facets_empty_query(self, fts_session: AsyncSession):
        """Empty query returns no facets."""
        service = SearchService()
        facets = await service.get_facets(
            "",
            fts_session,
            user_id=TEST_USER_ID,
        )
        assert facets.total == 0
        assert facets.facets == []

    @pytest.mark.asyncio
    async def test_sort_by_recency(self, fts_session: AsyncSession):
        """Sort=recency should order by updated_at descending."""
        await _create_article(
            fts_session,
            title="Old Article about Testing",
            slug="old-testing",
            content="An older article about testing.",
        )
        await _create_article(
            fts_session,
            title="New Article about Testing",
            slug="new-testing",
            content="A newer article about testing.",
        )

        service = SearchService()

        # By recency — art2 was created after art1
        resp = await service.search(
            "testing",
            fts_session,
            user_id=TEST_USER_ID,
            sort="recency",
        )
        assert resp.total == 2
        # The newer article should come first
        assert resp.results[0].slug == "new-testing"
