"""Integration tests for multi-user data isolation.

Verifies that data owned by user A is invisible and inaccessible to user B
across all major service-layer operations: sources, articles, conversations,
lint reports, and concepts.

Uses real in-memory SQLite sessions (no mocks of the DB layer) to exercise
the actual WHERE clauses that enforce user_id scoping.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlmodel import select

from wikimind.errors import NotFoundError
from wikimind.models import (
    Article,
    Concept,
    Conversation,
    ForkRequest,
    LintReport,
    LintReportStatus,
    Query,
    Source,
    SourceType,
)
from wikimind.services.ingest import IngestService
from wikimind.services.linter import LinterService
from wikimind.services.query import QueryService
from wikimind.services.taxonomy import upsert_concepts
from wikimind.services.wiki import WikiService

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession

# ---------------------------------------------------------------------------
# Test user constants
# ---------------------------------------------------------------------------

USER_ALICE = "user-alice"
USER_BOB = "user-bob"


# ---------------------------------------------------------------------------
# Helpers — seed data directly via the ORM (service calls require LLM mocking)
# ---------------------------------------------------------------------------


async def _seed_source(
    session: AsyncSession,
    user_id: str,
    title: str = "Test Source",
) -> Source:
    """Create and persist a Source row owned by ``user_id``."""
    source = Source(
        user_id=user_id,
        source_type=SourceType.TEXT,
        title=title,
        status="compiled",
        file_path=f"raw/{user_id}/test.txt",
    )
    session.add(source)
    await session.commit()
    await session.refresh(source)
    return source


async def _seed_article(
    session: AsyncSession,
    user_id: str,
    title: str = "Test Article",
    slug: str | None = None,
    tmp_path: Path | None = None,
) -> Article:
    """Create and persist an Article row owned by ``user_id``."""
    effective_slug = slug or title.lower().replace(" ", "-")
    file_path = f"articles/{effective_slug}.md"
    # Write a real file if tmp_path provided (for content reads)
    if tmp_path:
        wiki_dir = tmp_path / "wiki" / user_id / "articles"
        wiki_dir.mkdir(parents=True, exist_ok=True)
        (wiki_dir / f"{effective_slug}.md").write_text(
            f"# {title}\n\nContent for {user_id}.",
            encoding="utf-8",
        )
    article = Article(
        user_id=user_id,
        slug=effective_slug,
        title=title,
        file_path=file_path,
    )
    session.add(article)
    await session.commit()
    await session.refresh(article)
    return article


async def _seed_conversation(
    session: AsyncSession,
    user_id: str,
    title: str = "Test Conversation",
) -> Conversation:
    """Create a Conversation and a Query turn owned by ``user_id``."""
    conv = Conversation(user_id=user_id, title=title)
    session.add(conv)
    await session.commit()
    await session.refresh(conv)

    query = Query(
        user_id=user_id,
        question="What is testing?",
        answer="Testing verifies correctness.",
        conversation_id=conv.id,
        turn_index=0,
    )
    session.add(query)
    await session.commit()
    return conv


async def _seed_lint_report(
    session: AsyncSession,
    user_id: str,
) -> LintReport:
    """Create a LintReport row owned by ``user_id``."""
    report = LintReport(
        user_id=user_id,
        status=LintReportStatus.COMPLETE,
        article_count=5,
        total_findings=2,
    )
    session.add(report)
    await session.commit()
    await session.refresh(report)
    return report


# ---------------------------------------------------------------------------
# Source isolation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSourceIsolation:
    """User A's sources are invisible to User B."""

    async def test_list_sources_excludes_other_user(self, db_session: AsyncSession) -> None:
        """IngestService.list_sources only returns the requesting user's sources."""
        await _seed_source(db_session, USER_ALICE, title="Alice Source")
        await _seed_source(db_session, USER_BOB, title="Bob Source")

        svc = IngestService()
        alice_sources = await svc.list_sources(db_session, user_id=USER_ALICE)
        bob_sources = await svc.list_sources(db_session, user_id=USER_BOB)

        assert len(alice_sources) == 1
        assert alice_sources[0].title == "Alice Source"
        assert len(bob_sources) == 1
        assert bob_sources[0].title == "Bob Source"

    async def test_get_source_denies_other_user(self, db_session: AsyncSession) -> None:
        """IngestService.get_source raises NotFoundError for another user's source."""
        alice_source = await _seed_source(db_session, USER_ALICE)

        svc = IngestService()
        with pytest.raises(NotFoundError):
            await svc.get_source(alice_source.id, db_session, user_id=USER_BOB)

    async def test_delete_source_denies_other_user(self, db_session: AsyncSession) -> None:
        """IngestService.delete_source raises NotFoundError for another user's source."""
        alice_source = await _seed_source(db_session, USER_ALICE)

        svc = IngestService()
        with pytest.raises(NotFoundError):
            await svc.delete_source(alice_source.id, db_session, user_id=USER_BOB)

    async def test_own_source_accessible(self, db_session: AsyncSession) -> None:
        """The owning user can still access their own source."""
        alice_source = await _seed_source(db_session, USER_ALICE)

        svc = IngestService()
        retrieved = await svc.get_source(alice_source.id, db_session, user_id=USER_ALICE)
        assert retrieved.id == alice_source.id


