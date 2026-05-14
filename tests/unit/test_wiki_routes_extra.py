"""Tests for user_id ownership checks on recompile_article and get_article_tags.

Covers issues #660 (recompile_article) and #663 (get_article_tags).
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from wikimind.api.deps import ANONYMOUS_USER_ID
from wikimind.models import Article

OTHER_USER_ID = "other-user"


async def _seed_articles(factory) -> None:
    """Create one article per user."""
    async with factory() as session:
        session.add(
            Article(
                id="own-art",
                slug="own-article",
                title="Own Article",
                file_path="/tmp/own.md",
                user_id=ANONYMOUS_USER_ID,
            )
        )
        session.add(
            Article(
                id="other-art",
                slug="other-article",
                title="Other Article",
                file_path="/tmp/other.md",
                user_id=OTHER_USER_ID,
            )
        )
        await session.commit()


# ---------------------------------------------------------------------------
# recompile_article — user_id ownership (#660)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recompile_own_article_succeeds(client, async_engine) -> None:
    """Recompiling own article should return 200 with scheduled status."""
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    await _seed_articles(factory)

    resp = await client.post("/api/wiki/articles/own-art/recompile")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "scheduled"
    assert "job_id" in data


@pytest.mark.asyncio
async def test_recompile_other_users_article_returns_404(client, async_engine) -> None:
    """Recompiling another user's article should return 404."""
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    await _seed_articles(factory)

    resp = await client.post("/api/wiki/articles/other-art/recompile")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_recompile_nonexistent_article_returns_404(client) -> None:
    """Recompiling a nonexistent article should return 404."""
    resp = await client.post("/api/wiki/articles/does-not-exist/recompile")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# get_article_tags — user_id ownership (#663)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_tags_own_article(client, async_engine) -> None:
    """Getting tags for own article should succeed (empty list when untagged)."""
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    await _seed_articles(factory)

    resp = await client.get("/api/wiki/articles/own-art/tags")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_tags_other_users_article_returns_404(client, async_engine) -> None:
    """Getting tags for another user's article should return 404."""
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    await _seed_articles(factory)

    resp = await client.get("/api/wiki/articles/other-art/tags")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_tags_own_article_with_tags(client, async_engine) -> None:
    """Getting tags for own article that has tags should return them."""
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    await _seed_articles(factory)

    # Create a tag and apply it
    tag_resp = await client.post("/api/tags", json={"name": "important", "color": "#ef4444"})
    tag_id = tag_resp.json()["id"]
    await client.post("/api/wiki/articles/own-art/tags", json={"tag_id": tag_id})

    resp = await client.get("/api/wiki/articles/own-art/tags")
    assert resp.status_code == 200
    tags = resp.json()
    assert len(tags) == 1
    assert tags[0]["name"] == "important"
