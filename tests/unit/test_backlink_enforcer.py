"""Tests for the backlink enforcer and Phase 4 typed links (issue #143)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select

from wikimind.config import get_settings
from wikimind.engine.backlink_enforcer import enforce_backlinks, ensure_bidirectional
from wikimind.engine.linter.contradictions import detect_contradictions
from wikimind.models import (
    Article,
    ArticleConcept,
    Backlink,
    Concept,
    LintReport,
    PageType,
    RelationType,
)

if TYPE_CHECKING:
    from pathlib import Path
from tests.conftest import TEST_USER_ID
from wikimind.api.deps import ANONYMOUS_USER_ID


def _make_article(
    tmp_path: Path,
    *,
    article_id: str = "a1",
    slug: str = "test-article",
    title: str = "Test Article",
    concept_ids: list[str] | None = None,
    page_type: PageType = PageType.SOURCE,
    claims: list[str] | None = None,
) -> Article:
    file_path = tmp_path / f"{slug}.md"
    body_lines = [f"# {title}", ""]
    if claims:
        body_lines.append("## Key Claims")
        for c in claims:
            body_lines.append(f"- {c}")
    else:
        body_lines.append("Some body content here.")
    file_path.write_text("\n".join(body_lines), encoding="utf-8")
    return Article(
        id=article_id,
        slug=slug,
        title=title,
        file_path=str(file_path),
        concept_ids=json.dumps(concept_ids) if concept_ids else None,
        page_type=page_type,
        user_id=TEST_USER_ID,
    )


@pytest.mark.asyncio
async def test_bidirectional_creates_inverse_for_contradicts(db_session, _isolated_data_dir, tmp_path):
    art_a = _make_article(tmp_path, article_id="a1", slug="art-a", title="Art A")
    art_b = _make_article(tmp_path, article_id="a2", slug="art-b", title="Art B")
    db_session.add(art_a)
    db_session.add(art_b)
    bl = Backlink(
        source_article_id="a1",
        target_article_id="a2",
        relation_type=RelationType.CONTRADICTS,
        context="claim conflict",
        user_id=TEST_USER_ID,
    )
    db_session.add(bl)
    await db_session.commit()
    created = await ensure_bidirectional(bl, db_session)
    await db_session.commit()
    assert created is True
    result = await db_session.execute(
        select(Backlink).where(Backlink.source_article_id == "a2", Backlink.target_article_id == "a1")
    )
    inverse = result.scalars().first()
    assert inverse is not None
    assert inverse.relation_type == RelationType.CONTRADICTS


@pytest.mark.asyncio
async def test_bidirectional_skips_non_symmetric(db_session, _isolated_data_dir, tmp_path):
    art_a = _make_article(tmp_path, article_id="a1", slug="art-a", title="Art A")
    art_b = _make_article(tmp_path, article_id="a2", slug="art-b", title="Art B")
    db_session.add(art_a)
    db_session.add(art_b)
    bl = Backlink(
        source_article_id="a1",
        target_article_id="a2",
        relation_type=RelationType.REFERENCES,
        context="normal link",
        user_id=TEST_USER_ID,
    )
    db_session.add(bl)
    await db_session.commit()
    created = await ensure_bidirectional(bl, db_session)
    assert created is False


@pytest.mark.asyncio
async def test_enforcer_source_page_no_concepts(db_session, _isolated_data_dir, tmp_path):
    art = _make_article(
        tmp_path, article_id="a1", slug="no-concepts", title="No Concepts", page_type=PageType.SOURCE, concept_ids=None
    )
    db_session.add(art)
    await db_session.commit()
    result = await enforce_backlinks("a1", db_session)
    assert any("no concepts" in w.lower() for w in result.warnings)


@pytest.mark.asyncio
async def test_enforcer_concept_page_insufficient_synthesizes(db_session, _isolated_data_dir, tmp_path):
    art = _make_article(
        tmp_path, article_id="c1", slug="concept-page", title="Concept Page", page_type=PageType.CONCEPT
    )
    src = _make_article(tmp_path, article_id="s1", slug="source-1", title="Source 1")
    db_session.add(art)
    db_session.add(src)
    bl = Backlink(
        source_article_id="c1", target_article_id="s1", relation_type=RelationType.SYNTHESIZES, user_id=TEST_USER_ID
    )
    db_session.add(bl)
    await db_session.commit()
    result = await enforce_backlinks("c1", db_session)
    assert any("synthesizes" in w.lower() for w in result.warnings)


@pytest.mark.asyncio
async def test_enforcer_no_orphan_check(db_session, _isolated_data_dir, tmp_path):
    """Orphan detection is handled by detect_orphans(user_id=TEST_USER_ID), not the enforcer."""
    art = _make_article(
        tmp_path, article_id="orphan1", slug="orphan", title="Orphan Article", concept_ids=["some-concept"]
    )
    db_session.add(art)
    await db_session.commit()
    result = await enforce_backlinks("orphan1", db_session)
    # The enforcer no longer checks for orphans
    assert not any("orphan" in w.lower() for w in result.warnings)


@pytest.mark.asyncio
async def test_enforcer_auto_creates_inverse(db_session, _isolated_data_dir, tmp_path):
    art_a = _make_article(tmp_path, article_id="a1", slug="art-a", title="Art A", concept_ids=["c1"])
    art_b = _make_article(tmp_path, article_id="a2", slug="art-b", title="Art B", concept_ids=["c1"])
    db_session.add(art_a)
    db_session.add(art_b)
    bl = Backlink(
        source_article_id="a1",
        target_article_id="a2",
        relation_type=RelationType.CONTRADICTS,
        context="conflict",
        user_id=TEST_USER_ID,
    )
    db_session.add(bl)
    await db_session.commit()
    await enforce_backlinks("a1", db_session)
    await db_session.commit()
    result = await db_session.execute(
        select(Backlink).where(Backlink.source_article_id == "a2", Backlink.target_article_id == "a1")
    )
    inverse = result.scalars().first()
    assert inverse is not None
    assert inverse.relation_type == RelationType.CONTRADICTS


@pytest.mark.asyncio
async def test_contradiction_detection_creates_typed_backlink(db_session, _isolated_data_dir, tmp_path):
    concept = Concept(id="c1", name="testing", article_count=2, user_id=TEST_USER_ID)
    db_session.add(concept)
    art_a = _make_article(
        tmp_path,
        article_id="a1",
        slug="article-a",
        title="Article A",
        concept_ids=["testing"],
        claims=["The sky is blue"],
    )
    art_b = _make_article(
        tmp_path,
        article_id="a2",
        slug="article-b",
        title="Article B",
        concept_ids=["testing"],
        claims=["The sky is green"],
    )
    db_session.add(art_a)
    db_session.add(art_b)
    await db_session.commit()
    db_session.add(ArticleConcept(article_id="a1", concept_name="testing"))
    db_session.add(ArticleConcept(article_id="a2", concept_name="testing"))
    await db_session.commit()
    mock_router = MagicMock()
    mock_router.complete = AsyncMock(return_value=MagicMock())
    mock_router.parse_json_response = MagicMock(
        return_value={
            "contradictions": [
                {
                    "description": "Sky color contradiction",
                    "article_a_claim": "The sky is blue",
                    "article_b_claim": "The sky is green",
                    "confidence": "high",
                }
            ]
        }
    )
    settings = get_settings()
    report = LintReport(id="r1", user_id=TEST_USER_ID)
    db_session.add(report)
    await db_session.flush()
    findings = await detect_contradictions(db_session, mock_router, settings, report, user_id=TEST_USER_ID)
    assert len(findings) == 1
    assert findings[0].article_a_claim == "The sky is blue"
    result_ab = await db_session.execute(
        select(Backlink).where(
            Backlink.source_article_id == "a1",
            Backlink.target_article_id == "a2",
            Backlink.relation_type == RelationType.CONTRADICTS,
        )
    )
    bl_ab = result_ab.scalars().first()
    assert bl_ab is not None
    assert "The sky is blue" in bl_ab.context


@pytest.mark.asyncio
async def test_resolve_contradiction_endpoint(client, async_engine):
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    async with factory() as session:
        session.add(Article(id="a1", slug="art-a", title="Art A", file_path="/tmp/a.md", user_id=TEST_USER_ID))
        session.add(Article(id="a2", slug="art-b", title="Art B", file_path="/tmp/b.md", user_id=TEST_USER_ID))
        session.add(
            Backlink(
                source_article_id="a1",
                target_article_id="a2",
                relation_type=RelationType.CONTRADICTS,
                context="conflict",
                user_id=TEST_USER_ID,
            )
        )
        session.add(
            Backlink(
                source_article_id="a2",
                target_article_id="a1",
                relation_type=RelationType.CONTRADICTS,
                context="conflict",
                user_id=TEST_USER_ID,
            )
        )
        await session.commit()
    response = await client.post(
        "/wiki/backlinks/a1/a2/resolve", json={"resolution": "source_a_wins", "resolution_note": "More recent study"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["resolved"] is True
    assert data["resolution"] == "source_a_wins"
    async with factory() as session:
        result = await session.execute(
            select(Backlink).where(Backlink.source_article_id == "a1", Backlink.target_article_id == "a2")
        )
        bl = result.scalars().first()
        assert bl.resolution == "source_a_wins"
        assert bl.resolved_at is not None


@pytest.mark.asyncio
async def test_resolve_contradiction_404(client):
    response = await client.post("/wiki/backlinks/x/y/resolve", json={"resolution": "both_valid"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_resolve_contradiction_422_invalid(client, async_engine):
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    async with factory() as session:
        session.add(Article(id="a1", slug="art-a", title="Art A", file_path="/tmp/a.md", user_id=TEST_USER_ID))
        session.add(Article(id="a2", slug="art-b", title="Art B", file_path="/tmp/b.md", user_id=TEST_USER_ID))
        session.add(
            Backlink(
                source_article_id="a1",
                target_article_id="a2",
                relation_type=RelationType.CONTRADICTS,
                context="conflict",
                user_id=TEST_USER_ID,
            )
        )
        await session.commit()
    response = await client.post("/wiki/backlinks/a1/a2/resolve", json={"resolution": "invalid_value"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_graph_api_includes_relation_type(client, async_engine):
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    async with factory() as session:
        session.add(Article(id="a1", slug="art-a", title="Art A", file_path="/tmp/a.md", user_id=ANONYMOUS_USER_ID))
        session.add(Article(id="a2", slug="art-b", title="Art B", file_path="/tmp/b.md", user_id=ANONYMOUS_USER_ID))
        session.add(
            Backlink(
                source_article_id="a1",
                target_article_id="a2",
                relation_type=RelationType.CONTRADICTS,
                context="contradiction",
                resolution="source_a_wins",
                user_id=TEST_USER_ID,
            )
        )
        await session.commit()
    response = await client.get("/wiki/graph")
    assert response.status_code == 200
    data = response.json()
    edges = data["edges"]
    assert len(edges) == 1
    assert edges[0]["relation_type"] == "contradicts"
    assert edges[0]["resolution"] == "source_a_wins"
