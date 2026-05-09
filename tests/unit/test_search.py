"""Unit tests for FTS5-backed full-text search service."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from tests.conftest import TEST_USER_ID
from wikimind.models import Article, SearchResponse, SearchResult, User
from wikimind.services.search import (
    SearchService,
    _article_id_to_rowid,
    _sanitize_fts5_query,
    _sanitize_postgres_query,
    create_fts_table,
    get_search_service,
    index_article,
    rebuild_fts_index,
    remove_article,
    search_articles,
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


async def _create_article(
    session: AsyncSession,
    title: str,
    slug: str,
    content: str,
    user_id: str = TEST_USER_ID,
) -> Article:
    """Helper: create an Article row and index it in FTS."""
    # Ensure test user exists
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

    article = Article(
        title=title,
        slug=slug,
        file_path=f"{slug}/{slug}.md",
        user_id=user_id,
        summary=content[:200],
    )
    session.add(article)
    await session.commit()
    await session.refresh(article)

    # Index in FTS
    await index_article(session, article.id, title, content)
    await session.commit()

    return article


# ---------------------------------------------------------------------------
# Sanitizer tests
# ---------------------------------------------------------------------------


class TestSanitizeFts5Query:
    def test_simple_words(self):
        assert _sanitize_fts5_query("hello world") == '"hello"* "world"*'

    def test_empty_string(self):
        assert _sanitize_fts5_query("") == ""

    def test_whitespace_only(self):
        assert _sanitize_fts5_query("   ") == ""

    def test_single_word(self):
        assert _sanitize_fts5_query("python") == '"python"*'


class TestSanitizePostgresQuery:
    def test_simple_words(self):
        assert _sanitize_postgres_query("hello world") == "hello:* & world:*"

    def test_empty_string(self):
        assert _sanitize_postgres_query("") == ""

    def test_special_characters_stripped(self):
        result = _sanitize_postgres_query("hello! world?")
        assert "!" not in result
        assert "?" not in result


# ---------------------------------------------------------------------------
# Rowid hashing
# ---------------------------------------------------------------------------


class TestArticleIdToRowid:
    def test_deterministic(self):
        assert _article_id_to_rowid("abc") == _article_id_to_rowid("abc")

    def test_positive(self):
        assert _article_id_to_rowid("abc") > 0

    def test_different_ids_different_rowids(self):
        assert _article_id_to_rowid("abc") != _article_id_to_rowid("def")


# ---------------------------------------------------------------------------
# FTS indexing and search
# ---------------------------------------------------------------------------


class TestFtsSearch:
    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self, fts_session: AsyncSession):
        results, total = await search_articles(fts_session, "", TEST_USER_ID)
        assert results == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_no_articles_returns_empty(self, fts_session: AsyncSession):
        results, total = await search_articles(fts_session, "python", TEST_USER_ID)
        assert results == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_search_finds_matching_article(self, fts_session: AsyncSession):
        await _create_article(
            fts_session,
            title="Python Programming Guide",
            slug="python-programming-guide",
            content="Python is a versatile programming language used for web development.",
        )

        results, total = await search_articles(fts_session, "python", TEST_USER_ID)
        assert len(results) == 1
        assert total == 1
        assert results[0].title == "Python Programming Guide"
        assert results[0].slug == "python-programming-guide"
        assert results[0].snippet is not None
        assert results[0].rank is not None

    @pytest.mark.asyncio
    async def test_search_does_not_find_unrelated(self, fts_session: AsyncSession):
        await _create_article(
            fts_session,
            title="Python Programming Guide",
            slug="python-programming-guide",
            content="Python is a versatile programming language.",
        )

        results, total = await search_articles(fts_session, "javascript", TEST_USER_ID)
        assert results == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_search_multiple_results(self, fts_session: AsyncSession):
        await _create_article(
            fts_session,
            title="Machine Learning Basics",
            slug="ml-basics",
            content="Machine learning is a subset of artificial intelligence.",
        )
        await _create_article(
            fts_session,
            title="Deep Learning Overview",
            slug="deep-learning",
            content="Deep learning uses neural networks for machine learning tasks.",
        )

        results, total = await search_articles(fts_session, "machine learning", TEST_USER_ID)
        assert len(results) == 2
        assert total == 2

    @pytest.mark.asyncio
    async def test_search_user_scoping(self, fts_session: AsyncSession):
        """User A's articles should not appear in user B's search."""
        await _create_article(
            fts_session,
            title="User A Secret",
            slug="user-a-secret",
            content="This is a secret document about quantum computing.",
            user_id="user-a",
        )
        await _create_article(
            fts_session,
            title="User B Public",
            slug="user-b-public",
            content="This is a public document about quantum computing.",
            user_id="user-b",
        )

        results_a, total_a = await search_articles(fts_session, "quantum", "user-a")
        results_b, total_b = await search_articles(fts_session, "quantum", "user-b")

        assert len(results_a) == 1
        assert total_a == 1
        assert results_a[0].title == "User A Secret"

        assert len(results_b) == 1
        assert total_b == 1
        assert results_b[0].title == "User B Public"

    @pytest.mark.asyncio
    async def test_search_content_match(self, fts_session: AsyncSession):
        """Search should match on article content, not just title."""
        await _create_article(
            fts_session,
            title="Generic Title",
            slug="generic-title",
            content="The article discusses transformer architectures in detail.",
        )

        results, _total = await search_articles(fts_session, "transformer", TEST_USER_ID)
        assert len(results) == 1
        assert results[0].title == "Generic Title"

    @pytest.mark.asyncio
    async def test_search_title_match(self, fts_session: AsyncSession):
        """Search should match on article title."""
        await _create_article(
            fts_session,
            title="Kubernetes Deployment Patterns",
            slug="k8s-deploy",
            content="Some content without the title keywords.",
        )

        results, _total = await search_articles(fts_session, "kubernetes", TEST_USER_ID)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_remove_article_from_index(self, fts_session: AsyncSession):
        """Removing an article from FTS should make it unsearchable."""
        article = await _create_article(
            fts_session,
            title="Temporary Article",
            slug="temp-article",
            content="This article is about ephemeral computing resources.",
        )

        # Verify it's searchable
        results, total = await search_articles(fts_session, "ephemeral", TEST_USER_ID)
        assert len(results) == 1

        # Remove from FTS
        await remove_article(fts_session, article.id)
        await fts_session.commit()

        # Verify it's gone
        results, total = await search_articles(fts_session, "ephemeral", TEST_USER_ID)
        assert results == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_update_article_in_index(self, fts_session: AsyncSession):
        """Re-indexing an article should update its searchable content."""
        article = await _create_article(
            fts_session,
            title="Original Title",
            slug="original",
            content="Original content about databases.",
        )

        # Update the FTS entry with new content
        await index_article(
            fts_session,
            article.id,
            "Original Title",
            "Updated content about microservices.",
        )
        await fts_session.commit()

        # Old content should not match
        results, _total = await search_articles(fts_session, "databases", TEST_USER_ID)
        assert results == []

        # New content should match
        results, _total = await search_articles(fts_session, "microservices", TEST_USER_ID)
        assert len(results) == 1
        assert results[0].title == "Original Title"

    @pytest.mark.asyncio
    async def test_search_pagination(self, fts_session: AsyncSession):
        """Offset and limit should control result pagination."""
        for i in range(5):
            await _create_article(
                fts_session,
                title=f"Article {i} about testing",
                slug=f"article-{i}",
                content=f"This is testing article number {i} about software testing.",
            )

        all_results, total = await search_articles(fts_session, "testing", TEST_USER_ID, limit=10)
        assert len(all_results) == 5
        assert total == 5

        limited, total = await search_articles(fts_session, "testing", TEST_USER_ID, limit=2)
        assert len(limited) == 2
        assert total == 5

        offset_results, total = await search_articles(fts_session, "testing", TEST_USER_ID, limit=2, offset=2)
        assert len(offset_results) == 2
        assert total == 5

    @pytest.mark.asyncio
    async def test_prefix_matching(self, fts_session: AsyncSession):
        """FTS5 prefix matching should find partial words."""
        await _create_article(
            fts_session,
            title="Programming Languages",
            slug="programming-langs",
            content="Discussion of various programming paradigms.",
        )

        results, _total = await search_articles(fts_session, "program", TEST_USER_ID)
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestSearchModels:
    def test_search_result_schema(self):
        result = SearchResult(
            article_id="abc",
            slug="test-slug",
            title="Test",
            snippet="Some <mark>test</mark> snippet",
            rank=-1.5,
        )
        assert result.article_id == "abc"
        assert result.snippet == "Some <mark>test</mark> snippet"

    def test_search_response_schema(self):
        response = SearchResponse(
            results=[
                SearchResult(
                    article_id="abc",
                    slug="test",
                    title="Test",
                    snippet="...",
                    rank=-1.0,
                )
            ],
            total=1,
            query="test",
        )
        assert response.total == 1
        assert len(response.results) == 1


# ---------------------------------------------------------------------------
# Rebuild FTS index
# ---------------------------------------------------------------------------


class TestRebuildFtsIndex:
    @pytest.mark.asyncio
    async def test_rebuild_empty_db(self, fts_session: AsyncSession):
        count = await rebuild_fts_index(fts_session)
        assert count == 0

    @pytest.mark.asyncio
    async def test_rebuild_with_articles(self, fts_session: AsyncSession):
        """Rebuild should re-index all articles and make them searchable."""
        from unittest.mock import AsyncMock, patch

        existing = await fts_session.get(User, TEST_USER_ID)
        if not existing:
            fts_session.add(
                User(
                    id=TEST_USER_ID,
                    email=f"{TEST_USER_ID}@test.com",
                    auth_provider="test",
                    auth_provider_id=TEST_USER_ID,
                )
            )
            await fts_session.commit()

        a1 = Article(
            title="Rebuild Test",
            slug="rebuild-test",
            file_path="wiki/rebuild-test.md",
            user_id=TEST_USER_ID,
            summary="Content about rebuilding indexes.",
        )
        fts_session.add(a1)
        await fts_session.commit()

        mock_storage = AsyncMock()
        mock_storage.read = AsyncMock(return_value="Content about rebuilding indexes.")
        with patch("wikimind.services.search.get_wiki_storage", return_value=mock_storage):
            count = await rebuild_fts_index(fts_session)

        assert count == 1

        results, total = await search_articles(fts_session, "rebuild", TEST_USER_ID)
        assert total == 1


# ---------------------------------------------------------------------------
# SearchService wrapper
# ---------------------------------------------------------------------------


class TestSearchService:
    def test_singleton(self):
        get_search_service.cache_clear()
        svc1 = get_search_service()
        svc2 = get_search_service()
        assert svc1 is svc2
        get_search_service.cache_clear()

    @pytest.mark.asyncio
    async def test_search_delegates_to_search_articles(self, fts_session: AsyncSession):
        """SearchService.search should delegate to the module-level search_articles."""
        await _create_article(
            fts_session,
            title="Wrapper Test Article",
            slug="wrapper-test",
            content="Testing the SearchService wrapper class.",
        )

        svc = SearchService()
        response = await svc.search("wrapper", fts_session, user_id=TEST_USER_ID)
        assert response.total == 1
        assert response.results[0].title == "Wrapper Test Article"


# ---------------------------------------------------------------------------
# Sanitizer edge cases
# ---------------------------------------------------------------------------


class TestSanitizerEdgeCases:
    def test_fts5_strips_quotes(self):
        result = _sanitize_fts5_query('hello "world"')
        assert '"' not in result.replace('"hello"*', "").replace('"world"*', "")

    def test_postgres_strips_special_chars(self):
        result = _sanitize_postgres_query("hello@world #test")
        assert "@" not in result
        assert "#" not in result

    def test_postgres_empty_after_stripping(self):
        result = _sanitize_postgres_query("!!! @@@")
        assert result == ""
