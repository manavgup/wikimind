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
    emit_draft_ready,
    emit_source_progress,
)
from wikimind.config import get_settings
from wikimind.database import get_session_factory
from wikimind.engine.compiler import Compiler
from wikimind.engine.concept_compiler import ConceptCompiler
from wikimind.engine.linter.runner import run_lint  # CodeQL[cyclic-import]
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
from wikimind.services.billing import reconcile_subscriptions
from wikimind.services.embedding import _SEARCH_AVAILABLE
from wikimind.storage import get_raw_storage, get_wiki_storage

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Job functions — called by ARQ workers
# ---------------------------------------------------------------------------


async def _build_normalized_doc(source: Source) -> NormalizedDocument:
    """Build a NormalizedDocument from a source's content.

    Reads from ``source.clean_text`` (Postgres) first.  Falls back to
    the raw ``.txt`` file on disk when ``clean_text`` is ``None``
    (backward compat with sources ingested before migration 0013).

    Args:
        source: The source record.  Must have ``clean_text`` set or a
            non-null ``file_path`` pointing at the cached text on disk.

    Returns:
        A NormalizedDocument ready for compilation.

    Raises:
        ValueError: If neither ``clean_text`` nor ``file_path`` provides content.
    """
    content = source.clean_text
    if content is None and source.file_path:
        raw_storage = get_raw_storage(source.user_id)
        content = await raw_storage.read(source.file_path)
    if content is None:
        msg = f"No content available for source {source.id}"
        raise ValueError(msg)

    return NormalizedDocument(
        raw_source_id=source.id,
        clean_text=content,
        title=source.title or "Untitled",
        author=source.author,
        published_date=source.published_date,
        estimated_tokens=_ingest_service.estimate_tokens(content),
        chunks=_ingest_service.chunk_text(content, source.id),
    )


async def _try_embed_article(article: Article) -> None:
    """Embed article chunks for semantic search (non-blocking, best-effort).

    Silently logs and returns on failure so compilation is never blocked
    by embedding errors.

    Args:
        article: The article to embed.
    """
    if not _SEARCH_AVAILABLE:
        return
    try:
        from wikimind.services.factories import get_embedding_service  # noqa: PLC0415

        embedding_service = get_embedding_service()
        if embedding_service is not None:
            uid = article.user_id
            wiki_storage = get_wiki_storage(uid)
            content = await wiki_storage.read(article.file_path)
            embedding_service.embed_article(
                article.id,
                article.title,
                content,
                user_id=uid,
            )
            log.info("Article embedded", article_id=article.id)
    except (RuntimeError, ValueError, OSError) as embed_err:
        log.warning(
            "Embedding failed (non-fatal)",
            article_id=article.id,
            error=str(embed_err),
        )


async def _compile_interactive(
    source: Source,
    doc: NormalizedDocument,
    compiler: Compiler,
    job_id: str,
    user_id: str,
) -> None:
    """Interactive compilation: create a draft for user review (issue #418)."""
    source_id = source.id
    session_factory = get_session_factory()

    async def _on_chunk_progress(message: str) -> None:
        await emit_source_progress(source_id, message, user_id=user_id)

    # LLM work — no DB session held open
    await emit_source_progress(source_id, "Extracting key takeaways...", user_id=user_id)
    takeaways = await compiler.extract_takeaways(doc)

    async with session_factory() as session:
        result = await compiler.compile(doc, session, progress_callback=_on_chunk_progress)
    if not result:
        msg = "Compiler returned no result"
        raise ValueError(msg)

    # Write results with a short-lived session
    await emit_source_progress(source_id, "Creating draft for review...", user_id=user_id)
    from wikimind.services.factories import get_draft_service  # noqa: PLC0415

    draft_service = get_draft_service()
    draft = await draft_service.create_draft(source, doc, result, takeaways, session)

    job = await session.get(Job, job_id)
    if job:
        job.status = JobStatus.COMPLETE
        job.completed_at = utcnow_naive()
        job.result_summary = f"Draft created for review: {result.title}"
        session.add(job)
    await session.commit()

    await emit_draft_ready(source_id, draft.id, result.title, user_id=user_id)
    log.info("compile_source draft ready", source_id=source_id, draft_id=draft.id)


