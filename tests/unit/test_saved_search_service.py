"""Tests for services/saved_searches.py."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.conftest import TEST_USER_ID
from wikimind.errors import NotFoundError
from wikimind.models import Article, ArticleTag, PageType, Tag
from wikimind.services.factories import get_saved_search_service
from wikimind.services.saved_searches import SavedSearchService

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession


def test_singleton():
    get_saved_search_service.cache_clear()
    assert get_saved_search_service() is get_saved_search_service()
    get_saved_search_service.cache_clear()


async def test_create(db_session: AsyncSession):
    r = await SavedSearchService().create(db_session, TEST_USER_ID, name="S", query="ml")
    assert r.name == "S"
    assert r.id is not None


async def test_list_empty(db_session: AsyncSession):
    assert await SavedSearchService().list_searches(db_session, TEST_USER_ID) == []


async def test_delete(db_session: AsyncSession):
    s = SavedSearchService()
    r = await s.create(db_session, TEST_USER_ID, name="d", query="q")
    await s.delete(db_session, r.id, TEST_USER_ID)
    assert len(await s.list_searches(db_session, TEST_USER_ID)) == 0


async def test_delete_not_found(db_session: AsyncSession):
    with pytest.raises(NotFoundError):
        await SavedSearchService().delete(db_session, "bad", TEST_USER_ID)


async def test_execute_empty(db_session: AsyncSession):
    s = SavedSearchService()
    saved = await s.create(db_session, TEST_USER_ID, name="e", query="test")
    _resp, ids = await s.execute(db_session, saved.id, TEST_USER_ID)
    assert ids == []


async def test_execute_matches_title(db_session: AsyncSession):
    s = SavedSearchService()
    db_session.add(
        Article(
            slug="ml", title="Machine Learning", file_path="wiki/ml.md", page_type=PageType.SOURCE, user_id=TEST_USER_ID
        )
    )
    db_session.add(
        Article(slug="cook", title="Cooking", file_path="wiki/cook.md", page_type=PageType.SOURCE, user_id=TEST_USER_ID)
    )
    await db_session.flush()
    saved = await s.create(db_session, TEST_USER_ID, name="ML", query="machine learning")
    _resp, ids = await s.execute(db_session, saved.id, TEST_USER_ID)
    assert len(ids) == 1


async def test_execute_with_tag_filter(db_session: AsyncSession):
    s = SavedSearchService()
    tag = Tag(user_id=TEST_USER_ID, name="fav")
    db_session.add(tag)
    await db_session.flush()
    await db_session.refresh(tag)
    a1 = Article(slug="f1", title="Fav", file_path="wiki/f1.md", page_type=PageType.SOURCE, user_id=TEST_USER_ID)
    db_session.add(a1)
    await db_session.flush()
    await db_session.refresh(a1)
    db_session.add(ArticleTag(article_id=a1.id, tag_id=tag.id))
    await db_session.flush()
    saved = await s.create(db_session, TEST_USER_ID, name="Favs", query="", filters_json='{"tags": ["fav"]}')
    _resp, ids = await s.execute(db_session, saved.id, TEST_USER_ID)
    assert a1.id in ids


async def test_execute_invalid_json(db_session: AsyncSession):
    s = SavedSearchService()
    saved = await s.create(db_session, TEST_USER_ID, name="bad", query="", filters_json="not json")
    db_session.add(Article(slug="x", title="X", file_path="wiki/x.md", page_type=PageType.SOURCE, user_id=TEST_USER_ID))
    await db_session.flush()
    _resp, ids = await s.execute(db_session, saved.id, TEST_USER_ID)
    assert len(ids) == 1
