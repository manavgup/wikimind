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
import functools
import os
import uuid
from typing import TYPE_CHECKING

import structlog
from arq import create_pool
from arq.connections import RedisSettings

from wikimind.config import get_settings
from wikimind.jobs.worker import compile_source, lint_wiki, recompile_article, sweep_wikilinks

if TYPE_CHECKING:
    from wikimind.models import NormalizedDocument

log = structlog.get_logger()


class ProductionConfigError(RuntimeError):
    """Raised when production environment is missing required configuration."""


def _check_production_redis_guard() -> None:
    """Raise if running on Fly.io without Redis configured.

    On Fly.io (FLY_APP_NAME is set), Redis is required for the ARQ job
    queue. In-process fallback is only allowed for local development.
    """
    on_fly = bool(os.environ.get("FLY_APP_NAME"))
    redis_url = get_settings().redis_url
    if on_fly and not redis_url:
        msg = (
            "Production environment (FLY_APP_NAME set) requires Redis. "
            "Set WIKIMIND_REDIS_URL or REDIS_URL to a valid Redis URL. "
            "Refusing to start with in-process fallback on Fly.io."
        )
        log.error("production_config_error", error=msg)
        raise ProductionConfigError(msg)


class BackgroundCompiler:
    """Schedule compilation and lint jobs in dev (in-process) or prod (ARQ/Redis) mode."""

    def __init__(self) -> None:
        _check_production_redis_guard()
        self._redis_url: str | None = get_settings().redis_url

    @property
    def is_prod(self) -> bool:
        """Return True when a real Redis URL is configured."""
        return self._redis_url is not None

    async def schedule_compile(
        self,
        source_id: str,
        user_id: str,
        doc: NormalizedDocument | None = None,
    ) -> str:
        """Schedule a compilation job for the given source.

        Args:
            source_id: The source UUID to compile.
            user_id: Owner — scopes to this user's data.
            doc: Pre-built NormalizedDocument from the ingest adapter. Passed
                to the in-process worker to avoid re-reading and re-chunking
                the source file. Ignored in the ARQ (Redis) path because
                Pydantic models are not ARQ-serializable.

        Returns:
            A placeholder job ID string.
        """
        job_id = str(uuid.uuid4())

        if self.is_prod:
            await self._enqueue_arq("compile_source", source_id, user_id)
        else:
            asyncio.create_task(  # noqa: RUF006
                self._run_compile_in_process(source_id, user_id, doc)
            )

        log.info(
            "compile scheduled",
            source_id=source_id,
            user_id=user_id,
            mode="arq" if self.is_prod else "in-process",
        )
        return job_id

    async def schedule_lint(self, user_id: str) -> str:
        """Schedule a wiki lint job.

        Args:
            user_id: Owner — scopes to this user's data.

        Returns:
            A placeholder job ID string.
        """
        job_id = str(uuid.uuid4())

        if self.is_prod:
            await self._enqueue_arq("lint_wiki", user_id)
        else:
            asyncio.create_task(self._run_lint_in_process(user_id))  # noqa: RUF006

        log.info(
            "lint scheduled",
            user_id=user_id,
            mode="arq" if self.is_prod else "in-process",
        )
        return job_id

    async def schedule_recompile(
        self,
        article_id: str,
        mode: str,
        job_id: str,
        user_id: str,
    ) -> str:
        """Schedule a recompile job for an article.

        Args:
            article_id: The article UUID to recompile.
            mode: "source" or "concept".
            job_id: Pre-created Job record ID.
            user_id: Owner — scopes to this user's data.

        Returns:
            The job ID string.
        """
        if self.is_prod:
            await self._enqueue_arq("recompile_article", article_id, mode, job_id, user_id)
        else:
            asyncio.create_task(  # noqa: RUF006
                self._run_recompile_in_process(article_id, mode, job_id, user_id)
            )

        log.info(
            "recompile scheduled",
            article_id=article_id,
            mode=mode,
            job_id=job_id,
            user_id=user_id,
            dispatch="arq" if self.is_prod else "in-process",
        )
        return job_id

    async def schedule_sweep(self, user_id: str) -> str:
        """Schedule a wikilink resolution sweep job.

        Args:
            user_id: Owner — scopes to this user's data.

        Returns:
            A placeholder job ID string.
        """
        job_id = str(uuid.uuid4())

        if self.is_prod:
            await self._enqueue_arq("sweep_wikilinks", user_id)
        else:
            asyncio.create_task(self._run_sweep_in_process(user_id))  # noqa: RUF006

        log.info(
            "sweep scheduled",
            user_id=user_id,
            mode="arq" if self.is_prod else "in-process",
        )
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
    async def _run_compile_in_process(
        source_id: str,
        user_id: str,
        doc: NormalizedDocument | None = None,
    ) -> None:
        """Run compile_source directly in the current event loop."""
        try:
            await compile_source({}, source_id, user_id=user_id, doc=doc)
        except Exception:  # Intentional broad catch — background task must not crash
            log.exception("in-process compilation failed", source_id=source_id)

    @staticmethod
    async def _run_lint_in_process(user_id: str) -> None:
        """Run lint_wiki directly in the current event loop."""
        try:
            await lint_wiki({}, user_id=user_id)
        except Exception:  # Intentional broad catch — background task must not crash
            log.exception("in-process lint failed")

    @staticmethod
    async def _run_recompile_in_process(article_id: str, mode: str, job_id: str, user_id: str) -> None:
        """Run recompile_article directly in the current event loop."""
        try:
            await recompile_article({}, article_id, mode, job_id, user_id=user_id)
        except Exception:  # Intentional broad catch — background task must not crash
            log.exception("in-process recompile failed", article_id=article_id)

    @staticmethod
    async def _run_sweep_in_process(user_id: str) -> None:
        """Run sweep_wikilinks directly in the current event loop."""
        try:
            await sweep_wikilinks({}, user_id=user_id)
        except Exception:  # Intentional broad catch — background task must not crash
            log.exception("in-process sweep failed")


@functools.lru_cache(maxsize=1)
def get_background_compiler() -> BackgroundCompiler:
    """Return a singleton BackgroundCompiler instance."""
    return BackgroundCompiler()
