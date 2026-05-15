"""Tests for persisted contradictions — model, service, and API routes."""

from __future__ import annotations

import pytest

from tests.conftest import TEST_USER_ID
from wikimind.errors import NotFoundError
from wikimind.models import (
    Article,
    Contradiction,
    ContradictionStatus,
)
from wikimind.services.contradiction import ContradictionService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_articles_and_contradictions(factory) -> None:
    """Seed two articles and one active contradiction for the anonymous user."""
    async with factory() as session:
        session.add(
            Article(
                id="a1",
                slug="art-a",
                title="Article Alpha",
                file_path="/tmp/a.md",
                user_id=TEST_USER_ID,
            )
        )
        session.add(
            Article(
                id="a2",
                slug="art-b",
                title="Article Beta",
                file_path="/tmp/b.md",
                user_id=TEST_USER_ID,
            )
        )
        session.add(
            Article(
                id="a3",
                slug="art-c",
                title="Article Gamma",
                file_path="/tmp/c.md",
                user_id=TEST_USER_ID,
            )
        )
        session.add(
            Contradiction(
                id="ctr1",
                claim_a="The sky is blue",
                claim_b="The sky is green",
                article_a_id="a1",
                article_b_id="a2",
                status=ContradictionStatus.ACTIVE,
                user_id=TEST_USER_ID,
            )
        )
        session.add(
            Contradiction(
                id="ctr2",
                claim_a="Water boils at 100C",
                claim_b="Water boils at 90C",
                article_a_id="a1",
                article_b_id="a3",
                status=ContradictionStatus.RESOLVED,
                resolution="Both valid at different altitudes",
                user_id=TEST_USER_ID,
            )
        )
        await session.commit()


# ---------------------------------------------------------------------------
# Service layer tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_service_list_all_contradictions(db_session) -> None:
    """list_contradictions returns all contradictions for the user."""
    db_session.add(Article(id="a1", slug="a1", title="A1", file_path="a.md", user_id=TEST_USER_ID))
    db_session.add(Article(id="a2", slug="a2", title="A2", file_path="b.md", user_id=TEST_USER_ID))
    db_session.add(
        Contradiction(
            id="c1",
            claim_a="X",
            claim_b="Y",
            article_a_id="a1",
            article_b_id="a2",
            user_id=TEST_USER_ID,
        )
    )
    await db_session.commit()

    service = ContradictionService()
    results = await service.list_contradictions(db_session, user_id=TEST_USER_ID)
    assert len(results) == 1
    assert results[0].id == "c1"
    assert results[0].article_a_title == "A1"
    assert results[0].article_b_title == "A2"


@pytest.mark.asyncio
async def test_service_list_filter_by_status(db_session) -> None:
    """list_contradictions with status filter returns only matching records."""
    db_session.add(Article(id="a1", slug="a1", title="A1", file_path="a.md", user_id=TEST_USER_ID))
    db_session.add(Article(id="a2", slug="a2", title="A2", file_path="b.md", user_id=TEST_USER_ID))
    db_session.add(
        Contradiction(
            id="c1",
            claim_a="X",
            claim_b="Y",
            article_a_id="a1",
            article_b_id="a2",
            status=ContradictionStatus.ACTIVE,
            user_id=TEST_USER_ID,
        )
    )
    db_session.add(
        Contradiction(
            id="c2",
            claim_a="A",
            claim_b="B",
            article_a_id="a1",
            article_b_id="a2",
            status=ContradictionStatus.RESOLVED,
            user_id=TEST_USER_ID,
        )
    )
    await db_session.commit()

    service = ContradictionService()
    active = await service.list_contradictions(db_session, user_id=TEST_USER_ID, status=ContradictionStatus.ACTIVE)
    assert len(active) == 1
    assert active[0].id == "c1"


