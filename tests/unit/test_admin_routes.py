"""Tests for admin route access control (require_admin dependency)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from wikimind.api.deps import ANONYMOUS_USER_ID, require_admin
from wikimind.models import User

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlmodel.ext.asyncio.session import AsyncSession


async def test_admin_stats_accessible_without_auth(client: AsyncClient) -> None:
    """In single-user mode (auth disabled), admin endpoints are accessible."""
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
    from wikimind.config import get_settings

    user = User(
        email="regular@test.com",
        auth_provider="google",
        auth_provider_id="456",
        is_admin=False,
    )
    db_session.add(user)
    await db_session.commit()

    settings = get_settings()
    # Temporarily enable auth to test the guard
    original = settings.auth.enabled
    settings.auth.enabled = True
    try:
        with pytest.raises(Exception) as exc_info:
            await require_admin(user_id=user.id, session=db_session)
        assert exc_info.value.status_code == 403  # type: ignore[attr-defined]
    finally:
        settings.auth.enabled = original


async def test_require_admin_allows_admin(db_session: AsyncSession) -> None:
    """require_admin returns user_id when user is admin."""
    from wikimind.config import get_settings

    user = User(
        email="admin@test.com",
        auth_provider="google",
        auth_provider_id="789",
        is_admin=True,
    )
    db_session.add(user)
    await db_session.commit()

    settings = get_settings()
    original = settings.auth.enabled
    settings.auth.enabled = True
    try:
        result = await require_admin(user_id=user.id, session=db_session)
        assert result == user.id
    finally:
        settings.auth.enabled = original


async def test_require_admin_rejects_anonymous(db_session: AsyncSession) -> None:
    """require_admin raises 403 for anonymous user when auth is enabled."""
    from wikimind.config import get_settings

    settings = get_settings()
    original = settings.auth.enabled
    settings.auth.enabled = True
    try:
        with pytest.raises(Exception) as exc_info:
            await require_admin(user_id=ANONYMOUS_USER_ID, session=db_session)
        assert exc_info.value.status_code == 403  # type: ignore[attr-defined]
    finally:
        settings.auth.enabled = original
