"""Tests for the random article feature."""

from __future__ import annotations

import pytest

from tests.conftest import TEST_USER_ID
from wikimind.errors import NotFoundError
from wikimind.models import Article
from wikimind.services.wiki import WikiService


@pytest.mark.asyncio
async def test_random_article_returns_article(db_session) -> None:
    db_session.add(
        Article(
            id="r1",
            slug="random-test",
            title="Random Test",
            file_path="/tmp/r.md",
            user_id=TEST_USER_ID,
        )
    )
    await db_session.commit()

    svc = WikiService()
    result = await svc.get_random_article(db_session, user_id=TEST_USER_ID)
    assert result.slug == "random-test"
    assert result.title == "Random Test"


@pytest.mark.asyncio
async def test_random_article_returns_one_of_many(db_session) -> None:
    for i in range(5):
        db_session.add(
            Article(
                id=f"rm{i}",
                slug=f"random-multi-{i}",
                title=f"Multi {i}",
                file_path=f"/tmp/rm{i}.md",
                user_id=TEST_USER_ID,
            )
        )
    await db_session.commit()

    svc = WikiService()
    result = await svc.get_random_article(db_session, user_id=TEST_USER_ID)
    valid_slugs = {f"random-multi-{i}" for i in range(5)}
    assert result.slug in valid_slugs


@pytest.mark.asyncio
async def test_random_article_raises_when_no_articles(db_session) -> None:
    svc = WikiService()
    with pytest.raises(NotFoundError):
        await svc.get_random_article(db_session, user_id=TEST_USER_ID)
