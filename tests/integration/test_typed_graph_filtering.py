"""End-to-end test for typed-edge filtering on /wiki/graph (issue #423).

Seeds two articles with a CONTRADICTS edge between them (and a sibling
REFERENCES edge to a third article) and verifies that the
``relation_type=contradicts`` query parameter narrows the response down
to just the contradiction edge.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from wikimind.api.deps import ANONYMOUS_USER_ID
from wikimind.models import Article, Backlink, RelationType


@pytest.mark.asyncio
async def test_graph_relation_type_contradicts_returns_only_contradictions(client, async_engine) -> None:
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    async with factory() as session:
        session.add(
            Article(
                id="article-x",
                slug="article-x",
                title="Article X",
                file_path="/tmp/x.md",
                user_id=ANONYMOUS_USER_ID,
            )
        )
        session.add(
            Article(
                id="article-y",
                slug="article-y",
                title="Article Y",
                file_path="/tmp/y.md",
                user_id=ANONYMOUS_USER_ID,
            )
        )
        session.add(
            Article(
                id="article-z",
                slug="article-z",
                title="Article Z",
                file_path="/tmp/z.md",
                user_id=ANONYMOUS_USER_ID,
            )
        )
        # X contradicts Y — the edge we expect to see when filtering.
        session.add(
            Backlink(
                source_article_id="article-x",
                target_article_id="article-y",
                relation_type=RelationType.CONTRADICTS,
                context="X disagrees with Y",
                user_id=ANONYMOUS_USER_ID,
            )
        )
        # X references Z — should be excluded by the contradicts filter.
        session.add(
            Backlink(
                source_article_id="article-x",
                target_article_id="article-z",
                relation_type=RelationType.REFERENCES,
                context="see also",
                user_id=ANONYMOUS_USER_ID,
            )
        )
        await session.commit()

    # Without filter: both edges visible.
    full = await client.get("/wiki/graph")
    assert full.status_code == 200
    assert len(full.json()["edges"]) == 2

    # With contradicts filter: only X→Y survives.
    filtered = await client.get("/wiki/graph", params={"relation_type": "contradicts"})
    assert filtered.status_code == 200
    edges = filtered.json()["edges"]
    assert len(edges) == 1
    assert edges[0]["source"] == "article-x"
    assert edges[0]["target"] == "article-y"
    assert edges[0]["relation_type"] == "contradicts"