async def _compile_direct(
    source: Source,
    doc: NormalizedDocument,
    compiler: Compiler,
    job_id: str,
    ctx,
    user_id: str,
) -> None:
    """Standard compilation: compile and save article directly."""
    source_id = source.id
    session_factory = get_session_factory()

    async def _on_chunk_progress(message: str) -> None:
        await emit_source_progress(source_id, message, user_id=user_id)

    # LLM compilation — session is opened internally by compiler.compile()
    # and released before the LLM call (the compiler commits before calling
    # the router). The session returned here is used only for DB reads that
    # inform the prompt (concept registry, compilation schema).
    async with session_factory() as session:
        result = await compiler.compile(doc, session, progress_callback=_on_chunk_progress)
    if not result:
        msg = "Compiler returned no result"
        raise ValueError(msg)

    # Save article with a new short-lived session
    await emit_source_progress(source_id, "Saving article...", user_id=user_id)
    async with session_factory() as session:
        source_row = await session.get(Source, source_id)
        if not source_row:
            msg = "Source disappeared during compile"
            raise ValueError(msg)
        article = await compiler.save_article(result, source_row, session)

    # Update job status with a short-lived session
    async with session_factory() as session:
        job = await session.get(Job, job_id)
        if job:
            job.status = JobStatus.COMPLETE
            job.completed_at = utcnow_naive()
            job.result_summary = f"Created article: {article.slug}"
            session.add(job)
            await session.commit()

    await emit_compilation_complete(article.slug, article.title, user_id=user_id)
    log.info("compile_source complete", source_id=source_id, slug=article.slug)

    await _try_embed_article(article)
    await sweep_wikilinks(ctx, user_id=user_id)


async def compile_source(
    ctx,
    source_id: str,
    user_id: str,
    doc: NormalizedDocument | None = None,
):
    """Compile a raw source into a wiki article.

    Args:
        ctx: ARQ context (unused in dev mode).
        source_id: The source UUID to compile.
        user_id: User ID for data isolation — scopes WebSocket broadcasts
            and verifies source ownership.
        doc: Pre-built NormalizedDocument from the ingest adapter. When
            provided, the worker skips re-reading and re-chunking the source
            file. ``None`` in the ARQ (Redis) path or for recompilation.
    """
    log.info("compile_source started", source_id=source_id, user_id=user_id)

    session_factory = get_session_factory()

    # --- Phase 1: Read source data + create job (short-lived session) ---
    async with session_factory() as session:
        source = await session.get(Source, source_id)
        if not source:
            log.error("Source not found", source_id=source_id)
            return

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
        job_id = job.id

    await emit_source_progress(source_id, "Reading source...", user_id=user_id)

    try:
        # --- Phase 2: Build normalized doc (may read from storage, no LLM) ---
        if doc is None:
            await emit_source_progress(source_id, "Normalizing content...", user_id=user_id)
            async with session_factory() as session:
                source = await session.get(Source, source_id)
                if not source:
                    log.error("Source disappeared during compile", source_id=source_id)
                    return
                doc = await _build_normalized_doc(source)

        # --- Phase 3: LLM compilation (no session held open) ---
        await emit_source_progress(source_id, "Compiling with LLM...", user_id=user_id)
        compiler = Compiler(user_id=user_id)

        settings = get_settings()
        if settings.compiler.interactive:
            await _compile_interactive(source, doc, compiler, job_id, user_id)
        else:
            await _compile_direct(source, doc, compiler, job_id, ctx, user_id)

    except Exception as e:  # Intentional broad catch — job runner must not crash
        log.error("compile_source failed", source_id=source_id, error=str(e))

        # Record the failure with a short-lived session.
        try:
            async with session_factory() as err_session:
                src = await err_session.get(Source, source_id)
                if src:
                    src.status = IngestStatus.FAILED
                    src.error_message = str(e)

                err_job = (
                    await err_session.execute(
                        select(Job).where(
                            Job.source_id == source_id,
                            Job.status == JobStatus.RUNNING,
                        )
                    )
                ).scalar_one_or_none()
                if err_job:
                    err_job.status = JobStatus.FAILED
                    err_job.completed_at = utcnow_naive()
                    err_job.error = str(e)

                await err_session.commit()
        except Exception:
            log.exception(
                "Failed to record compile error in DB",
                source_id=source_id,
            )

        await emit_compilation_failed(source_id, str(e), user_id=user_id)