# ---------------------------------------------------------------------------
# Article / wiki isolation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestArticleIsolation:
    """User A's articles are invisible to User B."""

    async def test_list_articles_excludes_other_user(self, db_session: AsyncSession) -> None:
        """WikiService.list_articles only returns the requesting user's articles."""
        await _seed_article(db_session, USER_ALICE, title="Alice Art")
        await _seed_article(db_session, USER_BOB, title="Bob Art")

        svc = WikiService()
        alice_articles = await svc.list_articles(db_session, user_id=USER_ALICE)
        bob_articles = await svc.list_articles(db_session, user_id=USER_BOB)

        assert len(alice_articles) == 1
        assert alice_articles[0].title == "Alice Art"
        assert len(bob_articles) == 1
        assert bob_articles[0].title == "Bob Art"

    async def test_get_article_by_id_denies_other_user(self, db_session: AsyncSession) -> None:
        """WikiService.get_article raises NotFoundError for another user's article."""
        alice_art = await _seed_article(db_session, USER_ALICE, title="Private Art")

        svc = WikiService()
        with pytest.raises(NotFoundError):
            await svc.get_article(alice_art.id, db_session, user_id=USER_BOB)

    async def test_get_article_by_slug_denies_other_user(self, db_session: AsyncSession) -> None:
        """WikiService.get_article by slug raises NotFoundError for another user."""
        await _seed_article(db_session, USER_ALICE, title="Secret", slug="secret")

        svc = WikiService()
        with pytest.raises(NotFoundError):
            await svc.get_article("secret", db_session, user_id=USER_BOB)

    async def test_own_article_accessible(self, db_session: AsyncSession, tmp_path: Path) -> None:
        """The owning user can retrieve their own article by ID."""
        alice_art = await _seed_article(db_session, USER_ALICE, title="My Art", tmp_path=tmp_path)

        svc = WikiService()
        result = await svc.get_article(alice_art.id, db_session, user_id=USER_ALICE)
        assert result.title == "My Art"


