"""WikiMind Job Worker.

ARQ async job queue workers for compilation and linting.
Runs as a separate process in production: ``arq wikimind.jobs.worker.WorkerSettings``

In dev mode (no Redis), the same job functions are called in-process by
``BackgroundCompiler`` via ``asyncio.create_task()``.

The worker is intentionally agnostic to source format. Every ingest adapter
(URL, PDF, text, YouTube) writes a cleaned ``.txt`` file alongside the source
record (see ``wikimind.ingest.service`` and issue #59), and ``Source.file_path``
always points at that ``.txt``. The worker therefore just reads the file as
UTF-8 text — it never re-parses HTML, PDFs, or transcripts.
"""

from __future__ import annotations

import json
from typing import ClassVar

import structlog
from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import distinct
from sqlmodel import select

import wikimind.ingest.service as _ingest_service
from wikimind._datetime import utcnow_naive
from wikimind.api.routes.ws import (
    emit_article_recompiled,
    emit_compilation_complete,
    emit_compilation_failed,
    emit_source_progress,
)
from wikimind.config import get_settings
from wikimind.database import get_session_factory
from wikimind.engine.compiler import Compiler
from wikimind.engine.concept_compiler import ConceptCompiler
from wikimind.engine.linter.runner import run_lint
from wikimind.jobs.sweep import sweep_wikilinks
from wikimind.models import (
    Article,
    ArticleConcept,
    ArticleSource,
    Concept,
    IngestStatus,
    Job,
    JobStatus,
    JobType,
    NormalizedDocument,
    Source,
)
from wikimind.services.embedding import _SEARCH_AVAILABLE, get_embedding_service
from wikimind.storage import resolve_raw_path, resolve_wiki_path

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Job functions — called by ARQ workers
# ---------------------------------------------------------------------------


def _build_normalized_doc(source: Source) -> NormalizedDocument:
    """Read a source's cleaned text file and build a NormalizedDocument.

    Used as fallback when no pre-built document is passed (ARQ path or
    recompilation). Every ingest adapter writes a cleaned ``.txt`` and
    stores its path on the Source record (see issue #59).

    Args:
        source: The source record with a non-null ``file_path``.

    Returns:
        A NormalizedDocument ready for compilation.

    Raises:
        ValueError: If the source has no ``file_path``.
    """
    if not source.file_path:
        msg = "No cleaned text file path for source"
        raise ValueError(msg)

    text_path = resolve_raw_path(source.file_path, user_id=source.user_id)
    content = text_path.read_text(encoding="utf-8")

    return NormalizedDocument(
        raw_source_id=source.id,
        clean_text=content,
        title=source.title or "Untitled",
        author=source.author,
        published_date=source.published_date,
        estimated_tokens=_ingest_service.estimate_tokens(content),
        chunks=_ingest_service.chunk_text(content, source.id),
    )


def _try_embed_article(article: Article) -> None:
    """Embed article chunks for semantic search (non-blocking, best-effort).

    Silently logs and returns on failure so compilation is never blocked
    by embedding errors.

    Args:
        article: The article to embed.
    """
    if not _SEARCH_AVAILABLE:
        return
    try:
        embedding_service = get_embedding_service()
        if embedding_service is not None:
            content = resolve_wiki_path(article.file_path, user_id=article.user_id).read_text(encoding="utf-8")
            embedding_service.embed_article(article.id, article.title, content)
            log.info("Article embedded", article_id=article.id)
    except (RuntimeError, ValueError, OSError) as embed_err:
        log.warning(
            "Embedding failed (non-fatal)",
            article_id=article.id,
            error=str(embed_err),
        )