async def lint_wiki(_ctx, user_id: str):
    """Run the wiki linter to find contradictions, orphans, and gaps.

    Delegates to the structured ``run_lint`` pipeline. The existing
    ARQ cron and ``POST /jobs/lint`` entry point call this function.

    Args:
        ctx: ARQ context (unused in dev mode).
        user_id: User ID for data isolation.
    """
    log.info("lint_wiki started", user_id=user_id)

    session_factory = get_session_factory()

    # Create job record (short-lived session)
    async with session_factory() as session:
        job = Job(
            job_type=JobType.LINT_WIKI,
            status=JobStatus.RUNNING,
            user_id=user_id,
            started_at=utcnow_naive(),
        )
        session.add(job)
        await session.commit()
        job_id = job.id

    try:
        # Run the lint pipeline — uses its own sessions internally
        # for LLM-powered contradiction detection (10-60s calls).
        async with session_factory() as session:
            report = await run_lint(session, job_id=job_id, user_id=user_id)

        # Update job status (short-lived session)
        async with session_factory() as session:
            job = await session.get(Job, job_id)
            if job:
                job.status = JobStatus.COMPLETE
                job.completed_at = utcnow_naive()
                job.result_summary = (
                    f"Found {report.contradictions_count} contradictions, {report.orphans_count} orphans"
                )
                session.add(job)
                await session.commit()

        log.info(
            "lint_wiki complete",
            summary=f"Found {report.contradictions_count} contradictions, {report.orphans_count} orphans",
        )

    except Exception as e:  # Intentional broad catch — job runner must not crash
        log.error("lint_wiki failed", error=str(e))
        async with session_factory() as session:
            job = await session.get(Job, job_id)
            if job:
                job.status = JobStatus.FAILED
                job.error = str(e)
                job.completed_at = utcnow_naive()
                session.add(job)
                await session.commit()


async def _get_article_source_ids(article: Article, session) -> list[str]:
    """Fetch source IDs from join table with JSON column fallback."""
    result = await session.exec(select(ArticleSource.source_id).where(ArticleSource.article_id == article.id))
    ids = list(result.all())
    if not ids:
        ids = json.loads(article.source_ids) if article.source_ids else []
    return ids


async def _get_article_concept_names(article: Article, session) -> list[str]:
    """Fetch concept names from join table with JSON column fallback."""
    result = await session.exec(select(ArticleConcept.concept_name).where(ArticleConcept.article_id == article.id))
    names = list(result.all())
    if not names:
        names = json.loads(article.concept_ids) if article.concept_ids else []
    return names


async def _recompile_from_source(article_id: str, user_id: str) -> None:
    """Recompile an article by re-reading and re-compiling its primary source.

    Opens short-lived sessions around DB reads/writes, keeping no session
    open during LLM calls.

    Args:
        article_id: The article UUID to recompile.
        user_id: Owner — used to resolve BYOK API keys.

    Raises:
        ValueError: If the article has no linked sources or the source file
            is missing.
    """
    session_factory = get_session_factory()

    # Read needed data (short-lived session)
    async with session_factory() as session:
        article = await session.get(Article, article_id)
        if not article:
            msg = "Article not found"
            raise ValueError(msg)
        source_ids = await _get_article_source_ids(article, session)
        if not source_ids:
            msg = "Article has no linked sources"
            raise ValueError(msg)

        source = await session.get(Source, source_ids[0])
        if not source or not source.file_path:
            msg = "Source or source file_path not found"
            raise ValueError(msg)

        doc = await _build_normalized_doc(source)

    # LLM compilation (no session held open)
    compiler = Compiler(user_id=user_id)
    async with session_factory() as session:
        result = await compiler.compile(doc, session)
    if not result:
        msg = "Compiler returned no result"
        raise ValueError(msg)

    # Save results (short-lived session)
    async with session_factory() as session:
        article = await session.get(Article, article_id)
        source = await session.get(Source, source_ids[0])
        if not article or not source:
            msg = "Article or source disappeared during recompile"
            raise ValueError(msg)
        await compiler.save_article_in_place(article, result, source, session)


async def _recompile_from_concept(article_id: str, user_id: str) -> None:
    """Recompile an article by regenerating its concept page.

    Opens short-lived sessions around DB reads/writes, keeping no session
    open during LLM calls.

    Args:
        article_id: The article UUID to recompile.
        user_id: Owner — used to resolve BYOK API keys.

    Raises:
        ValueError: If the article has no linked concepts or the concept
            is not found.
    """
    session_factory = get_session_factory()

    # Read needed data (short-lived session)
    async with session_factory() as session:
        article = await session.get(Article, article_id)
        if not article:
            msg = "Article not found"
            raise ValueError(msg)
        concept_names = await _get_article_concept_names(article, session)
        if not concept_names:
            msg = "Article has no linked concepts"
            raise ValueError(msg)

        concept_name = concept_names[0]
        result = await session.exec(select(Concept).where(Concept.name == concept_name))
        concept = result.first()
        if not concept:
            msg = "Concept not found"
            raise ValueError(msg)
        concept_id = concept.id

    # LLM compilation (session opened internally by concept compiler,
    # released before LLM call)
    concept_compiler = ConceptCompiler(user_id=user_id)
    async with session_factory() as session:
        concept = await session.get(Concept, concept_id)
        if not concept:
            msg = "Concept disappeared during recompile"
            raise ValueError(msg)
        result_article = await concept_compiler.compile_concept_page(concept, session)
    if not result_article:
        msg = "ConceptCompiler returned no result"
        raise ValueError(msg)