# ---------------------------------------------------------------------------
# Conversation isolation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestConversationIsolation:
    """User A's conversations are invisible to User B."""

    async def test_list_conversations_excludes_other_user(self, db_session: AsyncSession) -> None:
        """QueryService.list_conversations only returns the requesting user's data."""
        await _seed_conversation(db_session, USER_ALICE, title="Alice Conv")
        await _seed_conversation(db_session, USER_BOB, title="Bob Conv")

        svc = QueryService()
        alice_convs = await svc.list_conversations(db_session, user_id=USER_ALICE)
        bob_convs = await svc.list_conversations(db_session, user_id=USER_BOB)

        assert len(alice_convs) == 1
        assert alice_convs[0].title == "Alice Conv"
        assert len(bob_convs) == 1
        assert bob_convs[0].title == "Bob Conv"

    async def test_get_conversation_denies_other_user(self, db_session: AsyncSession) -> None:
        """QueryService.get_conversation raises NotFoundError for another user."""
        alice_conv = await _seed_conversation(db_session, USER_ALICE)

        svc = QueryService()
        with pytest.raises(NotFoundError):
            await svc.get_conversation(alice_conv.id, db_session, user_id=USER_BOB)

    async def test_fork_conversation_denies_other_user(self, db_session: AsyncSession) -> None:
        """QueryService.fork_conversation raises NotFoundError for another user."""
        alice_conv = await _seed_conversation(db_session, USER_ALICE)

        svc = QueryService()
        fork_req = ForkRequest(turn_index=0, new_question="Why?")
        with pytest.raises(NotFoundError):
            await svc.fork_conversation(alice_conv.id, fork_req, db_session, user_id=USER_BOB)

    async def test_file_back_conversation_denies_other_user(self, db_session: AsyncSession) -> None:
        """QueryService.file_back_conversation raises NotFoundError for another user."""
        alice_conv = await _seed_conversation(db_session, USER_ALICE)

        svc = QueryService()
        with pytest.raises(NotFoundError):
            await svc.file_back_conversation(alice_conv.id, db_session, user_id=USER_BOB)

    async def test_own_conversation_accessible(self, db_session: AsyncSession) -> None:
        """The owning user can retrieve their own conversation."""
        alice_conv = await _seed_conversation(db_session, USER_ALICE)

        svc = QueryService()
        detail = await svc.get_conversation(alice_conv.id, db_session, user_id=USER_ALICE)
        assert detail.conversation.id == alice_conv.id

    async def test_query_history_excludes_other_user(self, db_session: AsyncSession) -> None:
        """QueryService.query_history only returns the requesting user's queries."""
        await _seed_conversation(db_session, USER_ALICE, title="Alice Q")
        await _seed_conversation(db_session, USER_BOB, title="Bob Q")

        svc = QueryService()
        alice_history = await svc.query_history(db_session, user_id=USER_ALICE)
        bob_history = await svc.query_history(db_session, user_id=USER_BOB)

        assert len(alice_history) == 1
        assert alice_history[0].user_id == USER_ALICE
        assert len(bob_history) == 1
        assert bob_history[0].user_id == USER_BOB


# ---------------------------------------------------------------------------
# Lint report isolation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestLintReportIsolation:
    """User A's lint reports are invisible to User B."""

    async def test_list_reports_excludes_other_user(self, db_session: AsyncSession) -> None:
        """LinterService.list_reports only returns the requesting user's reports."""
        await _seed_lint_report(db_session, USER_ALICE)
        await _seed_lint_report(db_session, USER_BOB)

        svc = LinterService()
        alice_reports = await svc.list_reports(db_session, user_id=USER_ALICE)
        bob_reports = await svc.list_reports(db_session, user_id=USER_BOB)

        assert len(alice_reports) == 1
        assert alice_reports[0].user_id == USER_ALICE
        assert len(bob_reports) == 1
        assert bob_reports[0].user_id == USER_BOB

    async def test_get_report_denies_other_user(self, db_session: AsyncSession) -> None:
        """LinterService.get_report raises NotFoundError for another user's report."""
        alice_report = await _seed_lint_report(db_session, USER_ALICE)

        svc = LinterService()
        with pytest.raises(NotFoundError):
            await svc.get_report(db_session, alice_report.id, user_id=USER_BOB)

    async def test_own_report_accessible(self, db_session: AsyncSession) -> None:
        """The owning user can retrieve their own lint report."""
        alice_report = await _seed_lint_report(db_session, USER_ALICE)

        svc = LinterService()
        detail = await svc.get_report(db_session, alice_report.id, user_id=USER_ALICE)
        assert detail.report.id == alice_report.id