async def compile_source(
    ctx,
    source_id: str,
    user_id: str | None = None,
    doc: NormalizedDocument | None = None,
):
    """Compile a raw source into a wiki article.

    Args:
        ctx: ARQ context (unused in dev mode).
        source_id: The source UUID to compile.
        user_id: Optional owner — used to scope WebSocket broadcasts and
            verify source ownership.
        doc: Pre-built NormalizedDocument from the ingest adapter. When
            provided, the worker skips re-reading and re-chunking the source
            file. ``None`` in the ARQ (Redis) path or for recompilation.
    """
    log.info("compile_source started", source_id=source_id, user_id=user_id)

    async with get_session_factory()() as session:
        source = await session.get(Source, source_id)
        if not source:
            log.error("Source not found", source_id=source_id)
            return

        # Inherit user_id from the source record when not explicitly passed.
        if user_id is None:
            user_id = source.user_id

        # Reset source status so the frontend shows a spinner instead of
        # the stale error from a previous failed attempt (issue #111).
        source.status = IngestStatus.PROCESSING
        source.error_message = None
        session.add(source)

        # Create job record
        job = Job(
            job_type=JobType.COMPILE_SOURCE,
            status=JobStatus.RUNNING,
            source_id=source_id,
            user_id=user_id,
            started_at=utcnow_naive(),
        )
        session.add(job)
        await session.commit()

        await emit_source_progress(source_id, "Reading source...", user_id=user_id)

        try:
            if doc is None:
                await emit_source_progress(source_id, "Normalizing content...", user_id=user_id)
                doc = _build_normalized_doc(source)

            await emit_source_progress(source_id, "Compiling with LLM...", user_id=user_id)

            async def _on_chunk_progress(message: str) -> None:
                await emit_source_progress(source_id, message, user_id=user_id)

            compiler = Compiler(user_id=user_id)
            result = await compiler.compile(doc, session, progress_callback=_on_chunk_progress)

            if not result:
                msg = "Compiler returned no result"
                raise ValueError(msg)

            await emit_source_progress(source_id, "Saving article...", user_id=user_id)

            article = await compiler.save_article(result, source, session)

            # Update job
            job.status = JobStatus.COMPLETE
            job.completed_at = utcnow_naive()
            job.result_summary = f"Created article: {article.slug}"
            session.add(job)
            await session.commit()

            await emit_compilation_complete(article.slug, article.title, user_id=user_id)
            log.info("compile_source complete", source_id=source_id, slug=article.slug)

            _try_embed_article(article)

            # Sweep existing articles — a newly compiled article may resolve
            # brackets that were previously unresolvable. Fast (no LLM),
            # idempotent, and safe to fire on every compile.
            await sweep_wikilinks(ctx, user_id=user_id)

        except Exception as e:  # Intentional broad catch — job runner must not crash
            log.error("compile_source failed", source_id=source_id, error=str(e))

            source.status = IngestStatus.FAILED
            source.error_message = str(e)
            session.add(source)

            job.status = JobStatus.FAILED
            job.completed_at = utcnow_naive()
            job.error = str(e)
            session.add(job)

            await session.commit()
            await emit_compilation_failed(source_id, str(e), user_id=user_id)


async def lint_wiki(_ctx, user_id: str | None = None):
    """Run the wiki linter to find contradictions, orphans, and gaps.

    Delegates to the structured ``run_lint`` pipeline. The existing
    ARQ cron and ``POST /jobs/lint`` entry point call this function.

    Args:
        ctx: ARQ context (unused in dev mode).
        user_id: Optional owner — scopes the lint to this user's articles.
    """
    log.info("lint_wiki started", user_id=user_id)

    async with get_session_factory()() as session:
        job = Job(
            job_type=JobType.LINT_WIKI,
            status=JobStatus.RUNNING,
            user_id=user_id,
            started_at=utcnow_naive(),
        )
        session.add(job)
        await session.commit()

        try:
            report = await run_lint(session, job_id=job.id, user_id=user_id)

            job.status = JobStatus.COMPLETE
            job.completed_at = utcnow_naive()
            job.result_summary = f"Found {report.contradictions_count} contradictions, {report.orphans_count} orphans"
            session.add(job)
            await session.commit()

            log.info("lint_wiki complete", summary=job.result_summary)

        except Exception as e:  # Intentional broad catch — job runner must not crash
            log.error("lint_wiki failed", error=str(e))
            job.status = JobStatus.FAILED
            job.error = str(e)
            job.completed_at = utcnow_naive()
            session.add(job)
            await session.commit()