async def recompile_article(_ctx, article_id: str, mode: str, _job_id: str, user_id: str):
    """Recompile an existing article from its source or concept.

    Args:
        _ctx: ARQ context (unused in dev mode).
        article_id: The article UUID to recompile.
        mode: "source" or "concept".
        _job_id: Pre-created Job record ID to update.
        user_id: User ID for data isolation.
    """
    log.info(
        "recompile_article started",
        article_id=article_id,
        mode=mode,
        job_id=_job_id,
        user_id=user_id,
    )

    session_factory = get_session_factory()

    # Mark job as running + validate article exists (short-lived session)
    async with session_factory() as session:
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
        page_type = article.page_type

    try:
        # LLM-heavy recompilation — manages its own short-lived sessions
        if mode == "source":
            await _recompile_from_source(article_id, user_id=user_id)
        elif mode == "concept":
            await _recompile_from_concept(article_id, user_id=user_id)

        # Update job status (short-lived session)
        async with session_factory() as session:
            job = await session.get(Job, _job_id)
            if job:
                job.status = JobStatus.COMPLETE
                job.completed_at = utcnow_naive()
                job.result_summary = f"Recompiled article {article_id} via {mode}"
                session.add(job)
                await session.commit()

        await emit_article_recompiled(article_id, page_type, "complete", user_id=user_id)
        log.info("recompile_article complete", article_id=article_id, mode=mode)

    except Exception as e:  # Intentional broad catch — job runner must not crash
        log.error("recompile_article failed", article_id=article_id, error=str(e))

        async with session_factory() as session:
            job = await session.get(Job, _job_id)
            if job:
                job.status = JobStatus.FAILED
                job.completed_at = utcnow_naive()
                job.error = str(e)
                session.add(job)
                await session.commit()

        await emit_article_recompiled(article_id, page_type, "failed", user_id=user_id)


# ---------------------------------------------------------------------------
# Cron wrappers — iterate over all users so per-user scoping is respected
# ---------------------------------------------------------------------------


async def lint_all_users(ctx) -> None:
    """Weekly lint — runs for each user with data."""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(distinct(Article.user_id))  # type: ignore[arg-type]
        )
        user_ids = [row[0] for row in result]
    for uid in user_ids:
        await lint_wiki(ctx, user_id=uid)


async def sweep_all_users(ctx) -> None:
    """Daily sweep — runs for each user with data."""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(distinct(Article.user_id))  # type: ignore[arg-type]
        )
        user_ids = [row[0] for row in result]
    for uid in user_ids:
        await sweep_wikilinks(ctx, user_id=uid)


async def run_reconciliation(_ctx) -> dict:
    """Periodic subscription reconciliation with Lemon Squeezy.

    Skips immediately in self-hosted mode (``billing_enabled == False``).
    Runs every 6 hours to catch any drift caused by missed webhooks.

    Args:
        ctx: ARQ context (unused).

    Returns:
        A dict with the count of subscriptions reconciled.
    """
    settings = get_settings()
    if not settings.billing_enabled:
        return {"reconciled": 0}

    async with get_session_factory()() as session:
        count = await reconcile_subscriptions(session)
    return {"reconciled": count}


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
    _worker_cfg = get_settings().worker
    max_jobs = _worker_cfg.max_jobs
    job_timeout = _worker_cfg.job_timeout
    keep_result = _worker_cfg.keep_result

    # Weekly linter + daily wikilink sweep — iterate over all users
    # 6-hourly subscription reconciliation (no-op in self-hosted mode)
    cron_jobs: ClassVar[list] = [
        cron(lint_all_users, weekday=0, hour=2, minute=0),  # Monday 2am
        cron(sweep_all_users, hour=3, minute=0),  # Daily 3am
        cron(run_reconciliation, hour={0, 6, 12, 18}, minute=0),  # type: ignore[arg-type]  # Every 6 hours
    ]
