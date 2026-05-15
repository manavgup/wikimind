"""Tests for manual article editing (PATCH /wiki/articles/{slug}) and recompile safety."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

from wikimind.api.deps import ANONYMOUS_USER_ID
from wikimind.models import Article, PageType, Source, SourceType
from wikimind.storage import get_wiki_storage

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlmodel.ext.asyncio.session import AsyncSession

# When auth is disabled (as in tests), get_current_user_id returns ANONYMOUS_USER_ID.
# Tests that go through the HTTP client must create articles with this user_id
# so the service-layer user_id filter finds them.
_CLIENT_USER_ID = ANONYMOUS_USER_ID


async def _create_article_with_file(
    db_session: AsyncSession,
    slug: str = "test-article",
    title: str = "Test Article",
    content: str = "# Test\n\nOriginal content.",
    user_id: str = _CLIENT_USER_ID,
) -> Article:
    """Helper to create an article with a markdown file on disk."""
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


# ---------------------------------------------------------------------------
# PATCH /wiki/articles/{slug} — happy path
# ---------------------------------------------------------------------------


async def test_edit_article_content(
    client: AsyncClient,
    db_session: AsyncSession,
    _isolated_data_dir,
) -> None:
    """PATCH with new content updates the article and sets manually_edited."""
    article = await _create_article_with_file(db_session)

    # Write initial file so storage can read it
    storage = get_wiki_storage(_CLIENT_USER_ID)
    await storage.write(article.file_path, "# Test\n\nOriginal content.")

    response = await client.patch(
        f"/api/wiki/articles/{article.slug}",
        json={"content": "# Test\n\nUpdated content."},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["manually_edited"] is True
    assert data["edited_at"] is not None
    assert "Updated content." in data["content"]


async def test_edit_article_title(
    client: AsyncClient,
    db_session: AsyncSession,
    _isolated_data_dir,
) -> None:
    """PATCH with new title updates the article title."""
    article = await _create_article_with_file(db_session)

    storage = get_wiki_storage(_CLIENT_USER_ID)
    await storage.write(article.file_path, "# Test\n\nOriginal content.")

    response = await client.patch(
        f"/api/wiki/articles/{article.slug}",
        json={"title": "New Title"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "New Title"
    assert data["manually_edited"] is True


async def test_edit_article_both(
    client: AsyncClient,
    db_session: AsyncSession,
    _isolated_data_dir,
) -> None:
    """PATCH with both content and title updates both fields."""
    article = await _create_article_with_file(db_session)

    storage = get_wiki_storage(_CLIENT_USER_ID)
    await storage.write(article.file_path, "# Test\n\nOriginal.")

    response = await client.patch(
        f"/api/wiki/articles/{article.slug}",
        json={"content": "# Updated\n\nNew body.", "title": "Updated Title"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Updated Title"
    assert "New body." in data["content"]
    assert data["manually_edited"] is True


# ---------------------------------------------------------------------------
# PATCH /wiki/articles/{slug} — error cases
# ---------------------------------------------------------------------------


async def test_edit_article_empty_patch_no_side_effects(
    client: AsyncClient,
    db_session: AsyncSession,
    _isolated_data_dir,
) -> None:
    """PATCH with both content and title omitted must NOT set manually_edited."""
    article = await _create_article_with_file(db_session)

    storage = get_wiki_storage(_CLIENT_USER_ID)
    await storage.write(article.file_path, "# Test\n\nOriginal content.")

    response = await client.patch(
        f"/api/wiki/articles/{article.slug}",
        json={},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["manually_edited"] is False
    assert data["edited_at"] is None


async def test_edit_article_empty_string_content_rejected(
    client: AsyncClient,
    db_session: AsyncSession,
    _isolated_data_dir,
) -> None:
    """PATCH with empty-string content returns 422 validation error."""
    article = await _create_article_with_file(db_session)

    response = await client.patch(
        f"/api/wiki/articles/{article.slug}",
        json={"content": ""},
    )

    assert response.status_code == 422


async def test_edit_article_empty_string_title_rejected(
    client: AsyncClient,
    db_session: AsyncSession,
    _isolated_data_dir,
) -> None:
    """PATCH with empty-string title returns 422 validation error."""
    article = await _create_article_with_file(db_session)

    response = await client.patch(
        f"/api/wiki/articles/{article.slug}",
        json={"title": ""},
    )

    assert response.status_code == 422


async def test_edit_article_not_found(client: AsyncClient) -> None:
    """PATCH for a non-existent article returns 404."""
    response = await client.patch(
        "/api/wiki/articles/nonexistent-slug",
        json={"content": "new content"},
    )
    assert response.status_code == 404


async def test_edit_article_by_id(
    client: AsyncClient,
    db_session: AsyncSession,
    _isolated_data_dir,
) -> None:
    """PATCH by article ID (not slug) also works."""
    article = await _create_article_with_file(db_session)

    storage = get_wiki_storage(_CLIENT_USER_ID)
    await storage.write(article.file_path, "# Test\n\nOriginal.")

    response = await client.patch(
        f"/api/wiki/articles/{article.id}",
        json={"content": "# Test\n\nEdited by ID."},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["manually_edited"] is True


# ---------------------------------------------------------------------------
# Recompile respects manually_edited flag
# ---------------------------------------------------------------------------


async def test_recompile_blocked_by_manual_edit(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """POST recompile on a manually-edited article returns 409 without force."""
    article = Article(
        slug="edited-article",
        title="Edited Article",
        file_path="/tmp/edited.md",
        page_type=PageType.SOURCE,
        user_id=_CLIENT_USER_ID,
        manually_edited=True,
    )
    db_session.add(article)
    await db_session.commit()

    response = await client.post(f"/api/wiki/articles/{article.id}/recompile")

    assert response.status_code == 409
    data = response.json()
    assert "manual edits" in data["error"]["message"].lower()


async def test_recompile_force_overrides_manual_edit(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """POST recompile with force=true clears manually_edited and proceeds."""
    src = Source(source_type=SourceType.TEXT, title="src", user_id=_CLIENT_USER_ID)
    db_session.add(src)
    await db_session.commit()

    article = Article(
        slug="force-recompile-article",
        title="Force Recompile Article",
        file_path="/tmp/force.md",
        page_type=PageType.SOURCE,
        source_ids=json.dumps([src.id]),
        user_id=_CLIENT_USER_ID,
        manually_edited=True,
    )
    db_session.add(article)
    await db_session.commit()

    with patch("wikimind.api.routes.wiki.get_background_compiler") as mock_bc:
        mock_compiler = mock_bc.return_value
        mock_compiler.schedule_recompile = AsyncMock(return_value="job-1")

        response = await client.post(f"/api/wiki/articles/{article.id}/recompile?force=true")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "scheduled"

    # Verify the flag was cleared in the DB
    await db_session.refresh(article)
    assert article.manually_edited is False
    assert article.edited_at is None


async def test_recompile_unedited_article_no_force_needed(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """POST recompile on a non-edited article works without force."""
    src = Source(source_type=SourceType.TEXT, title="src", user_id=_CLIENT_USER_ID)
    db_session.add(src)
    await db_session.commit()

    article = Article(
        slug="unedited-article",
        title="Unedited Article",
        file_path="/tmp/unedited.md",
        page_type=PageType.SOURCE,
        source_ids=json.dumps([src.id]),
        user_id=_CLIENT_USER_ID,
        manually_edited=False,
    )
    db_session.add(article)
    await db_session.commit()

    with patch("wikimind.api.routes.wiki.get_background_compiler") as mock_bc:
        mock_compiler = mock_bc.return_value
        mock_compiler.schedule_recompile = AsyncMock(return_value="job-1")

        response = await client.post(f"/api/wiki/articles/{article.id}/recompile")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "scheduled"
