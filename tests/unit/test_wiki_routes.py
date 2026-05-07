"""Route-level tests for typed-edge filtering on /wiki/graph.

Also covers the /wiki/articles/{id_or_slug}/relationships endpoint (issue #423).
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from wikimind.api.deps import ANONYMOUS_USER_ID
from wikimind.models import Article, Backlink, RelationType


async def _seed_three_article_graph(factory) -> None:
    """Seed a small graph for the anonymous test user.

    a1 --references-->   a2
    a1 --contradicts--> a3
    a2 --supersedes-->  a3
    """
    async with factory() as session:
        session.add(Article(id="a1", slug="art-a", title="Art A", file_path="/tmp/a.md", user_id=ANONYMOUS_USER_ID))
        session.add(Article(id="a2", slug="art-b", title="Art B", file_path="/tmp/b.md", user_id=ANONYMOUS_USER_ID))
        session.add(Article(id="a3", slug="art-c", title="Art C", file_path="/tmp/c.md", user_id=ANONYMOUS_USER_ID))
        session.add(
            Backlink(
                source_article_id="a1",
                target_article_id="a2",
                relation_type=RelationType.REFERENCES,
                context="ref",
                user_id=ANONYMOUS_USER_ID,
            )
        )
        session.add(
            Backlink(
                source_article_id="a1",
                target_article_id="a3",
                relation_type=RelationType.CONTRADICTS,
                context="conflict",
                user_id=ANONYMOUS_USER_ID,
            )
        )
        session.add(
            Backlink(
                source_article_id="a2",
                target_article_id="a3",
                relation_type=RelationType.SUPERSEDES,
                context="newer",
                user_id=ANONYMOUS_USER_ID,
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_graph_no_filters_returns_all_edges(client, async_engine) -> None:
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    await _seed_three_article_graph(factory)

    response = await client.get("/wiki/graph")
    assert response.status_code == 200
    data = response.json()
    assert len(data["nodes"]) == 3
    assert len(data["edges"]) == 3


@pytest.mark.asyncio
async def test_graph_filter_by_relation_type(client, async_engine) -> None:
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    await _seed_three_article_graph(factory)

    response = await client.get("/wiki/graph", params={"relation_type": "contradicts"})
    assert response.status_code == 200
    data = response.json()
    edges = data["edges"]
    assert len(edges) == 1
    assert edges[0]["relation_type"] == "contradicts"
    assert edges[0]["source"] == "a1"
    assert edges[0]["target"] == "a3"


@pytest.mark.asyncio
async def test_graph_filter_by_from_article_id(client, async_engine) -> None:
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    await _seed_three_article_graph(factory)

    response = await client.get("/wiki/graph", params={"from_article": "a1"})
    assert response.status_code == 200
    data = response.json()
    edges = data["edges"]
    assert len(edges) == 2
    assert {e["target"] for e in edges} == {"a2", "a3"}


@pytest.mark.asyncio
async def test_graph_filter_by_from_article_slug(client, async_engine) -> None:
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    await _seed_three_article_graph(factory)

    response = await client.get("/wiki/graph", params={"from_article": "art-a"})
    assert response.status_code == 200
    data = response.json()
    assert len(data["edges"]) == 2


@pytest.mark.asyncio
async def test_graph_filter_by_to_article(client, async_engine) -> None:
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    await _seed_three_article_graph(factory)

    response = await client.get("/wiki/graph", params={"to_article": "a3"})
    assert response.status_code == 200
    data = response.json()
    edges = data["edges"]
    assert len(edges) == 2
    assert {e["source"] for e in edges} == {"a1", "a2"}


@pytest.mark.asyncio
async def test_graph_filters_compose_with_and(client, async_engine) -> None:
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    await _seed_three_article_graph(factory)

    # from a1 AND relation_type contradicts → only a1->a3.
    response = await client.get(
        "/wiki/graph",
        params={"from_article": "a1", "relation_type": "contradicts"},
    )
    assert response.status_code == 200
    data = response.json()
    edges = data["edges"]
    assert len(edges) == 1
    assert edges[0]["source"] == "a1"
    assert edges[0]["target"] == "a3"
    assert edges[0]["relation_type"] == "contradicts"


@pytest.mark.asyncio
async def test_graph_unknown_from_article_returns_empty(client, async_engine) -> None:
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    await _seed_three_article_graph(factory)

    response = await client.get("/wiki/graph", params={"from_article": "no-such-thing"})
    assert response.status_code == 200
    data = response.json()
    assert data["edges"] == []
    assert data["nodes"] == []


@pytest.mark.asyncio
async def test_graph_invalid_relation_type_is_422(client, async_engine) -> None:
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    await _seed_three_article_graph(factory)

    response = await client.get("/wiki/graph", params={"relation_type": "bogus"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_relationships_endpoint_groups_by_direction_and_type(client, async_engine) -> None:
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    await _seed_three_article_graph(factory)

    response = await client.get("/wiki/articles/a1/relationships")
    assert response.status_code == 200
    data = response.json()

    # a1 has two outgoing edges (references → a2, contradicts → a3) and no incoming.
    assert data["incoming"] == {}
    assert set(data["outgoing"].keys()) == {"references", "contradicts"}
    refs = data["outgoing"]["references"]
    assert len(refs) == 1
    assert refs[0]["article_id"] == "a2"
    assert refs[0]["slug"] == "art-b"
    assert refs[0]["title"] == "Art B"
    assert refs[0]["context"] == "ref"
    assert refs[0]["relation_type"] == "references"
    cons = data["outgoing"]["contradicts"]
    assert len(cons) == 1
    assert cons[0]["article_id"] == "a3"


@pytest.mark.asyncio
async def test_relationships_endpoint_resolves_slug(client, async_engine) -> None:
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    await _seed_three_article_graph(factory)

    # a3 has two incoming (a1 contradicts, a2 supersedes) and no outgoing.
    response = await client.get("/wiki/articles/art-c/relationships")
    assert response.status_code == 200
    data = response.json()
    assert data["outgoing"] == {}
    assert set(data["incoming"].keys()) == {"contradicts", "supersedes"}
    assert data["incoming"]["contradicts"][0]["article_id"] == "a1"
    assert data["incoming"]["supersedes"][0]["article_id"] == "a2"


@pytest.mark.asyncio
async def test_relationships_endpoint_404_when_missing(client) -> None:
    response = await client.get("/wiki/articles/does-not-exist/relationships")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_graph_unknown_to_article_returns_empty(client, async_engine) -> None:
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    await _seed_three_article_graph(factory)

    response = await client.get("/wiki/graph", params={"to_article": "no-such-thing"})
    assert response.status_code == 200
    data = response.json()
    assert data["edges"] == []
    assert data["nodes"] == []


@pytest.mark.asyncio
async def test_graph_filter_by_to_article_slug(client, async_engine) -> None:
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    await _seed_three_article_graph(factory)

    response = await client.get("/wiki/graph", params={"to_article": "art-c"})
    assert response.status_code == 200
    data = response.json()
    assert len(data["edges"]) == 2
