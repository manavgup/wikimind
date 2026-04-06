"""Async background compiler that dispatches compilation jobs.

In dev mode (no REDIS_URL), runs compile_source() in-process via
asyncio.create_task(). In prod mode, enqueues via ARQ + Redis.
This decouples ingest from compilation so ingest never blocks on Redis.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import structlog
from arq import create_pool
from arq.connections import RedisSettings

from wikimind.jobs.worker import compile_source, lint_wiki

log = structlog.get_logger()


class BackgroundCompiler:
    """Schedule compilation and lint jobs in dev (in-process) or prod (ARQ/Redis) mode."""

    def __init__(self) -> None:
        self._redis_url: str | None = os.environ.get("REDIS_URL")

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


_background_compiler: BackgroundCompiler | None = None


def get_background_compiler() -> BackgroundCompiler:
    """Return a singleton BackgroundCompiler instance."""
    global _background_compiler
    if _background_compiler is None:
        _background_compiler = BackgroundCompiler()
    return _background_compiler
