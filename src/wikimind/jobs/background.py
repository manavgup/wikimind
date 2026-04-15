"""Async background compiler that dispatches compilation jobs.

In dev mode (``Settings.redis_url`` unset), runs ``compile_source()``
in-process via ``asyncio.create_task()``. In prod mode, enqueues via
ARQ + Redis. This decouples ingest from compilation so ingest never
blocks on Redis.

The Redis URL is read through ``wikimind.config.get_settings()`` so it
honours both ``WIKIMIND_REDIS_URL`` (matching the project env prefix)
and the raw ``REDIS_URL`` fallback (ADR-002, CI/CD compatibility).
"""

from __future__ import annotations

import asyncio
import uuid

import structlog
from arq import create_pool
from arq.connections import RedisSettings

from wikimind.config import get_settings
from wikimind.jobs.worker import compile_source, lint_wiki, recompile_article, sweep_wikilinks

log = structlog.get_logger()


class BackgroundCompiler:
    """Schedule compilation and lint jobs in dev (in-process) or prod (ARQ/Redis) mode."""

    def __init__(self) -> None:
        self._redis_url: str | None = get_settings().redis_url

    @property
    def is_prod(self) -> bool:
        """Return True when a real Redis URL is configured."""
        return self._redis_url is not None

    async def schedule_compile(self, source_id: str) -> str:
        """Schedule a compilation job for the given source.

        Args:
            source_id: The source UUID to compile.

        Returns:
            A placeholder job ID string.
        """
        job_id = str(uuid.uuid4())

        if self.is_prod:
            await self._enqueue_arq("compile_source", source_id)
        else:
            asyncio.create_task(self._run_compile_in_process(source_id))  # noqa: RUF006

        log.info("compile scheduled", source_id=source_id, mode="arq" if self.is_prod else "in-process")
        return job_id

    async def schedule_lint(self) -> str:
        """Schedule a wiki lint job.

        Returns:
            A placeholder job ID string.
        """
        job_id = str(uuid.uuid4())

        if self.is_prod:
            await self._enqueue_arq("lint_wiki")
        else:
            asyncio.create_task(self._run_lint_in_process())  # noqa: RUF006

        log.info("lint scheduled", mode="arq" if self.is_prod else "in-process")
        return job_id

    async def schedule_recompile(self, article_id: str, mode: str, job_id: str) -> str:
        """Schedule a recompile job for an article.

        Args:
            article_id: The article UUID to recompile.
            mode: "source" or "concept".
            job_id: Pre-created Job record ID.

        Returns:
            The job ID string.
        """
        if self.is_prod:
            await self._enqueue_arq("recompile_article", article_id, mode, job_id)
        else:
            asyncio.create_task(self._run_recompile_in_process(article_id, mode, job_id))  # noqa: RUF006

        log.info(
            "recompile scheduled",
            article_id=article_id,
            mode=mode,
            job_id=job_id,
            dispatch="arq" if self.is_prod else "in-process",
        )
        return job_id

    async def schedule_sweep(self) -> str:
        """Schedule a wikilink resolution sweep job.

        Returns:
            A placeholder job ID string.
        """
        job_id = str(uuid.uuid4())

        if self.is_prod:
            await self._enqueue_arq("sweep_wikilinks")
        else:
            asyncio.create_task(self._run_sweep_in_process())  # noqa: RUF006

        log.info("sweep scheduled", mode="arq" if self.is_prod else "in-process")
        return job_id

    async def _enqueue_arq(self, func_name: str, *args: object) -> None:
        """Enqueue a job via ARQ Redis pool."""
        settings = RedisSettings.from_dsn(self._redis_url)  # type: ignore[arg-type]
        pool = await create_pool(settings)
        try:
            await pool.enqueue_job(func_name, *args)
        finally:
            await pool.close()

    @staticmethod
    async def _run_compile_in_process(source_id: str) -> None:
        """Run compile_source directly in the current event loop."""
        try:
            await compile_source({}, source_id)
        except Exception:
            log.exception("in-process compilation failed", source_id=source_id)

    @staticmethod
    async def _run_lint_in_process() -> None:
        """Run lint_wiki directly in the current event loop."""
        try:
            await lint_wiki({})
        except Exception:
            log.exception("in-process lint failed")

    @staticmethod
    async def _run_recompile_in_process(article_id: str, mode: str, job_id: str) -> None:
        """Run recompile_article directly in the current event loop."""
        try:
            await recompile_article({}, article_id, mode, job_id)
        except Exception:
            log.exception("in-process recompile failed", article_id=article_id)

    @staticmethod
    async def _run_sweep_in_process() -> None:
        """Run sweep_wikilinks directly in the current event loop."""
        try:
            await sweep_wikilinks({})
        except Exception:
            log.exception("in-process sweep failed")


_background_compiler: BackgroundCompiler | None = None


def get_background_compiler() -> BackgroundCompiler:
    """Return a singleton BackgroundCompiler instance."""
    global _background_compiler
    if _background_compiler is None:
        _background_compiler = BackgroundCompiler()
    return _background_compiler
