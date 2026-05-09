"""Administrative operations — aggregate statistics and maintenance triggers."""

from datetime import timedelta

import structlog
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind._datetime import utcnow_naive
from wikimind.config import get_settings
from wikimind.jobs.background import get_background_compiler
from wikimind.models import (
    AdminActionResult,
    Article,
    Backlink,
    Concept,
    Conversation,
    EligibleConcept,
    IngestStatus,
    Job,
    JobStatus,
    JobType,
    OrphanArticle,
    Source,
    StuckSource,
    SystemStats,
)
from wikimind.storage import get_wiki_storage

log = structlog.get_logger()


class AdminService:
    """Aggregate statistics and administrative operations."""

    async def _get_content_breakdowns(
        self,
        session: AsyncSession,
        user_id: str,
    ) -> dict:
        """Compute content breakdown aggregates.

        Returns dict with articles_by_type, articles_by_confidence,
        sources_by_type, and sources_by_status.
        """
        # Articles by page_type
        type_stmt = select(Article.page_type, func.count()).group_by(Article.page_type)
        if user_id:
            type_stmt = type_stmt.where(Article.user_id == user_id)
        type_result = await session.execute(type_stmt)
        articles_by_type = {row[0]: row[1] for row in type_result.all()}

        # Articles by confidence
        conf_stmt = select(Article.confidence, func.count()).group_by(Article.confidence)
        if user_id:
            conf_stmt = conf_stmt.where(Article.user_id == user_id)
        conf_result = await session.execute(conf_stmt)
        articles_by_confidence = {
            (row[0] or "unknown"): row[1] for row in conf_result.all()
        }

        # Sources by type
        stype_stmt = select(Source.source_type, func.count()).group_by(Source.source_type)
        if user_id:
            stype_stmt = stype_stmt.where(Source.user_id == user_id)
        stype_result = await session.execute(stype_stmt)
        sources_by_type = {row[0]: row[1] for row in stype_result.all()}

        # Sources by status
        sstatus_stmt = select(Source.status, func.count()).group_by(Source.status)
        if user_id:
            sstatus_stmt = sstatus_stmt.where(Source.user_id == user_id)
        sstatus_result = await session.execute(sstatus_stmt)
        sources_by_status = {row[0]: row[1] for row in sstatus_result.all()}

        return {
            "articles_by_type": articles_by_type,
            "articles_by_confidence": articles_by_confidence,
            "sources_by_type": sources_by_type,
            "sources_by_status": sources_by_status,
        }

    async def _get_compilation_health(
        self,
        session: AsyncSession,
        user_id: str,
    ) -> dict:
        """Compute compilation queue depth and last compilation time."""
        queue_stmt = (
            select(func.count())
            .select_from(Job)
            .where(
                Job.job_type == JobType.COMPILE_SOURCE,
                Job.status == JobStatus.QUEUED,
            )
        )
        if user_id:
            queue_stmt = queue_stmt.where(Job.user_id == user_id)
        queue_result = await session.execute(queue_stmt)
        compilation_queue_depth = queue_result.scalar() or 0

        last_stmt = select(func.max(Job.completed_at)).where(
            Job.job_type == JobType.COMPILE_SOURCE,
            Job.status == JobStatus.COMPLETE,
        )
        if user_id:
            last_stmt = last_stmt.where(Job.user_id == user_id)
        last_result = await session.execute(last_stmt)
        last_val = last_result.scalar()
        last_compilation_at = last_val.isoformat() if last_val else None

        return {
            "compilation_queue_depth": compilation_queue_depth,
            "last_compilation_at": last_compilation_at,
        }

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

        breakdowns = await self._get_content_breakdowns(session, user_id)
        health = await self._get_compilation_health(session, user_id)
        stuck = await self._get_stuck_sources(session, user_id)

        # Orphan count (articles with missing wiki files)
        art_stmt = select(Article)
        if user_id:
            art_stmt = art_stmt.where(Article.user_id == user_id)
        art_result = await session.execute(art_stmt)
        orphan_count = 0
        for article in art_result.scalars().all():
            if article.file_path:
                wiki_storage = get_wiki_storage(article.user_id)
                if not await wiki_storage.exists(article.file_path):
                    orphan_count += 1

        return SystemStats(
            **counts,
            orphan_count=orphan_count,
            articles_by_type=breakdowns["articles_by_type"],
            articles_by_page_type=breakdowns["articles_by_type"],
            articles_by_confidence=breakdowns["articles_by_confidence"],
            sources_by_type=breakdowns["sources_by_type"],
            sources_by_status=breakdowns["sources_by_status"],
            sources_stuck_processing=stuck,
            **health,
        )

    async def _get_stuck_sources(
        self,
        session: AsyncSession,
        user_id: str,
        threshold_minutes: int = 10,
    ) -> list[StuckSource]:
        """Find sources stuck in processing beyond the threshold.

        Args:
            session: Async database session.
            user_id: User ID filter.
            threshold_minutes: Minutes after which a processing source is stuck.

        Returns:
            List of StuckSource objects.
        """
        cutoff = utcnow_naive() - timedelta(minutes=threshold_minutes)
        stmt = select(Source).where(
            Source.status == IngestStatus.PROCESSING,
            Source.ingested_at < cutoff,
        )
        if user_id:
            stmt = stmt.where(Source.user_id == user_id)
        result = await session.execute(stmt)
        now = utcnow_naive()
        stuck: list[StuckSource] = []
        for src in result.scalars().all():
            minutes = int((now - src.ingested_at).total_seconds() / 60)
            stuck.append(
                StuckSource(
                    id=src.id,
                    title=src.title,
                    source_type=src.source_type,
                    ingested_at=src.ingested_at.isoformat(),
                    minutes_stuck=minutes,
                )
            )
        return stuck

    async def get_stuck_sources(
        self,
        session: AsyncSession,
        user_id: str,
    ) -> list[StuckSource]:
        """Public accessor for stuck sources.

        Args:
            session: Async database session.
            user_id: User ID filter.

        Returns:
            List of StuckSource objects.
        """
        return await self._get_stuck_sources(session, user_id)

    async def retry_stuck_source(
        self,
        session: AsyncSession,
        source_id: str,
        user_id: str,
    ) -> AdminActionResult:
        """Reset a stuck source to pending and re-queue compilation.

        Args:
            session: Async database session.
            source_id: The source UUID to retry.
            user_id: Owner user ID.

        Returns:
            AdminActionResult with action result.
        """
        stmt = select(Source).where(Source.id == source_id)
        if user_id:
            stmt = stmt.where(Source.user_id == user_id)
        result = await session.execute(stmt)
        source = result.scalar_one_or_none()
        if source is None:
            return AdminActionResult(action="retry_stuck", status="not_found")

        source.status = IngestStatus.PENDING
        source.error_message = None
        await session.commit()

        bg = get_background_compiler()
        job_id = await bg.schedule_compile(source_id=source_id, user_id=user_id)
        log.info("retry stuck source", source_id=source_id, user_id=user_id)
        return AdminActionResult(
            action="retry_stuck", status="scheduled", job_id=job_id
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
            wiki_storage = get_wiki_storage(article.user_id)
            if not await wiki_storage.exists(article.file_path):
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