async def _get_article_source_ids(article: Article, session) -> list[str]:
    """Fetch source IDs from join table with JSON column fallback."""
    result = await session.execute(select(ArticleSource.source_id).where(ArticleSource.article_id == article.id))
    ids = [row[0] for row in result.all()]
    if not ids:
        ids = json.loads(article.source_ids) if article.source_ids else []
    return ids


async def _get_article_concept_names(article: Article, session) -> list[str]:
    """Fetch concept names from join table with JSON column fallback."""
    result = await session.execute(select(ArticleConcept.concept_name).where(ArticleConcept.article_id == article.id))
    names = [row[0] for row in result.all()]
    if not names:
        names = json.loads(article.concept_ids) if article.concept_ids else []
    return names


async def _recompile_from_source(article: Article, session, user_id: str | None = None) -> None:
    """Recompile an article by re-reading and re-compiling its primary source.

    Args:
        article: The article to recompile.
        session: Async database session.
        user_id: Optional owner — used to resolve BYOK API keys.

    Raises:
        ValueError: If the article has no linked sources or the source file
            is missing.
    """
    source_ids = await _get_article_source_ids(article, session)
    if not source_ids:
        msg = "Article has no linked sources"
        raise ValueError(msg)

    source = await session.get(Source, source_ids[0])
    if not source or not source.file_path:
        msg = "Source or source file_path not found"
        raise ValueError(msg)

    doc = _build_normalized_doc(source)

    effective_user_id = user_id or source.user_id
    compiler = Compiler(user_id=effective_user_id)
    result = await compiler.compile(doc, session)
    if not result:
        msg = "Compiler returned no result"
        raise ValueError(msg)

    await compiler.save_article(result, source, session)


async def _recompile_from_concept(article: Article, session, user_id: str | None = None) -> None:
    """Recompile an article by regenerating its concept page.

    Args:
        article: The article to recompile.
        session: Async database session.
        user_id: Optional owner — used to resolve BYOK API keys.

    Raises:
        ValueError: If the article has no linked concepts or the concept
            is not found.
    """
    concept_names = await _get_article_concept_names(article, session)
    if not concept_names:
        msg = "Article has no linked concepts"
        raise ValueError(msg)

    concept_name = concept_names[0]
    result = await session.execute(select(Concept).where(Concept.name == concept_name))
    concept = result.scalars().first()
    if not concept:
        msg = "Concept not found"
        raise ValueError(msg)

    concept_compiler = ConceptCompiler(user_id=user_id)
    result_article = await concept_compiler.compile_concept_page(concept, session)
    if not result_article:
        msg = "ConceptCompiler returned no result"
        raise ValueError(msg)


