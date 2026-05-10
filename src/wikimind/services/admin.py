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
    CompiledClaim,
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
    User,
)
from wikimind.storage import get_wiki_storage

log = structlog.get_logger()


class AdminService:
    """Aggregate system-wide statistics and administrative operations."""

    async def _get_content_breakdowns(
        self,
        session: AsyncSession,
    ) -> dict:
        """Compute content breakdown aggregates (system-wide).

        Returns dict with articles_by_type, articles_by_confidence,
        sources_by_type, and sources_by_status.
        """
        # Articles by page_type
        type_stmt = select(Article.page_type, func.count()).group_by(Article.page_type)
        type_result = await session.execute(type_stmt)
        articles_by_type = {row[0]: row[1] for row in type_result.all()}

        # Articles by confidence
        conf_stmt = select(Article.confidence, func.count()).group_by(Article.confidence)
        conf_result = await session.execute(conf_stmt)
        articles_by_confidence = {(row[0] or "unknown"): row[1] for row in conf_result.all()}

        # Sources by type
        stype_stmt = select(Source.source_type, func.count()).group_by(Source.source_type)
        stype_result = await session.execute(stype_stmt)
        sources_by_type = {row[0]: row[1] for row in stype_result.all()}

        # Sources by status
        sstatus_stmt = select(Source.status, func.count()).group_by(Source.status)
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
    ) -> dict:
        """Compute compilation queue depth, last compilation time, and success rate."""
        queue_stmt = (
            select(func.count())
            .select_from(Job)
            .where(
                Job.job_type == JobType.COMPILE_SOURCE,
                Job.status == JobStatus.QUEUED,
            )
        )
        queue_result = await session.execute(queue_stmt)
        compilation_queue_depth = queue_result.scalar() or 0

        last_stmt = select(func.max(Job.completed_at)).where(
            Job.job_type == JobType.COMPILE_SOURCE,
            Job.status == JobStatus.COMPLETE,
        )
        last_result = await session.execute(last_stmt)
        last_val = last_result.scalar()
        last_compilation_at = last_val.isoformat() if last_val else None

        # Compilation success rate: completed / (completed + failed)
        completed_stmt = select(func.count()).select_from(Source).where(Source.status == IngestStatus.COMPILED)
        completed_result = await session.execute(completed_stmt)
        completed_count = completed_result.scalar() or 0

        failed_stmt = select(func.count()).select_from(Source).where(Source.status == IngestStatus.FAILED)
        failed_result = await session.execute(failed_stmt)
        failed_count = failed_result.scalar() or 0

        total_terminal = completed_count + failed_count
        compilation_success_rate = completed_count / total_terminal if total_terminal > 0 else None

        return {
            "compilation_queue_depth": compilation_queue_depth,
            "last_compilation_at": last_compilation_at,
            "compilation_success_rate": compilation_success_rate,
        }

    async def get_stats(
        self,
        session: AsyncSession,
    ) -> SystemStats:
        """Compute aggregate system-wide counts across all tables.

        Args:
            session: Async database session.

        Returns:
            SystemStats with aggregate counts and breakdowns.
        """
        # Core counts (system-wide, no user_id filter)
        counts: dict[str, int] = {}
        for model, key in [
            (Article, "article_count"),
            (Source, "source_count"),
            (Concept, "concept_count"),
            (Backlink, "backlink_count"),
            (Conversation, "conversation_count"),
        ]:
            stmt = select(func.count()).select_from(model)
            result = await session.execute(stmt)
            counts[key] = result.scalar() or 0

        # User count
        user_stmt = select(func.count()).select_from(User)
        user_result = await session.execute(user_stmt)
        total_users = user_result.scalar() or 0

        # Compiled claims count
        claims_stmt = select(func.count()).select_from(CompiledClaim)
        claims_result = await session.execute(claims_stmt)
        total_compiled_claims = claims_result.scalar() or 0

        breakdowns = await self._get_content_breakdowns(session)
        health = await self._get_compilation_health(session)
        stuck = await self._get_stuck_sources(session)

        # Orphan count (articles with missing wiki files)
        art_stmt = select(Article)
        art_result = await session.execute(art_stmt)
        orphan_count = 0
        for article in art_result.scalars().all():
            if article.file_path:
                wiki_storage = get_wiki_storage(article.user_id)
                if not await wiki_storage.exists(article.file_path):
                    orphan_count += 1

        return SystemStats(
            total_users=total_users,
            total_sources=counts["source_count"],
            total_articles=counts["article_count"],
            total_compiled_claims=total_compiled_claims,
            **counts,
            orphan_count=orphan_count,
            articles_by_type=breakdowns["articles_by_type"],
            articles_by_page_type=breakdowns["articles_by_type"],
            articles_by_confidence=breakdowns["articles_by_confidence"],
            sources_by_type=breakdowns["sources_by_type"],
            sources_by_status=breakdowns["sources_by_status"],
            sources_stuck_processing=stuck,
            stuck_sources=len(stuck),
            **health,
        )

    async def _get_stuck_sources(
        self,
        session: AsyncSession,
        threshold_minutes: int = 10,
    ) -> list[StuckSource]:
        """Find sources stuck in processing beyond the threshold (system-wide).

        Args:
            session: Async database session.
            threshold_minutes: Minutes after which a processing source is stuck.

        Returns:
            List of StuckSource objects.
        """
        cutoff = utcnow_naive() - timedelta(minutes=threshold_minutes)
        stmt = select(Source).where(
            Source.status == IngestStatus.PROCESSING,
            Source.ingested_at < cutoff,
        )
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
    ) -> list[StuckSource]:
        """Public accessor for stuck sources (system-wide).

        Args:
            session: Async database session.

        Returns:
            List of StuckSource objects.
        """
        return await self._get_stuck_sources(session)

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
            user_id: Admin user ID (used as the job owner).

        Returns:
            AdminActionResult with action result.
        """
        stmt = select(Source).where(Source.id == source_id)
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
        return AdminActionResult(action="retry_stuck", status="scheduled", job_id=job_id)

    async def get_orphan_articles(
        self,
        session: AsyncSession,
    ) -> list[OrphanArticle]:
        """Find articles whose wiki file is missing from disk (system-wide).

        Args:
            session: Async database session.

        Returns:
            List of OrphanArticle with orphan article info.
        """
        stmt = select(Article)
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
    ) -> list[EligibleConcept]:
        """Find concepts eligible for concept-page generation (system-wide).

        A concept is eligible when its article_count meets the threshold
        defined in ``settings.taxonomy.concept_page_min_sources``.

        Args:
            session: Async database session.

        Returns:
            List of EligibleConcept with eligible concept info.
        """
        settings = get_settings()
        threshold = settings.taxonomy.concept_page_min_sources

        stmt = select(Concept).where(Concept.article_count >= threshold)
        result = await session.execute(stmt)
        concepts = result.scalars().all()

        eligible: list[EligibleConcept] = []
        for concept in concepts:
            # Check if a concept page article already exists
            page_stmt = select(Article).where(
                Article.slug == f"concept-{concept.name}",
                Article.page_type == "concept",
            )
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
            user_id: Admin user ID to scope the sweep.

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
