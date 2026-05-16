"""Tests for services/tags.py — tag management service (DB-level)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.conftest import TEST_USER_ID
from wikimind.api.services import get_tag_service
from wikimind.errors import NotFoundError
from wikimind.models import Article, PageType
from wikimind.services.tags import TagService

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession


def test_singleton():
    get_tag_service.cache_clear()
    assert get_tag_service() is get_tag_service()
    get_tag_service.cache_clear()


async def test_create_tag(db_session: AsyncSession):
    tag = await TagService().create_tag(db_session, TEST_USER_ID, "read-later")
    assert tag.name == "read-later"
    assert tag.id is not None


async def test_list_tags_empty(db_session: AsyncSession):
    assert await TagService().list_tags(db_session, TEST_USER_ID) == []


async def test_list_tags(db_session: AsyncSession):
    s = TagService()
    await s.create_tag(db_session, TEST_USER_ID, "a")
    await s.create_tag(db_session, TEST_USER_ID, "b")
    assert len(await s.list_tags(db_session, TEST_USER_ID)) == 2


async def test_delete_tag(db_session: AsyncSession):
    s = TagService()
    tag = await s.create_tag(db_session, TEST_USER_ID, "del")
    await s.delete_tag(db_session, tag.id, TEST_USER_ID)
    assert len(await s.list_tags(db_session, TEST_USER_ID)) == 0


async def test_delete_tag_not_found(db_session: AsyncSession):
    with pytest.raises(NotFoundError):
        await TagService().delete_tag(db_session, "bad", TEST_USER_ID)


async def test_tag_article(db_session: AsyncSession):
    s = TagService()
    tag = await s.create_tag(db_session, TEST_USER_ID, "imp")
    art = Article(slug="a1", title="A1", file_path="wiki/a1.md", page_type=PageType.SOURCE, user_id=TEST_USER_ID)
    db_session.add(art)
    await db_session.flush()
    await db_session.refresh(art)
    await s.tag_article(db_session, art.id, tag.id, TEST_USER_ID)
    assert len(await s.get_tags_for_article(db_session, art.id)) == 1


async def test_tag_article_idempotent(db_session: AsyncSession):
    s = TagService()
    tag = await s.create_tag(db_session, TEST_USER_ID, "dup")
    art = Article(slug="a2", title="A2", file_path="wiki/a2.md", page_type=PageType.SOURCE, user_id=TEST_USER_ID)
    db_session.add(art)
    await db_session.flush()
    await db_session.refresh(art)
    await s.tag_article(db_session, art.id, tag.id, TEST_USER_ID)
    await s.tag_article(db_session, art.id, tag.id, TEST_USER_ID)
    assert len(await s.get_tags_for_article(db_session, art.id)) == 1


async def test_untag_article(db_session: AsyncSession):
    s = TagService()
    tag = await s.create_tag(db_session, TEST_USER_ID, "rem")
    art = Article(slug="a3", title="A3", file_path="wiki/a3.md", page_type=PageType.SOURCE, user_id=TEST_USER_ID)
    db_session.add(art)
    await db_session.flush()
    await db_session.refresh(art)
    await s.tag_article(db_session, art.id, tag.id, TEST_USER_ID)
    await s.untag_article(db_session, art.id, tag.id, TEST_USER_ID)
    assert len(await s.get_tags_for_article(db_session, art.id)) == 0


async def test_untag_nonexistent(db_session: AsyncSession):
    s = TagService()
    tag = await s.create_tag(db_session, TEST_USER_ID, "t")
    art = Article(slug="a4", title="A4", file_path="wiki/a4.md", page_type=PageType.SOURCE, user_id=TEST_USER_ID)
    db_session.add(art)
    await db_session.flush()
    await db_session.refresh(art)
    with pytest.raises(NotFoundError):
        await s.untag_article(db_session, art.id, tag.id, TEST_USER_ID)


async def test_get_articles_by_tag(db_session: AsyncSession):
    s = TagService()
    tag = await s.create_tag(db_session, TEST_USER_ID, "grp")
    a1 = Article(slug="g1", title="G1", file_path="wiki/g1.md", page_type=PageType.SOURCE, user_id=TEST_USER_ID)
    db_session.add(a1)
    await db_session.flush()
    await db_session.refresh(a1)
    await s.tag_article(db_session, a1.id, tag.id, TEST_USER_ID)
    ids = await s.get_articles_by_tag(db_session, tag.id, TEST_USER_ID)
    assert a1.id in ids


async def test_get_tags_for_articles_empty(db_session: AsyncSession):
    assert await TagService().get_tags_for_articles(db_session, []) == {}


async def test_delete_tag_cascades(db_session: AsyncSession):
    s = TagService()
    tag = await s.create_tag(db_session, TEST_USER_ID, "cas")
    art = Article(slug="c1", title="C1", file_path="wiki/c1.md", page_type=PageType.SOURCE, user_id=TEST_USER_ID)
    db_session.add(art)
    await db_session.flush()
    await db_session.refresh(art)
    await s.tag_article(db_session, art.id, tag.id, TEST_USER_ID)
    await s.delete_tag(db_session, tag.id, TEST_USER_ID)
    assert len(await s.get_tags_for_article(db_session, art.id)) == 0


async def test_get_tags_for_articles_batch(db_session: AsyncSession):
    """Batch tag lookup should return tags keyed by article ID."""
    s = TagService()
    tag1 = await s.create_tag(db_session, TEST_USER_ID, "batch-a")
    tag2 = await s.create_tag(db_session, TEST_USER_ID, "batch-b")
    a1 = Article(slug="b1", title="B1", file_path="wiki/b1.md", page_type=PageType.SOURCE, user_id=TEST_USER_ID)
    a2 = Article(slug="b2", title="B2", file_path="wiki/b2.md", page_type=PageType.SOURCE, user_id=TEST_USER_ID)
    db_session.add(a1)
    db_session.add(a2)
    await db_session.flush()
    await db_session.refresh(a1)
    await db_session.refresh(a2)
    await s.tag_article(db_session, a1.id, tag1.id, TEST_USER_ID)
    await s.tag_article(db_session, a2.id, tag2.id, TEST_USER_ID)
    result = await s.get_tags_for_articles(db_session, [a1.id, a2.id])
    assert len(result[a1.id]) == 1
    assert result[a1.id][0].name == "batch-a"
    assert len(result[a2.id]) == 1
    assert result[a2.id][0].name == "batch-b"


async def test_tag_article_not_found(db_session: AsyncSession):
    """Tagging a non-existent article should raise NotFoundError."""
    s = TagService()
    tag = await s.create_tag(db_session, TEST_USER_ID, "orphan-tag")
    with pytest.raises(NotFoundError, match="Article not found"):
        await s.tag_article(db_session, "nonexistent-article-id", tag.id, TEST_USER_ID)