async def recompile_article(_ctx, article_id: str, mode: str, _job_id: str, user_id: str | None = None):
    """Recompile an existing article from its source or concept.

    Args:
        _ctx: ARQ context (unused in dev mode).
        article_id: The article UUID to recompile.
        mode: "source" or "concept".
        _job_id: Pre-created Job record ID to update.
        user_id: Optional owner — scopes WebSocket broadcasts.
    """
    log.info(
        "recompile_article started",
        article_id=article_id,
        mode=mode,
        job_id=_job_id,
        user_id=user_id,
    )

    async with get_session_factory()() as session:
        job = await session.get(Job, _job_id)
        if not job:
            log.error("Job not found for recompile", job_id=_job_id)
            return

        job.status = JobStatus.RUNNING
        job.started_at = utcnow_naive()
        session.add(job)
        await session.commit()

        article = await session.get(Article, article_id)
        if not article:
            log.error("Article not found for recompile", article_id=article_id)
            job.status = JobStatus.FAILED
            job.completed_at = utcnow_naive()
            job.error = "Article not found"
            session.add(job)
            await session.commit()
            await emit_article_recompiled(article_id, "unknown", "failed", user_id=user_id)
            return

        # Inherit user_id from the article record when not explicitly passed.
        if user_id is None:
            user_id = article.user_id

        try:
            if mode == "source":
                await _recompile_from_source(article, session, user_id=user_id)
            elif mode == "concept":
                await _recompile_from_concept(article, session, user_id=user_id)

            job.status = JobStatus.COMPLETE
            job.completed_at = utcnow_naive()
            job.result_summary = f"Recompiled article {article_id} via {mode}"
            session.add(job)
            await session.commit()

            await emit_article_recompiled(article_id, article.page_type, "complete", user_id=user_id)
            log.info("recompile_article complete", article_id=article_id, mode=mode)

        except Exception as e:  # Intentional broad catch — job runner must not crash
            log.error("recompile_article failed", article_id=article_id, error=str(e))

            job.status = JobStatus.FAILED
            job.completed_at = utcnow_naive()
            job.error = str(e)
            session.add(job)
            await session.commit()

            await emit_article_recompiled(article_id, article.page_type, "failed", user_id=user_id)


# ---------------------------------------------------------------------------
# Cron wrappers — iterate over all users so per-user scoping is respected
# ---------------------------------------------------------------------------


async def lint_all_users(ctx) -> None:
    """Weekly lint — runs for each user with data, plus legacy unowned data."""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(distinct(Article.user_id)).where(  # type: ignore[arg-type]
                Article.user_id.isnot(None)  # type: ignore[union-attr]
            )
        )
        user_ids = [row[0] for row in result]
    for uid in user_ids:
        await lint_wiki(ctx, user_id=uid)
    # Also lint data with no user_id (legacy single-user)
    await lint_wiki(ctx, user_id=None)


async def sweep_all_users(ctx) -> None:
    """Daily sweep — runs for each user with data, plus legacy unowned data."""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(distinct(Article.user_id)).where(  # type: ignore[arg-type]
                Article.user_id.isnot(None)  # type: ignore[union-attr]
            )
        )
        user_ids = [row[0] for row in result]
    for uid in user_ids:
        await sweep_wikilinks(ctx, user_id=uid)
    # Also sweep data with no user_id (legacy single-user)
    await sweep_wikilinks(ctx, user_id=None)


# ---------------------------------------------------------------------------
# Redis settings — only used when a Redis URL is configured (production ARQ)
# ---------------------------------------------------------------------------


def get_redis_settings() -> RedisSettings:
    """Return ARQ RedisSettings from ``Settings.redis_url``.

    Reads through ``get_settings()`` so the URL honours the project's
    standard env var precedence (``WIKIMIND_REDIS_URL`` then raw
    ``REDIS_URL``). Falls back to ``localhost:6379`` when unset so the
    ``WorkerSettings`` class can still be imported without error, but the
    worker will fail to start without a reachable Redis instance.
    """
    redis_url = get_settings().redis_url
    if redis_url:
        return RedisSettings.from_dsn(redis_url)
    return RedisSettings(host="localhost", port=6379)


# ---------------------------------------------------------------------------
# Worker settings — used by `arq wikimind.jobs.worker.WorkerSettings`
# ---------------------------------------------------------------------------


class WorkerSettings:
    """ARQ worker configuration for production (requires Redis)."""

    functions: ClassVar[list] = [compile_source, lint_wiki, recompile_article, sweep_wikilinks]
    redis_settings = get_redis_settings()
    max_jobs = 4
    job_timeout = 300  # 5 min max per job
    keep_result = 3600  # Keep results for 1 hour

    # Weekly linter + daily wikilink sweep — iterate over all users
    cron_jobs: ClassVar[list] = [
        cron(lint_all_users, weekday=0, hour=2, minute=0),  # Monday 2am
        cron(sweep_all_users, hour=3, minute=0),  # Daily 3am
    ]
