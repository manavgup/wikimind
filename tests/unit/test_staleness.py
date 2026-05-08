"""Tests for knowledge staleness detection and decay (issue #425)."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select

from tests.conftest import TEST_USER_ID
from wikimind._datetime import utcnow_naive
from wikimind.api.deps import ANONYMOUS_USER_ID
from wikimind.engine.confidence import compute_staleness
from wikimind.errors import NotFoundError
from wikimind.models import (
    Article,
    ReinforcementEvent,
    User,
)
from wikimind.services.wiki import WikiService

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession


# ---------------------------------------------------------------------------
# Unit tests — compute_staleness (pure function, no DB)
# ---------------------------------------------------------------------------


class TestComputeStaleness:
    """Test the compute_staleness pure function."""

    def test_zero_days_returns_zero(self):
        assert compute_staleness(0.0) == 0.0

    def test_negative_days_treated_as_zero(self):
        assert compute_staleness(-10.0) == 0.0

    def test_250_days_about_half(self):
        score = compute_staleness(250.0)
        assert score == pytest.approx(0.5, abs=0.01)

    def test_500_days_is_one(self):
        score = compute_staleness(500.0)
        assert score == 1.0

    def test_1000_days_clamped_to_one(self):
        score = compute_staleness(1000.0)
        assert score == 1.0

    def test_custom_decay_rate(self):
        # decay_rate=0.01: 50 days -> 0.5
        score = compute_staleness(50.0, decay_rate=0.01)
        assert score == pytest.approx(0.5, abs=0.01)

    def test_one_day(self):
        score = compute_staleness(1.0)
        assert score == pytest.approx(0.002, abs=0.001)

    def test_100_days(self):
        score = compute_staleness(100.0)
        assert score == pytest.approx(0.2, abs=0.01)


# ---------------------------------------------------------------------------
# Integration tests — reinforcement events on recompile
# ---------------------------------------------------------------------------


async def _create_test_user(session: AsyncSession) -> None:
    """Ensure the test user exists."""
    existing = await session.get(User, TEST_USER_ID)
    if existing is None:
        session.add(
            User(
                id=TEST_USER_ID,
                email="test@example.com",
                auth_provider="test",
                auth_provider_id="test",
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_refresh_creates_reinforcement_event(db_session: AsyncSession):
    """POST /wiki/articles/{slug}/refresh should create a manual_refresh event."""
    await _create_test_user(db_session)

    # Create an article with an old last_reinforced_at
    old_time = utcnow_naive() - timedelta(days=300)
    article = Article(
        slug="test-staleness",
        title="Test Staleness",
        file_path="test/test-staleness.md",
        user_id=TEST_USER_ID,
        last_reinforced_at=old_time,
    )
    db_session.add(article)
    await db_session.commit()
    await db_session.refresh(article)

    # Manually refresh via service
    service = WikiService()
    updated = await service.refresh_article(article.slug, db_session, user_id=TEST_USER_ID)

    # Verify last_reinforced_at was updated
    assert updated.last_reinforced_at is not None
    assert updated.last_reinforced_at > old_time

    # Verify a ReinforcementEvent was created
    result = await db_session.execute(select(ReinforcementEvent).where(ReinforcementEvent.article_id == article.id))
    events = list(result.scalars().all())
    assert len(events) == 1
    assert events[0].event_type == "manual_refresh"
    assert events[0].user_id == TEST_USER_ID


@pytest.mark.asyncio
async def test_refresh_not_found_raises(db_session: AsyncSession):
    """Refreshing a non-existent article should raise NotFoundError."""
    await _create_test_user(db_session)

    service = WikiService()
    with pytest.raises(NotFoundError):
        await service.refresh_article("nonexistent-slug", db_session, user_id=TEST_USER_ID)


# ---------------------------------------------------------------------------
# API route tests — refresh endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_endpoint(client, async_engine):
    """POST /wiki/articles/{slug}/refresh should return 200 with staleness."""
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    old_time = utcnow_naive() - timedelta(days=300)

    async with factory() as session:
        session.add(
            Article(
                slug="api-refresh-test",
                title="API Refresh Test",
                file_path="test/api-refresh-test.md",
                user_id=ANONYMOUS_USER_ID,
                last_reinforced_at=old_time,
            )
        )
        await session.commit()

    response = await client.post("/wiki/articles/api-refresh-test/refresh")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "refreshed"
    # After refresh, staleness should be near 0
    assert data["staleness_score"] < 0.01


@pytest.mark.asyncio
async def test_refresh_endpoint_not_found(client):
    """POST /wiki/articles/{slug}/refresh for missing article returns 404."""
    response = await client.post("/wiki/articles/does-not-exist/refresh")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# API response includes staleness_score
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_articles_includes_staleness(client, async_engine):
    """GET /wiki/articles should include staleness_score in each response."""
    factory = async_sessionmaker(async_engine, expire_on_commit=False)

    async with factory() as session:
        session.add(
            Article(
                slug="staleness-list-test",
                title="Staleness List Test",
                file_path="test/staleness-list.md",
                user_id=ANONYMOUS_USER_ID,
                last_reinforced_at=utcnow_naive(),
            )
        )
        await session.commit()

    response = await client.get("/wiki/articles")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    # Find our article
    found = [a for a in data if a["slug"] == "staleness-list-test"]
    assert len(found) == 1
    assert "staleness_score" in found[0]
    assert found[0]["staleness_score"] is not None
    # Just created, so should be near 0
    assert found[0]["staleness_score"] < 0.01
