"""Tests for admin route access control (require_admin dependency)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from wikimind.api.deps import require_admin
from wikimind.models import User

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlmodel.ext.asyncio.session import AsyncSession


async def test_admin_stats_accessible(client: AsyncClient) -> None:
    """Admin endpoints are accessible when authenticated."""
    resp = await client.get("/api/admin/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_users" in data
    assert "total_sources" in data
    assert "total_articles" in data
    assert "compilation_success_rate" in data


async def test_admin_stats_returns_system_wide_metrics(client: AsyncClient) -> None:
    """Stats endpoint returns system-wide fields."""
    resp = await client.get("/api/admin/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_users" in data
    assert "total_sources" in data
    assert "total_articles" in data
    assert "total_compiled_claims" in data
    assert "stuck_sources" in data
    assert "sources_by_status" in data


async def test_require_admin_rejects_non_admin(db_session: AsyncSession) -> None:
    """require_admin raises 403 when user is not admin."""
    user = User(
        email="regular@test.com",
        auth_provider="google",
        auth_provider_id="456",
        is_admin=False,
    )
    db_session.add(user)
    await db_session.commit()

    with pytest.raises(Exception) as exc_info:
        await require_admin(user_id=user.id, session=db_session)
    assert exc_info.value.status_code == 403  # type: ignore[attr-defined]


async def test_require_admin_allows_admin(db_session: AsyncSession) -> None:
    """require_admin returns user_id when user is admin."""
    user = User(
        email="admin@test.com",
        auth_provider="google",
        auth_provider_id="789",
        is_admin=True,
    )
    db_session.add(user)
    await db_session.commit()

    result = await require_admin(user_id=user.id, session=db_session)
    assert result == user.id


async def test_require_admin_rejects_unknown_user(db_session: AsyncSession) -> None:
    """require_admin raises 403 for a user_id that does not exist in the DB."""
    with pytest.raises(Exception) as exc_info:
        await require_admin(user_id="nonexistent-user", session=db_session)
    assert exc_info.value.status_code == 403  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Per-user admin endpoints (issue #772)
# ---------------------------------------------------------------------------


async def test_admin_users_list(client: AsyncClient) -> None:
    """GET /api/admin/users returns a list of user summaries."""
    resp = await client.get("/api/admin/users")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    # The test fixture seeds a single admin user
    assert len(data) >= 1
    first = data[0]
    assert "id" in first
    assert "email" in first
    assert "article_count" in first
    assert "source_count" in first
    assert "total_cost_usd" in first


async def test_admin_user_detail(client: AsyncClient) -> None:
    """GET /api/admin/users/{user_id} returns detailed stats."""
    # First get the users list to find the test user's ID
    resp = await client.get("/api/admin/users")
    assert resp.status_code == 200
    users = resp.json()
    assert len(users) >= 1
    user_id = users[0]["id"]

    resp = await client.get(f"/api/admin/users/{user_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == user_id
    assert "articles_by_type" in data
    assert "sources_by_status" in data
    assert "cost_by_provider" in data
    assert "recent_sources" in data


async def test_admin_user_detail_not_found(client: AsyncClient) -> None:
    """GET /api/admin/users/{user_id} returns 404 for unknown user."""
    resp = await client.get("/api/admin/users/nonexistent-user-id")
    assert resp.status_code == 404