# ---------------------------------------------------------------------------
# Concept isolation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestConceptIsolation:
    """User A's concepts are invisible to User B."""

    async def test_upsert_concepts_scoped_by_user(self, db_session: AsyncSession) -> None:
        """Same concept name creates separate rows per user."""
        alice_concepts = await upsert_concepts(["Machine Learning"], db_session, user_id=USER_ALICE)
        bob_concepts = await upsert_concepts(["Machine Learning"], db_session, user_id=USER_BOB)

        assert len(alice_concepts) == 1
        assert len(bob_concepts) == 1
        assert alice_concepts[0].id != bob_concepts[0].id
        assert alice_concepts[0].user_id == USER_ALICE
        assert bob_concepts[0].user_id == USER_BOB

    async def test_concept_list_filtered_by_user(self, db_session: AsyncSession) -> None:
        """Direct DB query for concepts returns only the specified user's data."""
        await upsert_concepts(["Python", "Rust"], db_session, user_id=USER_ALICE)
        await upsert_concepts(["Go", "Java"], db_session, user_id=USER_BOB)

        alice_result = await db_session.execute(select(Concept).where(Concept.user_id == USER_ALICE))
        alice_names = {c.name for c in alice_result.scalars().all()}

        bob_result = await db_session.execute(select(Concept).where(Concept.user_id == USER_BOB))
        bob_names = {c.name for c in bob_result.scalars().all()}

        assert "python" in alice_names
        assert "rust" in alice_names
        assert "go" not in alice_names
        assert "java" not in alice_names

        assert "go" in bob_names
        assert "java" in bob_names
        assert "python" not in bob_names
        assert "rust" not in bob_names

    async def test_upsert_idempotent_within_user_not_across(self, db_session: AsyncSession) -> None:
        """Upserting same concept is idempotent within user but distinct across users."""
        first = await upsert_concepts(["AI"], db_session, user_id=USER_ALICE)
        second = await upsert_concepts(["AI"], db_session, user_id=USER_ALICE)
        other = await upsert_concepts(["AI"], db_session, user_id=USER_BOB)

        assert first[0].id == second[0].id
        assert first[0].id != other[0].id


# ---------------------------------------------------------------------------
# Cross-cutting: no data leakage in empty-state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestEmptyStateIsolation:
    """A new user sees zero data even when other users have data."""

    async def test_new_user_sees_no_sources(self, db_session: AsyncSession) -> None:
        """A user with no data sees an empty source list."""
        await _seed_source(db_session, USER_ALICE)

        svc = IngestService()
        bob_sources = await svc.list_sources(db_session, user_id=USER_BOB)
        assert bob_sources == []

    async def test_new_user_sees_no_articles(self, db_session: AsyncSession) -> None:
        """A user with no data sees an empty article list."""
        await _seed_article(db_session, USER_ALICE)

        svc = WikiService()
        bob_articles = await svc.list_articles(db_session, user_id=USER_BOB)
        assert bob_articles == []

    async def test_new_user_sees_no_conversations(self, db_session: AsyncSession) -> None:
        """A user with no data sees an empty conversation list."""
        await _seed_conversation(db_session, USER_ALICE)

        svc = QueryService()
        bob_convs = await svc.list_conversations(db_session, user_id=USER_BOB)
        assert bob_convs == []

    async def test_new_user_sees_no_lint_reports(self, db_session: AsyncSession) -> None:
        """A user with no data sees an empty lint report list."""
        await _seed_lint_report(db_session, USER_ALICE)

        svc = LinterService()
        bob_reports = await svc.list_reports(db_session, user_id=USER_BOB)
        assert bob_reports == []

    async def test_new_user_sees_no_query_history(self, db_session: AsyncSession) -> None:
        """A user with no data sees an empty query history."""
        await _seed_conversation(db_session, USER_ALICE)

        svc = QueryService()
        bob_history = await svc.query_history(db_session, user_id=USER_BOB)
        assert bob_history == []
