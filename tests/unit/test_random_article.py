"""Tests for the GET /wiki/articles/random endpoint."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from wikimind.api.deps import ANONYMOUS_USER_ID
from wikimind.models import Article


@pytest.mark.asyncio
async def test_random_article_returns_article(client, async_engine) -> None:
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    async with factory() as session:
        session.add(
            Article(
                id="r1",
                slug="random-test",
                title="Random Test",
                file_path="/tmp/r.md",
                user_id=ANONYMOUS_USER_ID,
            )
        )
        await session.commit()

    response = await client.get("/wiki/articles/random")
    assert response.status_code == 200
    data = response.json()
    assert data["slug"] == "random-test"
    assert data["title"] == "Random Test"


@pytest.mark.asyncio
async def test_random_article_returns_one_of_many(client, async_engine) -> None:
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    async with factory() as session:
        for i in range(5):
            session.add(
                Article(
                    id=f"rm{i}",
                    slug=f"random-multi-{i}",
                    title=f"Multi {i}",
                    file_path=f"/tmp/rm{i}.md",
                    user_id=ANONYMOUS_USER_ID,
                )
            )
        await session.commit()

    response = await client.get("/wiki/articles/random")
    assert response.status_code == 200
    data = response.json()
    valid_slugs = {f"random-multi-{i}" for i in range(5)}
    assert data["slug"] in valid_slugs


@pytest.mark.asyncio
async def test_random_article_404_when_no_articles(client) -> None:
    response = await client.get("/wiki/articles/random")
    assert response.status_code == 404