@pytest.mark.asyncio
async def test_service_get_single_contradiction(db_session) -> None:
    """get_contradiction returns the record with article titles."""
    db_session.add(Article(id="a1", slug="a1", title="Alpha", file_path="a.md", user_id=TEST_USER_ID))
    db_session.add(Article(id="a2", slug="a2", title="Beta", file_path="b.md", user_id=TEST_USER_ID))
    db_session.add(
        Contradiction(
            id="c1",
            claim_a="X",
            claim_b="Y",
            article_a_id="a1",
            article_b_id="a2",
            user_id=TEST_USER_ID,
        )
    )
    await db_session.commit()

    service = ContradictionService()
    result = await service.get_contradiction(db_session, "c1", user_id=TEST_USER_ID)
    assert result.claim_a == "X"
    assert result.article_a_title == "Alpha"
    assert result.article_b_title == "Beta"


@pytest.mark.asyncio
async def test_service_get_contradiction_not_found(db_session) -> None:
    """get_contradiction raises NotFoundError for missing ID."""
    service = ContradictionService()
    with pytest.raises(NotFoundError):
        await service.get_contradiction(db_session, "no-such-id", user_id=TEST_USER_ID)


@pytest.mark.asyncio
async def test_service_resolve_contradiction(db_session) -> None:
    """resolve_contradiction updates status, resolution, and timestamps."""
    db_session.add(Article(id="a1", slug="a1", title="A1", file_path="a.md", user_id=TEST_USER_ID))
    db_session.add(Article(id="a2", slug="a2", title="A2", file_path="b.md", user_id=TEST_USER_ID))
    db_session.add(
        Contradiction(
            id="c1",
            claim_a="X",
            claim_b="Y",
            article_a_id="a1",
            article_b_id="a2",
            user_id=TEST_USER_ID,
        )
    )
    await db_session.commit()

    service = ContradictionService()
    result = await service.resolve_contradiction(
        db_session,
        "c1",
        user_id=TEST_USER_ID,
        new_status=ContradictionStatus.RESOLVED,
        resolution="A1 has more recent data",
    )
    assert result.status == "resolved"
    assert result.resolution == "A1 has more recent data"
    assert result.resolved_at is not None
    assert result.resolved_by == TEST_USER_ID


@pytest.mark.asyncio
async def test_service_resolve_contradiction_not_found(db_session) -> None:
    """resolve_contradiction raises NotFoundError for bad ID."""
    service = ContradictionService()
    with pytest.raises(NotFoundError):
        await service.resolve_contradiction(
            db_session,
            "nonexistent-id",
            user_id=TEST_USER_ID,
            new_status=ContradictionStatus.RESOLVED,
            resolution="test",
        )


@pytest.mark.asyncio
async def test_service_create_from_finding_deduplicates_same_claims(db_session) -> None:
    """create_from_finding deduplicates on claim-pair level, not article-pair."""
    db_session.add(Article(id="a1", slug="a1", title="A1", file_path="a.md", user_id=TEST_USER_ID))
    db_session.add(Article(id="a2", slug="a2", title="A2", file_path="b.md", user_id=TEST_USER_ID))
    await db_session.commit()

    service = ContradictionService()
    first = await service.create_from_finding(
        db_session,
        claim_a="X",
        claim_b="Y",
        article_a_id="a1",
        article_b_id="a2",
        user_id=TEST_USER_ID,
    )
    # Same claims, same pair — should return existing
    second = await service.create_from_finding(
        db_session,
        claim_a="X",
        claim_b="Y",
        article_a_id="a1",
        article_b_id="a2",
        user_id=TEST_USER_ID,
    )
    assert first.id == second.id


@pytest.mark.asyncio
async def test_service_create_from_finding_different_claims_creates_separate(db_session) -> None:
    """create_from_finding creates separate records for different claims between same articles."""
    db_session.add(Article(id="a1", slug="a1", title="A1", file_path="a.md", user_id=TEST_USER_ID))
    db_session.add(Article(id="a2", slug="a2", title="A2", file_path="b.md", user_id=TEST_USER_ID))
    await db_session.commit()

    service = ContradictionService()
    first = await service.create_from_finding(
        db_session,
        claim_a="X",
        claim_b="Y",
        article_a_id="a1",
        article_b_id="a2",
        user_id=TEST_USER_ID,
    )
    # Different claims, same pair — should create a new record
    second = await service.create_from_finding(
        db_session,
        claim_a="X2",
        claim_b="Y2",
        article_a_id="a1",
        article_b_id="a2",
        user_id=TEST_USER_ID,
    )
    assert first.id != second.id


