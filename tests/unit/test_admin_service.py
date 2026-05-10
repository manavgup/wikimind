"""Tests for services/admin.py — aggregate stats and maintenance triggers."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

from tests.conftest import TEST_USER_ID
from wikimind.models import Article, Concept, IngestStatus, PageType, Source, SourceType, User
from wikimind.services import admin as admin_mod
from wikimind.services.admin import AdminService, get_admin_service

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession


def test_admin_service_singleton() -> None:
    admin_mod._admin_service = None
    a = get_admin_service()
    b = get_admin_service()
    assert a is b
    admin_mod._admin_service = None


async def test_get_stats_empty(db_session: AsyncSession) -> None:
    service = AdminService()
    stats = await service.get_stats(db_session)
    assert stats.article_count == 0
    assert stats.source_count == 0
    assert stats.total_users == 0
    assert stats.total_sources == 0
    assert stats.total_articles == 0
    assert stats.total_compiled_claims == 0


async def test_get_stats_with_data(db_session: AsyncSession) -> None:
    db_session.add(
        User(
            email="admin@test.com",
            auth_provider="google",
            auth_provider_id="123",
            id=TEST_USER_ID,
            is_admin=True,
        )
    )
    for i in range(3):
        db_session.add(Source(source_type=SourceType.TEXT, title=f"src-{i}", user_id=TEST_USER_ID))
    for i in range(2):
        db_session.add(
            Article(
                slug=f"art-{i}",
                title=f"Article {i}",
                file_path=f"wiki/art-{i}.md",
                page_type=PageType.SOURCE,
                user_id=TEST_USER_ID,
            )
        )
    db_session.add(Concept(name="test-concept", user_id=TEST_USER_ID))
    await db_session.commit()
    service = AdminService()
    stats = await service.get_stats(db_session)
    assert stats.source_count == 3
    assert stats.total_sources == 3
    assert stats.article_count == 2
    assert stats.total_articles == 2
    assert stats.concept_count == 1
    assert stats.total_users == 1


async def test_get_stats_orphan_detection(db_session: AsyncSession) -> None:
    db_session.add(
        Article(
            slug="orphan",
            title="Orphan",
            file_path="/nonexistent/path.md",
            page_type=PageType.SOURCE,
            user_id=TEST_USER_ID,
        )
    )
    await db_session.commit()
    service = AdminService()
    mock_storage = AsyncMock()
    mock_storage.exists = AsyncMock(return_value=False)
    with patch.object(admin_mod, "get_wiki_storage", return_value=mock_storage):
        stats = await service.get_stats(db_session)
    assert stats.orphan_count == 1


async def test_get_orphan_articles_none(db_session: AsyncSession) -> None:
    service = AdminService()
    orphans = await service.get_orphan_articles(db_session)
    assert orphans == []


async def test_get_orphan_articles_with_missing_file(db_session: AsyncSession) -> None:
    db_session.add(
        Article(
            slug="missing",
            title="Missing",
            file_path="/fake/missing.md",
            page_type=PageType.SOURCE,
            user_id=TEST_USER_ID,
        )
    )
    await db_session.commit()
    service = AdminService()
    mock_storage = AsyncMock()
    mock_storage.exists = AsyncMock(return_value=False)
    with patch.object(admin_mod, "get_wiki_storage", return_value=mock_storage):
        orphans = await service.get_orphan_articles(db_session)
    assert len(orphans) == 1


async def test_get_eligible_concepts_none(db_session: AsyncSession) -> None:
    service = AdminService()
    eligible = await service.get_eligible_concepts(db_session)
    assert eligible == []


async def test_get_eligible_concepts_with_data(db_session: AsyncSession) -> None:
    db_session.add(Concept(name="popular", article_count=10, user_id=TEST_USER_ID))
    await db_session.commit()
    service = AdminService()
    eligible = await service.get_eligible_concepts(db_session)
    assert len(eligible) == 1


async def test_trigger_sweep() -> None:
    service = AdminService()
    mock_bg = AsyncMock()
    mock_bg.schedule_lint = AsyncMock()
    with patch.object(admin_mod, "get_background_compiler", return_value=mock_bg):
        result = await service.trigger_sweep(user_id=TEST_USER_ID)
    assert result.action == "sweep"


async def test_trigger_reindex() -> None:
    service = AdminService()
    result = await service.trigger_reindex()
    assert result.action == "reindex"


async def test_get_stats_compilation_success_rate(db_session: AsyncSession) -> None:
    """Compilation success rate = compiled / (compiled + failed)."""
    for i in range(7):
        db_session.add(
            Source(
                source_type=SourceType.URL,
                title=f"compiled-{i}",
                user_id=TEST_USER_ID,
                status="compiled",
            )
        )
    for i in range(3):
        db_session.add(
            Source(
                source_type=SourceType.URL,
                title=f"failed-{i}",
                user_id=TEST_USER_ID,
                status="failed",
            )
        )
    await db_session.commit()
    service = AdminService()
    stats = await service.get_stats(db_session)
    assert stats.compilation_success_rate is not None
    assert abs(stats.compilation_success_rate - 0.7) < 0.01


async def test_get_stats_stuck_sources_count(db_session: AsyncSession) -> None:
    """stuck_sources field reflects count of stuck sources."""
    service = AdminService()
    stats = await service.get_stats(db_session)
    assert stats.stuck_sources == 0


async def test_retry_stuck_source_rejects_zombie(db_session: AsyncSession) -> None:
    """Sources without a file_path should not be requeued."""
    source = Source(
        source_type=SourceType.URL,
        title="zombie",
        user_id=TEST_USER_ID,
        status=IngestStatus.PROCESSING,
        file_path=None,
    )
    db_session.add(source)
    await db_session.commit()

    service = AdminService()
    result = await service.retry_stuck_source(db_session, str(source.id), TEST_USER_ID)
    assert result.action == "retry_stuck"
    assert result.status == "not_retryable"
