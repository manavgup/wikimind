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


async def compile_source(ctx, source_id: str):
    """Compile a raw source into a wiki article."""
    log.info("compile_source started", source_id=source_id)

    async with get_session_factory()() as session:
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
            started_at=utcnow_naive(),
        )
        session.add(job)
        await session.commit()

        await emit_source_progress(source_id, "Reading source...")

        try:
            # Every adapter writes a cleaned .txt and stores its path on the
            # Source record (see issue #59). The worker is format-agnostic and
            # just reads UTF-8 text — no PDF/HTML re-extraction here.
            if not source.file_path:
                raise ValueError("No cleaned text file path for source")

            text_path = resolve_raw_path(source.file_path)
            content = text_path.read_text(encoding="utf-8")

            await emit_source_progress(source_id, "Normalizing content...")

            doc = NormalizedDocument(
                raw_source_id=source.id,
                clean_text=content,
                title=source.title or "Untitled",
                author=source.author,
                published_date=source.published_date,
                estimated_tokens=_ingest_service.estimate_tokens(content),
                chunks=_ingest_service.chunk_text(content, source.id),
            )

            await emit_source_progress(source_id, "Compiling with LLM...")

            async def _on_chunk_progress(message: str) -> None:
                await emit_source_progress(source_id, message)

            compiler = Compiler()
            result = await compiler.compile(doc, session, progress_callback=_on_chunk_progress)  # type: ignore[arg-type]

            if not result:
                raise ValueError("Compiler returned no result")

            await emit_source_progress(source_id, "Saving article...")

            article = await compiler.save_article(result, source, session)  # type: ignore[arg-type]

            # Update job
            job.status = JobStatus.COMPLETE
            job.completed_at = utcnow_naive()
            job.result_summary = f"Created article: {article.slug}"
            session.add(job)
            await session.commit()

            await emit_compilation_complete(article.slug, article.title)

            log.info("compile_source complete", source_id=source_id, slug=article.slug)

            # Embed article chunks for semantic search (non-blocking)
            if _SEARCH_AVAILABLE:
                try:
                    embedding_service = get_embedding_service()
                    if embedding_service is not None:
                        content = resolve_wiki_path(article.file_path).read_text(encoding="utf-8")
                        embedding_service.embed_article(article.id, article.title, content)
                        log.info("Article embedded", article_id=article.id)
                except Exception as embed_err:
                    log.warning(
                        "Embedding failed (non-fatal)",
                        article_id=article.id,
                        error=str(embed_err),
                    )

            # Sweep existing articles — a newly compiled article may resolve
            # brackets that were previously unresolvable. Fast (no LLM),
            # idempotent, and safe to fire on every compile.
            await sweep_wikilinks(ctx)

        except Exception as e:
            log.error("compile_source failed", source_id=source_id, error=str(e))

            source.status = IngestStatus.FAILED
            source.error_message = str(e)
            session.add(source)

            job.status = JobStatus.FAILED
            job.completed_at = utcnow_naive()
            job.error = str(e)
            session.add(job)

            await session.commit()
            await emit_compilation_failed(source_id, str(e))


async def lint_wiki(ctx):
    """Run the wiki linter to find contradictions, orphans, and gaps.

    Delegates to the structured ``run_lint`` pipeline. The existing
    ARQ cron and ``POST /jobs/lint`` entry point call this function.
    """
    log.info("lint_wiki started")

    async with get_session_factory()() as session:
        job = Job(
            job_type=JobType.LINT_WIKI,
            status=JobStatus.RUNNING,
            started_at=utcnow_naive(),
        )
        session.add(job)
        await session.commit()

        try:
            report = await run_lint(session, job_id=job.id)

            job.status = JobStatus.COMPLETE
            job.completed_at = utcnow_naive()
            job.result_summary = f"Found {report.contradictions_count} contradictions, {report.orphans_count} orphans"
            session.add(job)
            await session.commit()

            log.info("lint_wiki complete", summary=job.result_summary)

        except Exception as e:
            log.error("lint_wiki failed", error=str(e))
            job.status = JobStatus.FAILED
            job.error = str(e)
            job.completed_at = utcnow_naive()
            session.add(job)
            await session.commit()


async def recompile_article(ctx, article_id: str, mode: str, _job_id: str):
    """Recompile an existing article from its source or concept.

    Args:
        ctx: ARQ context (unused in dev mode).
        article_id: The article UUID to recompile.
        mode: "source" or "concept".
        _job_id: Pre-created Job record ID to update.
    """
    log.info("recompile_article started", article_id=article_id, mode=mode, job_id=_job_id)

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
            await emit_article_recompiled(article_id, "unknown", "failed")
            return

        try:
            if mode == "source":
                source_ids = json.loads(article.source_ids) if article.source_ids else []
                if not source_ids:
                    raise ValueError("Article has no linked sources")

                source = await session.get(Source, source_ids[0])
                if not source or not source.file_path:
                    raise ValueError("Source or source file_path not found")

                content = resolve_raw_path(source.file_path).read_text(encoding="utf-8")

                doc = NormalizedDocument(
                    raw_source_id=source.id,
                    clean_text=content,
                    title=source.title or "Untitled",
                    author=source.author,
                    published_date=source.published_date,
                    estimated_tokens=_ingest_service.estimate_tokens(content),
                    chunks=_ingest_service.chunk_text(content, source.id),
                )

                compiler = Compiler()
                result = await compiler.compile(doc, session)

                if not result:
                    raise ValueError("Compiler returned no result")

                await compiler.save_article(result, source, session)

            elif mode == "concept":
                concept_ids = json.loads(article.concept_ids) if article.concept_ids else []
                if not concept_ids:
                    raise ValueError("Article has no linked concepts")

                concept_name = concept_ids[0]
                result = await session.execute(select(Concept).where(Concept.name == concept_name))
                concept = result.scalars().first()
                if not concept:
                    raise ValueError("Concept not found")

                concept_compiler = ConceptCompiler()
                result_article = await concept_compiler.compile_concept_page(concept, session)

                if not result_article:
                    raise ValueError("ConceptCompiler returned no result")

            job.status = JobStatus.COMPLETE
            job.completed_at = utcnow_naive()
            job.result_summary = f"Recompiled article {article_id} via {mode}"
            session.add(job)
            await session.commit()

            await emit_article_recompiled(article_id, article.page_type, "complete")

            log.info("recompile_article complete", article_id=article_id, mode=mode)

        except Exception as e:
            log.error("recompile_article failed", article_id=article_id, error=str(e))

            job.status = JobStatus.FAILED
            job.completed_at = utcnow_naive()
            job.error = str(e)
            session.add(job)
            await session.commit()

            await emit_article_recompiled(article_id, article.page_type, "failed")


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

    # Weekly linter + daily wikilink sweep
    cron_jobs: ClassVar[list] = [
        cron(lint_wiki, weekday=0, hour=2, minute=0),  # Monday 2am
        cron(sweep_wikilinks, hour=3, minute=0),  # Daily 3am
    ]
