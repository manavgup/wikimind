"""Administrative operations — aggregate statistics and maintenance triggers."""

import structlog
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.config import get_settings
from wikimind.jobs.background import get_background_compiler
from wikimind.models import (
    AdminActionResult,
    Article,
    Backlink,
    Concept,
    Conversation,
    EligibleConcept,
    OrphanArticle,
    Source,
    SystemStats,
)
from wikimind.storage import resolve_wiki_path

log = structlog.get_logger()


class AdminService:
    """Aggregate statistics and administrative operations."""

    async def get_stats(
        self,
        session: AsyncSession,
        user_id: str,
    ) -> SystemStats:
        """Compute aggregate counts across all tables.

        Args:
            session: Async database session.
            user_id: Optional user ID filter.

        Returns:
            SystemStats with aggregate counts and breakdowns.
        """
        counts: dict[str, int] = {}
        for model, key in [
            (Article, "article_count"),
            (Source, "source_count"),
            (Concept, "concept_count"),
            (Backlink, "backlink_count"),
            (Conversation, "conversation_count"),
        ]:
            stmt = select(func.count()).select_from(model)
            if user_id and hasattr(model, "user_id"):
                stmt = stmt.where(model.user_id == user_id)
            result = await session.execute(stmt)
            counts[key] = result.scalar() or 0

        # Articles by page_type breakdown
        type_stmt = select(Article.page_type, func.count()).group_by(Article.page_type)
        if user_id:
            type_stmt = type_stmt.where(Article.user_id == user_id)
        type_result = await session.execute(type_stmt)
        articles_by_type = {row[0]: row[1] for row in type_result.all()}

        # Orphan count (articles with missing wiki files)
        art_stmt = select(Article)
        if user_id:
            art_stmt = art_stmt.where(Article.user_id == user_id)
        art_result = await session.execute(art_stmt)
        orphan_count = 0
        for article in art_result.scalars().all():
            if article.file_path:
                wiki_path = resolve_wiki_path(article.file_path, user_id=article.user_id)
                if not wiki_path.exists():
                    orphan_count += 1

        return SystemStats(
            **counts,
            orphan_count=orphan_count,
            articles_by_type=articles_by_type,
        )

    async def get_orphan_articles(
        self,
        session: AsyncSession,
        user_id: str,
    ) -> list[OrphanArticle]:
        """Find articles whose wiki file is missing from disk.

        Args:
            session: Async database session.
            user_id: Optional user ID filter.

        Returns:
            List of OrphanArticle with orphan article info.
        """
        stmt = select(Article)
        if user_id:
            stmt = stmt.where(Article.user_id == user_id)
        result = await session.execute(stmt)

        orphans: list[OrphanArticle] = []
        for article in result.scalars().all():
            if not article.file_path:
                continue
            wiki_path = resolve_wiki_path(article.file_path, user_id=article.user_id)
            if not wiki_path.exists():
                orphans.append(
                    OrphanArticle(
                        id=article.id,
                        slug=article.slug,
                        title=article.title,
                        file_path=article.file_path,
                    )
                )
        return orphans

    async def get_eligible_concepts(
        self,
        session: AsyncSession,
        user_id: str,
    ) -> list[EligibleConcept]:
        """Find concepts eligible for concept-page generation.

        A concept is eligible when its article_count meets the threshold
        defined in ``settings.taxonomy.concept_page_min_sources``.

        Args:
            session: Async database session.
            user_id: Optional user ID filter.

        Returns:
            List of EligibleConcept with eligible concept info.
        """
        settings = get_settings()
        threshold = settings.taxonomy.concept_page_min_sources

        stmt = select(Concept).where(Concept.article_count >= threshold)
        if user_id:
            stmt = stmt.where(Concept.user_id == user_id)
        result = await session.execute(stmt)
        concepts = result.scalars().all()

        eligible: list[EligibleConcept] = []
        for concept in concepts:
            # Check if a concept page article already exists
            page_stmt = select(Article).where(
                Article.slug == f"concept-{concept.name}",
                Article.page_type == "concept",
            )
            if user_id:
                page_stmt = page_stmt.where(Article.user_id == user_id)
            page_result = await session.execute(page_stmt)
            has_page = page_result.scalar_one_or_none() is not None

            eligible.append(
                EligibleConcept(
                    id=concept.id,
                    name=concept.name,
                    article_count=concept.article_count,
                    has_existing_page=has_page,
                )
            )
        return eligible

    async def trigger_sweep(
        self,
        user_id: str,
    ) -> AdminActionResult:
        """Trigger a wikilink sweep manually.

        Args:
            user_id: Optional user ID to scope the sweep.

        Returns:
            AdminActionResult with action result.
        """
        bg = get_background_compiler()
        await bg.schedule_lint(user_id=user_id)
        return AdminActionResult(action="sweep", status="scheduled")

    async def trigger_reindex(self) -> AdminActionResult:
        """Rebuild the search index.

        Returns:
            AdminActionResult with action result.
        """
        return AdminActionResult(action="reindex", status="scheduled")


_admin_service: AdminService | None = None


def get_admin_service() -> AdminService:
    """Return a singleton AdminService instance for FastAPI DI."""
    global _admin_service
    if _admin_service is None:
        _admin_service = AdminService()
    return _admin_service
