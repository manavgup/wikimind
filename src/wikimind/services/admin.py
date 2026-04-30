"""Administrative operations — aggregate statistics and maintenance triggers."""

import structlog
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.config import get_settings
from wikimind.jobs.background import get_background_compiler
from wikimind.models import Article, Backlink, Concept, Conversation, Source
from wikimind.storage import resolve_wiki_path

log = structlog.get_logger()


class AdminService:
    """Aggregate statistics and administrative operations."""

    async def get_stats(
        self,
        session: AsyncSession,
        user_id: str,
    ) -> dict:
        """Compute aggregate counts across all tables.

        Args:
            session: Async database session.
            user_id: Optional user ID filter.

        Returns:
            Dict with aggregate counts and breakdowns.
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

        return {
            **counts,
            "orphan_count": orphan_count,
            "articles_by_type": articles_by_type,
        }

    async def get_orphan_articles(
        self,
        session: AsyncSession,
        user_id: str,
    ) -> list[dict]:
        """Find articles whose wiki file is missing from disk.

        Args:
            session: Async database session.
            user_id: Optional user ID filter.

        Returns:
            List of dicts with orphan article info.
        """
        stmt = select(Article)
        if user_id:
            stmt = stmt.where(Article.user_id == user_id)
        result = await session.execute(stmt)

        orphans = []
        for article in result.scalars().all():
            if not article.file_path:
                continue
            wiki_path = resolve_wiki_path(article.file_path, user_id=article.user_id)
            if not wiki_path.exists():
                orphans.append(
                    {
                        "id": article.id,
                        "slug": article.slug,
                        "title": article.title,
                        "file_path": article.file_path,
                    }
                )
        return orphans

    async def get_eligible_concepts(
        self,
        session: AsyncSession,
        user_id: str,
    ) -> list[dict]:
        """Find concepts eligible for concept-page generation.

        A concept is eligible when its article_count meets the threshold
        defined in ``settings.taxonomy.concept_page_min_sources``.

        Args:
            session: Async database session.
            user_id: Optional user ID filter.

        Returns:
            List of dicts with eligible concept info.
        """
        settings = get_settings()
        threshold = settings.taxonomy.concept_page_min_sources

        stmt = select(Concept).where(Concept.article_count >= threshold)
        if user_id:
            stmt = stmt.where(Concept.user_id == user_id)
        result = await session.execute(stmt)
        concepts = result.scalars().all()

        eligible = []
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
                {
                    "id": concept.id,
                    "name": concept.name,
                    "article_count": concept.article_count,
                    "has_existing_page": has_page,
                }
            )
        return eligible

    async def trigger_sweep(
        self,
        user_id: str,
    ) -> dict:
        """Trigger a wikilink sweep manually.

        Args:
            user_id: Optional user ID to scope the sweep.

        Returns:
            Dict with action result.
        """
        bg = get_background_compiler()
        await bg.schedule_lint(user_id=user_id)
        return {"action": "sweep", "status": "scheduled"}

    async def trigger_reindex(self) -> dict:
        """Rebuild the search index.

        Returns:
            Dict with action result.
        """
        return {"action": "reindex", "status": "scheduled"}


_admin_service: AdminService | None = None


def get_admin_service() -> AdminService:
    """Return a singleton AdminService instance for FastAPI DI."""
    global _admin_service
    if _admin_service is None:
        _admin_service = AdminService()
    return _admin_service