# ---------------------------------------------------------------------------
# API route tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_list_contradictions(client, session_factory) -> None:
    await _seed_articles_and_contradictions(session_factory)

    response = await client.get("/api/wiki/contradictions")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2


@pytest.mark.asyncio
async def test_api_list_contradictions_filter_active(client, session_factory) -> None:
    await _seed_articles_and_contradictions(session_factory)

    response = await client.get("/api/wiki/contradictions", params={"status": "active"})
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["status"] == "active"


@pytest.mark.asyncio
async def test_api_get_single_contradiction(client, session_factory) -> None:
    await _seed_articles_and_contradictions(session_factory)

    response = await client.get("/api/wiki/contradictions/ctr1")
    assert response.status_code == 200
    data = response.json()
    assert data["claim_a"] == "The sky is blue"
    assert data["claim_b"] == "The sky is green"
    assert data["article_a_title"] == "Article Alpha"
    assert data["article_b_title"] == "Article Beta"


@pytest.mark.asyncio
async def test_api_get_contradiction_not_found(client) -> None:
    response = await client.get("/api/wiki/contradictions/nonexistent")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_api_resolve_contradiction(client, session_factory) -> None:
    await _seed_articles_and_contradictions(session_factory)

    response = await client.patch(
        "/api/wiki/contradictions/ctr1",
        json={"status": "resolved", "resolution": "Claim A is correct"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "resolved"
    assert data["resolution"] == "Claim A is correct"
    assert data["resolved_at"] is not None


@pytest.mark.asyncio
async def test_api_dismiss_contradiction(client, session_factory) -> None:
    await _seed_articles_and_contradictions(session_factory)

    response = await client.patch(
        "/api/wiki/contradictions/ctr1",
        json={"status": "dismissed"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "dismissed"


@pytest.mark.asyncio
async def test_api_resolve_nonexistent_contradiction(client) -> None:
    response = await client.patch(
        "/api/wiki/contradictions/nonexistent",
        json={"status": "resolved", "resolution": "test"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Cross-user isolation tests
# ---------------------------------------------------------------------------

OTHER_USER_ID = "other-user"


async def _seed_other_user_contradiction(factory) -> None:
    """Seed articles and a contradiction owned by OTHER_USER_ID."""
    async with factory() as session:
        session.add(
            Article(
                id="other-a1",
                slug="other-art-a",
                title="Other Article A",
                file_path="/tmp/oa.md",
                user_id=OTHER_USER_ID,
            )
        )
        session.add(
            Article(
                id="other-a2",
                slug="other-art-b",
                title="Other Article B",
                file_path="/tmp/ob.md",
                user_id=OTHER_USER_ID,
            )
        )
        session.add(
            Contradiction(
                id="other-ctr1",
                claim_a="Claim X",
                claim_b="Claim Y",
                article_a_id="other-a1",
                article_b_id="other-a2",
                status=ContradictionStatus.ACTIVE,
                user_id=OTHER_USER_ID,
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_api_get_contradiction_cross_user_returns_404(client, session_factory) -> None:
    """GET another user's contradiction returns 404 — not leaked."""
    await _seed_other_user_contradiction(session_factory)

    response = await client.get("/api/wiki/contradictions/other-ctr1")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_api_patch_contradiction_cross_user_returns_404(client, session_factory) -> None:
    """PATCH another user's contradiction returns 404 — not modifiable."""
    await _seed_other_user_contradiction(session_factory)

    response = await client.patch(
        "/api/wiki/contradictions/other-ctr1",
        json={"status": "resolved", "resolution": "hijack attempt"},
    )
    assert response.status_code == 404
