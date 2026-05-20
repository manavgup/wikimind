"""Tests for human-in-the-loop discussion before compilation (issue #418)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

from tests.conftest import TEST_USER_ID
from wikimind.models import (
    Article,
    ArticleSource,
    DiscussionMessage,
    PageType,
    Source,
    SourceType,
)

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlmodel.ext.asyncio.session import AsyncSession

_CLIENT_USER_ID = TEST_USER_ID


async def _create_article(
    db_session: AsyncSession,
    slug: str = "test-article",
    title: str = "Test Article",
    user_id: str = _CLIENT_USER_ID,
) -> Article:
    """Helper to create an article."""
    article = Article(
        slug=slug,
        title=title,
        file_path=f"general/{slug}.md",
        page_type=PageType.SOURCE,
        user_id=user_id,
    )
    db_session.add(article)
    await db_session.commit()
    await db_session.refresh(article)
    return article


async def _create_article_with_source(
    db_session: AsyncSession,
    slug: str = "test-article",
    user_id: str = _CLIENT_USER_ID,
) -> tuple[Article, Source]:
    """Helper to create an article with a linked source."""
    source = Source(
        source_type=SourceType.TEXT,
        title="Test Source",
        user_id=user_id,
        clean_text="This is the source content about machine learning.",
    )
    db_session.add(source)
    await db_session.commit()
    await db_session.refresh(source)

    article = Article(
        slug=slug,
        title="Test Article",
        file_path=f"general/{slug}.md",
        page_type=PageType.SOURCE,
        user_id=user_id,
    )
    db_session.add(article)
    await db_session.commit()
    await db_session.refresh(article)

    link = ArticleSource(article_id=article.id, source_id=source.id)
    db_session.add(link)
    await db_session.commit()

    return article, source


# ---------------------------------------------------------------------------
# GET /wiki/articles/{id}/discussion — empty thread
# ---------------------------------------------------------------------------


async def test_get_empty_discussion(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """GET discussion for an article with no messages returns empty list."""
    article = await _create_article(db_session)

    response = await client.get(f"/api/wiki/articles/{article.id}/discussion")

    assert response.status_code == 200
    data = response.json()
    assert data["article_id"] == article.id
    assert data["messages"] == []


# ---------------------------------------------------------------------------
# GET /wiki/articles/{id}/discussion — not found
# ---------------------------------------------------------------------------


async def test_get_discussion_not_found(client: AsyncClient) -> None:
    """GET discussion for a non-existent article returns 404."""
    response = await client.get("/api/wiki/articles/nonexistent-id/discussion")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /wiki/articles/{id}/discuss — happy path
# ---------------------------------------------------------------------------


async def test_post_discussion_message(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """POST a message and get an assistant response."""
    article = await _create_article(db_session)

    mock_response = MagicMock()
    mock_response.content = "Here is my analysis of the sources."

    with (
        patch(
            "wikimind.services.plan_routing.plan_aware_complete",
            new_callable=AsyncMock,
            return_value=mock_response,
        ),
        patch(
            "wikimind.storage.read_article_content",
            new_callable=AsyncMock,
            return_value="# Article content",
        ),
    ):
        response = await client.post(
            f"/api/wiki/articles/{article.id}/discuss",
            json={"message": "What are the key points in this source?"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "assistant"
    assert data["content"] == "Here is my analysis of the sources."
    assert data["article_id"] == article.id


# ---------------------------------------------------------------------------
# POST /wiki/articles/{id}/discuss — not found
# ---------------------------------------------------------------------------


async def test_post_discussion_not_found(client: AsyncClient) -> None:
    """POST discuss on a non-existent article returns 404."""
    response = await client.post(
        "/api/wiki/articles/nonexistent-id/discuss",
        json={"message": "Hello"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /wiki/articles/{id}/discuss — empty message
# ---------------------------------------------------------------------------


async def test_post_discussion_empty_message(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """POST with empty message is rejected by validation."""
    article = await _create_article(db_session)

    response = await client.post(
        f"/api/wiki/articles/{article.id}/discuss",
        json={"message": ""},
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /wiki/articles/{id}/discussion — with messages
# ---------------------------------------------------------------------------


async def test_get_discussion_with_messages(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """GET discussion returns all messages in order."""
    article = await _create_article(db_session)

    # Seed messages directly
    msg1 = DiscussionMessage(
        article_id=article.id,
        user_id=_CLIENT_USER_ID,
        role="user",
        content="What does this article cover?",
    )
    msg2 = DiscussionMessage(
        article_id=article.id,
        user_id=_CLIENT_USER_ID,
        role="assistant",
        content="The article covers machine learning concepts.",
    )
    db_session.add(msg1)
    db_session.add(msg2)
    await db_session.commit()

    response = await client.get(f"/api/wiki/articles/{article.id}/discussion")

    assert response.status_code == 200
    data = response.json()
    assert len(data["messages"]) == 2
    assert data["messages"][0]["role"] == "user"
    assert data["messages"][1]["role"] == "assistant"


# ---------------------------------------------------------------------------
# POST /wiki/articles/{id}/compile-with-guidance — happy path
# ---------------------------------------------------------------------------


async def test_compile_with_guidance(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """POST compile-with-guidance creates a recompile job."""
    article, source = await _create_article_with_source(db_session)

    # Add a discussion message
    msg = DiscussionMessage(
        article_id=article.id,
        user_id=_CLIENT_USER_ID,
        role="user",
        content="Focus more on the practical applications.",
    )
    db_session.add(msg)
    await db_session.commit()

    response = await client.post(
        f"/api/wiki/articles/{article.id}/compile-with-guidance",
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"
    assert data["job_id"] is not None


# ---------------------------------------------------------------------------
# POST /wiki/articles/{id}/compile-with-guidance — not found
# ---------------------------------------------------------------------------


async def test_compile_with_guidance_not_found(client: AsyncClient) -> None:
    """POST compile-with-guidance for a non-existent article returns 404."""
    response = await client.post(
        "/api/wiki/articles/nonexistent-id/compile-with-guidance",
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /wiki/articles/{id}/compile-with-guidance — no discussion
# ---------------------------------------------------------------------------


async def test_compile_with_guidance_no_discussion(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """POST compile-with-guidance with no discussion still creates a job."""
    article, _source = await _create_article_with_source(db_session)

    response = await client.post(
        f"/api/wiki/articles/{article.id}/compile-with-guidance",
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"


# ---------------------------------------------------------------------------
# Service unit test — discussion thread isolation by user
# ---------------------------------------------------------------------------


async def test_discussion_isolated_by_user(
    db_session: AsyncSession,
) -> None:
    """Discussion messages are scoped to the current user."""
    from wikimind.services.discussion import DiscussionService

    service = DiscussionService()

    article = await _create_article(db_session)

    # Add messages from a different user
    other_msg = DiscussionMessage(
        article_id=article.id,
        user_id="other-user",
        role="user",
        content="This should not appear.",
    )
    db_session.add(other_msg)
    await db_session.commit()

    thread = await service.get_thread(article.id, db_session, _CLIENT_USER_ID)
    assert len(thread.messages) == 0
