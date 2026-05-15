"""Tests for stub page creation and wikilink resolution (issue #451)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from sqlmodel import select

from wikimind.api.deps import ANONYMOUS_USER_ID
from wikimind.models import Article, PageType
from wikimind.services.wiki import WikiService
from wikimind.storage import get_wiki_storage

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlmodel.ext.asyncio.session import AsyncSession

from tests.conftest import TEST_USER_ID

# When auth is disabled (as in tests), get_current_user_id returns ANONYMOUS_USER_ID.
_CLIENT_USER_ID = ANONYMOUS_USER_ID


# ---------------------------------------------------------------------------
# Service-layer tests (direct WikiService calls)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_stub_article(db_session: AsyncSession, _isolated_data_dir) -> None:
    """WikiService.create_stub_article creates a stub with is_stub=True."""
    service = WikiService()
    result = await service.create_stub_article(
        title="Quantum Computing",
        body_markdown="",
        session=db_session,
        user_id=TEST_USER_ID,
    )
    assert result.title == "Quantum Computing"
    assert result.slug == "quantum-computing"
    assert result.is_stub is True

    # Verify the article is in the database
    stmt = select(Article).where(Article.id == result.id)
    db_result = await db_session.execute(stmt)
    article = db_result.scalar_one()
    assert article.is_stub is True
    assert article.page_type == PageType.SOURCE


@pytest.mark.asyncio
async def test_create_stub_with_body(db_session: AsyncSession, _isolated_data_dir) -> None:
    """Stub creation writes body_markdown to disk."""
    service = WikiService()
    result = await service.create_stub_article(
        title="Neural Networks",
        body_markdown="Some initial notes about NNs.",
        session=db_session,
        user_id=TEST_USER_ID,
    )

    storage = get_wiki_storage(TEST_USER_ID)

    stmt = select(Article).where(Article.id == result.id)
    db_result = await db_session.execute(stmt)
    article = db_result.scalar_one()
    content = await storage.read(article.file_path)
    assert "Some initial notes about NNs." in content


@pytest.mark.asyncio
async def test_create_stub_slug_collision(db_session: AsyncSession, _isolated_data_dir) -> None:
    """When a slug already exists, a suffix is appended."""
    service = WikiService()
    result1 = await service.create_stub_article(
        title="Test Article",
        body_markdown="",
        session=db_session,
        user_id=TEST_USER_ID,
    )
    result2 = await service.create_stub_article(
        title="Test Article",
        body_markdown="",
        session=db_session,
        user_id=TEST_USER_ID,
    )
    assert result1.slug == "test-article"
    assert result2.slug == "test-article-2"


@pytest.mark.asyncio
async def test_resolve_wikilinks_finds_matches(db_session: AsyncSession) -> None:
    """resolve_wikilinks returns partial title matches."""
    service = WikiService()
    db_session.add(
        Article(
            id=str(uuid.uuid4()),
            slug="machine-learning",
            title="Machine Learning",
            file_path="/tmp/ml.md",
            user_id=TEST_USER_ID,
        )
    )
    db_session.add(
        Article(
            id=str(uuid.uuid4()),
            slug="machine-translation",
            title="Machine Translation",
            file_path="/tmp/mt.md",
            user_id=TEST_USER_ID,
        )
    )
    await db_session.commit()

    matches = await service.resolve_wikilinks("Machine", db_session, user_id=TEST_USER_ID)
    assert len(matches) == 2
    titles = {m.title for m in matches}
    assert "Machine Learning" in titles
    assert "Machine Translation" in titles


@pytest.mark.asyncio
async def test_resolve_wikilinks_case_insensitive(db_session: AsyncSession) -> None:
    """Wikilink resolution is case-insensitive."""
    service = WikiService()
    db_session.add(
        Article(
            id=str(uuid.uuid4()),
            slug="react",
            title="React",
            file_path="/tmp/react.md",
            user_id=TEST_USER_ID,
        )
    )
    await db_session.commit()

    matches = await service.resolve_wikilinks("react", db_session, user_id=TEST_USER_ID)
    assert len(matches) == 1
    assert matches[0].title == "React"


@pytest.mark.asyncio
async def test_resolve_wikilinks_strips_brackets(db_session: AsyncSession) -> None:
    """Leading/trailing brackets are stripped from the query."""
    service = WikiService()
    db_session.add(
        Article(
            id=str(uuid.uuid4()),
            slug="react",
            title="React",
            file_path="/tmp/react.md",
            user_id=TEST_USER_ID,
        )
    )
    await db_session.commit()

    matches = await service.resolve_wikilinks("[[React]]", db_session, user_id=TEST_USER_ID)
    assert len(matches) == 1


@pytest.mark.asyncio
async def test_resolve_wikilinks_empty_query(db_session: AsyncSession) -> None:
    """Empty query returns no results."""
    service = WikiService()
    matches = await service.resolve_wikilinks("", db_session, user_id=TEST_USER_ID)
    assert matches == []


@pytest.mark.asyncio
async def test_process_wikilinks_resolves_existing(db_session: AsyncSession) -> None:
    """process_wikilinks replaces [[title]] with markdown links for existing articles."""
    service = WikiService()
    db_session.add(
        Article(
            id=str(uuid.uuid4()),
            slug="react",
            title="React",
            file_path="/tmp/react.md",
            user_id=TEST_USER_ID,
        )
    )
    await db_session.commit()

    result = await service.process_wikilinks(
        "Check out [[React]] for more info.",
        db_session,
        user_id=TEST_USER_ID,
    )
    assert "[React](/wiki/articles/react)" in result
    assert "[[React]]" not in result


@pytest.mark.asyncio
async def test_process_wikilinks_leaves_unresolved(db_session: AsyncSession) -> None:
    """process_wikilinks leaves [[unknown]] as-is when no article matches."""
    service = WikiService()
    result = await service.process_wikilinks(
        "See [[Unknown Topic]] for details.",
        db_session,
        user_id=TEST_USER_ID,
    )
    assert "[[Unknown Topic]]" in result


@pytest.mark.asyncio
async def test_process_wikilinks_mixed(db_session: AsyncSession) -> None:
    """process_wikilinks handles a mix of resolved and unresolved links."""
    service = WikiService()
    db_session.add(
        Article(
            id=str(uuid.uuid4()),
            slug="react",
            title="React",
            file_path="/tmp/react.md",
            user_id=TEST_USER_ID,
        )
    )
    await db_session.commit()

    result = await service.process_wikilinks(
        "Learn [[React]] and [[Vue]] frameworks.",
        db_session,
        user_id=TEST_USER_ID,
    )
    assert "[React](/wiki/articles/react)" in result
    assert "[[Vue]]" in result


# ---------------------------------------------------------------------------
# Route-level tests (HTTP endpoints via test client)
# ---------------------------------------------------------------------------


async def _seed_articles(factory) -> None:
    """Create a few articles for the anonymous user."""
    async with factory() as session:
        session.add(
            Article(
                id="a1",
                slug="machine-learning",
                title="Machine Learning",
                file_path="/tmp/ml.md",
                user_id=_CLIENT_USER_ID,
            )
        )
        session.add(
            Article(
                id="a2",
                slug="deep-learning",
                title="Deep Learning",
                file_path="/tmp/dl.md",
                user_id=_CLIENT_USER_ID,
                is_stub=True,
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_post_stub_endpoint(client: AsyncClient, _isolated_data_dir) -> None:
    """POST /wiki/articles/stub creates a stub article and returns 201."""
    response = await client.post(
        "/api/wiki/articles/stub",
        json={"title": "Quantum Computing", "body_markdown": ""},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Quantum Computing"
    assert data["is_stub"] is True
    assert data["slug"] == "quantum-computing"


@pytest.mark.asyncio
async def test_post_stub_with_body(client: AsyncClient, _isolated_data_dir) -> None:
    """POST /wiki/articles/stub with body_markdown creates file on disk."""
    response = await client.post(
        "/api/wiki/articles/stub",
        json={"title": "Neural Nets", "body_markdown": "Notes about NNs."},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["slug"] == "neural-nets"


@pytest.mark.asyncio
async def test_post_stub_empty_title_rejected(client: AsyncClient) -> None:
    """POST /wiki/articles/stub with empty title returns 422."""
    response = await client.post(
        "/api/wiki/articles/stub",
        json={"title": ""},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_wikilink_resolve_endpoint(client: AsyncClient, session_factory) -> None:
    """GET /wiki/wikilinks/resolve returns matching articles."""
    await _seed_articles(session_factory)

    response = await client.get("/api/wiki/wikilinks/resolve", params={"q": "learning"})
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    titles = {m["title"] for m in data}
    assert "Machine Learning" in titles
    assert "Deep Learning" in titles


@pytest.mark.asyncio
async def test_wikilink_resolve_shows_stub_flag(client: AsyncClient, session_factory) -> None:
    """Wikilink resolve response includes is_stub field."""
    await _seed_articles(session_factory)

    response = await client.get("/api/wiki/wikilinks/resolve", params={"q": "Deep"})
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["is_stub"] is True


@pytest.mark.asyncio
async def test_wikilink_resolve_empty_query_rejected(client: AsyncClient) -> None:
    """GET /wiki/wikilinks/resolve with empty q returns 422."""
    response = await client.get("/api/wiki/wikilinks/resolve", params={"q": ""})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_article_list_includes_stub_flag(client: AsyncClient, session_factory) -> None:
    """GET /wiki/articles returns is_stub in the response for each article."""
    await _seed_articles(session_factory)

    response = await client.get("/api/wiki/articles")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    by_slug = {a["slug"]: a for a in data}
    assert by_slug["machine-learning"]["is_stub"] is False
    assert by_slug["deep-learning"]["is_stub"] is True
