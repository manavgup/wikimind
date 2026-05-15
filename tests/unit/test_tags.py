"""Tests for tags and saved searches (issue #454)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import TEST_USER_ID
from wikimind.config import get_settings
from wikimind.models import Article

# ---------------------------------------------------------------------------
# Tag CRUD via API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_tag(client, async_engine) -> None:
    resp = await client.post("/api/tags", json={"name": "read-later", "color": "#ef4444"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "read-later"
    assert data["color"] == "#ef4444"
    assert "id" in data


@pytest.mark.asyncio
async def test_list_tags_empty(client) -> None:
    resp = await client.get("/api/tags")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_tags_after_create(client) -> None:
    await client.post("/api/tags", json={"name": "favorite"})
    await client.post("/api/tags", json={"name": "to-revisit"})
    resp = await client.get("/api/tags")
    assert resp.status_code == 200
    tags = resp.json()
    assert len(tags) == 2
    names = {t["name"] for t in tags}
    assert names == {"favorite", "to-revisit"}


@pytest.mark.asyncio
async def test_delete_tag(client) -> None:
    create_resp = await client.post("/api/tags", json={"name": "temp"})
    tag_id = create_resp.json()["id"]
    delete_resp = await client.delete(f"/api/tags/{tag_id}")
    assert delete_resp.status_code == 204
    # Verify it's gone
    list_resp = await client.get("/api/tags")
    assert list_resp.json() == []


@pytest.mark.asyncio
async def test_delete_nonexistent_tag_returns_404(client) -> None:
    resp = await client.delete("/api/tags/nonexistent-id")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Article tagging
# ---------------------------------------------------------------------------


async def _seed_article(factory) -> str:
    """Create a test article and return its ID."""
    async with factory() as session:
        article = Article(
            id="art-1",
            slug="test-article",
            title="Test Article",
            file_path="/tmp/test.md",
            user_id=TEST_USER_ID,
        )
        session.add(article)
        await session.commit()
    return "art-1"


@pytest.mark.asyncio
async def test_tag_article(client, session_factory) -> None:
    await _seed_article(session_factory)

    tag_resp = await client.post("/api/tags", json={"name": "important"})
    tag_id = tag_resp.json()["id"]

    resp = await client.post(
        "/api/wiki/articles/art-1/tags",
        json={"tag_id": tag_id},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["article_id"] == "art-1"
    assert data["tag_id"] == tag_id


@pytest.mark.asyncio
async def test_tag_article_idempotent(client, session_factory) -> None:
    """Tagging the same article twice should not raise an error."""
    await _seed_article(session_factory)

    tag_resp = await client.post("/api/tags", json={"name": "star"})
    tag_id = tag_resp.json()["id"]

    resp1 = await client.post("/api/wiki/articles/art-1/tags", json={"tag_id": tag_id})
    assert resp1.status_code == 201

    resp2 = await client.post("/api/wiki/articles/art-1/tags", json={"tag_id": tag_id})
    assert resp2.status_code == 201


@pytest.mark.asyncio
async def test_untag_article(client, session_factory) -> None:
    await _seed_article(session_factory)

    tag_resp = await client.post("/api/tags", json={"name": "remove-me"})
    tag_id = tag_resp.json()["id"]

    await client.post("/api/wiki/articles/art-1/tags", json={"tag_id": tag_id})
    resp = await client.delete(f"/api/wiki/articles/art-1/tags/{tag_id}")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_untag_nonexistent_returns_404(client, session_factory) -> None:
    await _seed_article(session_factory)

    tag_resp = await client.post("/api/tags", json={"name": "nope"})
    tag_id = tag_resp.json()["id"]

    resp = await client.delete(f"/api/wiki/articles/art-1/tags/{tag_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_article_tags(client, session_factory) -> None:
    await _seed_article(session_factory)

    tag_resp = await client.post("/api/tags", json={"name": "alpha", "color": "#22c55e"})
    tag_id = tag_resp.json()["id"]
    await client.post("/api/wiki/articles/art-1/tags", json={"tag_id": tag_id})

    resp = await client.get("/api/wiki/articles/art-1/tags")
    assert resp.status_code == 200
    tags = resp.json()
    assert len(tags) == 1
    assert tags[0]["name"] == "alpha"
    assert tags[0]["color"] == "#22c55e"


@pytest.mark.asyncio
async def test_get_articles_by_tag(client, session_factory) -> None:
    await _seed_article(session_factory)

    tag_resp = await client.post("/api/tags", json={"name": "special"})
    tag_id = tag_resp.json()["id"]
    await client.post("/api/wiki/articles/art-1/tags", json={"tag_id": tag_id})

    resp = await client.get(f"/api/tags/{tag_id}/articles")
    assert resp.status_code == 200
    articles = resp.json()
    assert len(articles) == 1
    assert articles[0]["id"] == "art-1"


@pytest.mark.asyncio
async def test_article_response_includes_tags(client, session_factory) -> None:
    """Article detail should include tags in the response."""
    factory = session_factory

    # Seed article with a file that can be read
    settings = get_settings()
    wiki_dir = Path(settings.data_dir) / "wiki" / TEST_USER_ID
    wiki_dir.mkdir(parents=True, exist_ok=True)
    md_file = wiki_dir / "test.md"
    md_file.write_text("# Test\nSome content")

    async with factory() as session:
        article = Article(
            id="art-tagged",
            slug="tagged-article",
            title="Tagged Article",
            file_path="test.md",
            user_id=TEST_USER_ID,
        )
        session.add(article)
        await session.commit()

    tag_resp = await client.post("/api/tags", json={"name": "tagged"})
    tag_id = tag_resp.json()["id"]
    await client.post("/api/wiki/articles/art-tagged/tags", json={"tag_id": tag_id})

    resp = await client.get("/api/wiki/articles/tagged-article")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["tags"]) == 1
    assert data["tags"][0]["name"] == "tagged"


@pytest.mark.asyncio
async def test_delete_tag_cascades_to_associations(client, session_factory) -> None:
    """Deleting a tag should remove all article-tag associations."""
    await _seed_article(session_factory)

    tag_resp = await client.post("/api/tags", json={"name": "cascade-test"})
    tag_id = tag_resp.json()["id"]
    await client.post("/api/wiki/articles/art-1/tags", json={"tag_id": tag_id})

    await client.delete(f"/api/tags/{tag_id}")

    # Verify article no longer has the tag
    resp = await client.get("/api/wiki/articles/art-1/tags")
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# Saved searches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_saved_search(client) -> None:
    resp = await client.post(
        "/api/saved-searches",
        json={
            "name": "Q2 Research",
            "query": "machine learning",
            "filters_json": json.dumps({"tags": ["read-later"]}),
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Q2 Research"
    assert data["query"] == "machine learning"


@pytest.mark.asyncio
async def test_list_saved_searches(client) -> None:
    await client.post("/api/saved-searches", json={"name": "Search 1", "query": "test"})
    await client.post("/api/saved-searches", json={"name": "Search 2", "query": "demo"})
    resp = await client.get("/api/saved-searches")
    assert resp.status_code == 200
    searches = resp.json()
    assert len(searches) == 2


@pytest.mark.asyncio
async def test_delete_saved_search(client) -> None:
    create_resp = await client.post(
        "/api/saved-searches",
        json={"name": "Temp", "query": "temporary"},
    )
    search_id = create_resp.json()["id"]
    del_resp = await client.delete(f"/api/saved-searches/{search_id}")
    assert del_resp.status_code == 204

    list_resp = await client.get("/api/saved-searches")
    assert list_resp.json() == []


@pytest.mark.asyncio
async def test_execute_saved_search_empty(client) -> None:
    """Executing a search with no matching articles returns empty list."""
    create_resp = await client.post(
        "/api/saved-searches",
        json={"name": "Empty", "query": "nonexistent-title"},
    )
    search_id = create_resp.json()["id"]

    resp = await client.post(f"/api/saved-searches/{search_id}/execute")
    assert resp.status_code == 200
    data = resp.json()
    assert data["articles"] == []
    assert data["saved_search"]["name"] == "Empty"


@pytest.mark.asyncio
async def test_execute_saved_search_with_tag_filter(client, session_factory) -> None:
    """Executing a search with tag filter returns only tagged articles."""
    factory = session_factory

    async with factory() as session:
        session.add(
            Article(
                id="art-a",
                slug="alpha",
                title="Alpha Article",
                file_path="/tmp/a.md",
                user_id=TEST_USER_ID,
            )
        )
        session.add(
            Article(
                id="art-b",
                slug="beta",
                title="Beta Article",
                file_path="/tmp/b.md",
                user_id=TEST_USER_ID,
            )
        )
        await session.commit()

    # Create tag and apply to art-a only
    tag_resp = await client.post("/api/tags", json={"name": "research"})
    tag_id = tag_resp.json()["id"]
    await client.post("/api/wiki/articles/art-a/tags", json={"tag_id": tag_id})

    # Create saved search that filters by tag
    create_resp = await client.post(
        "/api/saved-searches",
        json={
            "name": "Research",
            "query": "",
            "filters_json": json.dumps({"tags": ["research"]}),
        },
    )
    search_id = create_resp.json()["id"]

    resp = await client.post(f"/api/saved-searches/{search_id}/execute")
    assert resp.status_code == 200
    articles = resp.json()["articles"]
    assert len(articles) == 1
    assert articles[0]["id"] == "art-a"
