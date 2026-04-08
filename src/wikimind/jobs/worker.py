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
from datetime import datetime
from pathlib import Path
from typing import ClassVar

import structlog
from arq import cron
from arq.connections import RedisSettings
from sqlmodel import select

import wikimind.ingest.service as _ingest_service
from wikimind.api.routes.ws import (
    emit_compilation_complete,
    emit_compilation_failed,
    emit_job_progress,
    emit_linter_alert,
)
from wikimind.config import get_settings
from wikimind.database import get_session_factory
from wikimind.engine.compiler import Compiler
from wikimind.engine.llm_router import get_llm_router
from wikimind.models import (
    Article,
    CompletionRequest,
    IngestStatus,
    Job,
    JobStatus,
    JobType,
    NormalizedDocument,
    Source,
    TaskType,
)

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

        # Create job record
        job = Job(
            job_type=JobType.COMPILE_SOURCE,
            status=JobStatus.RUNNING,
            source_id=source_id,
            started_at=datetime.utcnow(),
        )
        session.add(job)
        await session.commit()

        await emit_job_progress(job.id, 10, "Reading source...")

        try:
            # Every adapter writes a cleaned .txt and stores its path on the
            # Source record (see issue #59). The worker is format-agnostic and
            # just reads UTF-8 text — no PDF/HTML re-extraction here.
            if not source.file_path:
                raise ValueError("No cleaned text file path for source")

            text_path = Path(source.file_path)
            content = text_path.read_text(encoding="utf-8")

            await emit_job_progress(job.id, 30, "Normalizing content...")

            doc = NormalizedDocument(
                raw_source_id=source.id,
                clean_text=content,
                title=source.title or "Untitled",
                author=source.author,
                published_date=source.published_date,
                estimated_tokens=_ingest_service.estimate_tokens(content),
                chunks=_ingest_service.chunk_text(content, source.id),
            )

            await emit_job_progress(job.id, 50, "Compiling with LLM...")

            compiler = Compiler()
            result = await compiler.compile(doc, session)  # type: ignore[arg-type]

            if not result:
                raise ValueError("Compiler returned no result")

            await emit_job_progress(job.id, 80, "Saving article...")

            article = await compiler.save_article(result, source, session)  # type: ignore[arg-type]

            # Update job
            job.status = JobStatus.COMPLETE
            job.completed_at = datetime.utcnow()
            job.result_summary = f"Created article: {article.slug}"
            session.add(job)
            await session.commit()

            await emit_job_progress(job.id, 100, "Done")
            await emit_compilation_complete(article.slug, article.title)

            log.info("compile_source complete", source_id=source_id, slug=article.slug)

        except Exception as e:
            log.error("compile_source failed", source_id=source_id, error=str(e))

            source.status = IngestStatus.FAILED
            source.error_message = str(e)
            session.add(source)

            job.status = JobStatus.FAILED
            job.completed_at = datetime.utcnow()
            job.error = str(e)
            session.add(job)

            await session.commit()
            await emit_compilation_failed(source_id, str(e))


async def lint_wiki(ctx):
    """Run the wiki linter to find contradictions, orphans, and gaps."""
    log.info("lint_wiki started")

    async with get_session_factory()() as session:
        job = Job(
            job_type=JobType.LINT_WIKI,
            status=JobStatus.RUNNING,
            started_at=datetime.utcnow(),
        )
        session.add(job)
        await session.commit()

        try:
            # Gather all articles
            result = await session.execute(select(Article))
            articles = result.scalars().all()

            if not articles:
                job.status = JobStatus.COMPLETE
                job.result_summary = "No articles to lint"
                session.add(job)
                await session.commit()
                return

            # Build wiki summary for linter
            summaries = []
            for article in articles[:50]:  # Cap at 50 for token budget
                try:
                    content = Path(article.file_path).read_text(encoding="utf-8")[:1000]
                    summaries.append(f"## {article.title}\n{content}\n")
                except Exception:
                    continue

            wiki_text = "\n---\n".join(summaries)

            router = get_llm_router()
            lint_request = CompletionRequest(
                system="""You are a wiki health auditor. Analyze these wiki articles and identify issues.

Return valid JSON only:
{
  "contradictions": [{"claim_a": "...", "claim_b": "...", "articles": ["title1", "title2"]}],
  "orphaned_articles": ["title"],
  "stale_articles": ["title"],
  "gap_suggestions": ["New article title that should exist"],
  "coverage_scores": {"topic": 0.0}
}""",
                messages=[{"role": "user", "content": f"Analyze this wiki:\n\n{wiki_text}"}],
                max_tokens=2048,
                temperature=0.2,
                response_format="json",
                task_type=TaskType.LINT,
            )

            response = await router.complete(lint_request, session=session)
            lint_data = router.parse_json_response(response)

            # Save health report
            settings = get_settings()
            meta_dir = Path(settings.data_dir) / "wiki" / "_meta"
            meta_dir.mkdir(parents=True, exist_ok=True)

            health = {
                "generated_at": datetime.utcnow().isoformat(),
                "total_articles": len(articles),
                **lint_data,
            }
            (meta_dir / "health.json").write_text(json.dumps(health, indent=2))

            # Emit alerts
            if lint_data.get("contradictions"):
                articles_involved = []
                for c in lint_data["contradictions"]:
                    articles_involved.extend(c.get("articles", []))
                await emit_linter_alert("contradiction", articles_involved)

            job.status = JobStatus.COMPLETE
            job.completed_at = datetime.utcnow()
            job.result_summary = (
                f"Found {len(lint_data.get('contradictions', []))} contradictions, "
                f"{len(lint_data.get('gap_suggestions', []))} gaps"
            )
            session.add(job)
            await session.commit()

            log.info("lint_wiki complete", summary=job.result_summary)

        except Exception as e:
            log.error("lint_wiki failed", error=str(e))
            job.status = JobStatus.FAILED
            job.error = str(e)
            job.completed_at = datetime.utcnow()
            session.add(job)
            await session.commit()


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

    functions: ClassVar[list] = [compile_source, lint_wiki]
    redis_settings = get_redis_settings()
    max_jobs = 4
    job_timeout = 300  # 5 min max per job
    keep_result = 3600  # Keep results for 1 hour

    # Weekly linter
    cron_jobs: ClassVar[list] = [
        cron(lint_wiki, weekday=0, hour=2, minute=0)  # Monday 2am
    ]
