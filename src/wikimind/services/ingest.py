"""Orchestrate source ingestion across URL, PDF, text, and YouTube adapters.

Routes delegate to this service for all ingest operations. The service
coordinates adapter selection, source persistence, and background compilation
scheduling via ``BackgroundCompiler``. It also owns the lifecycle of the raw
and cleaned files written by adapters under ``~/.wikimind/raw/`` (see issue
#59) and removes them on delete.
"""

import functools
from contextlib import suppress

import httpx
import structlog
from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.ingest.service import IngestService as IngestAdapter
from wikimind.jobs.background import get_background_compiler
from wikimind.models import NormalizedDocument, Source
from wikimind.services.activity_log import append_log_entry
from wikimind.storage import resolve_raw_path

log = structlog.get_logger()


class IngestService:
    """Orchestrate source ingestion and background compilation scheduling."""

    def __init__(self) -> None:
        self._adapter = IngestAdapter()

    async def ingest_url(
        self,
        url: str,
        session: AsyncSession,
        *,
        auto_compile: bool = True,
        user_id: str | None = None,
    ) -> Source:
        """Ingest a URL (web page or YouTube) and optionally schedule compilation.

        Args:
            url: The URL to ingest.
            session: Async database session.
            auto_compile: When ``True`` (default), schedule background compilation
                immediately after persisting the source. When ``False``, persist
                only — the caller can compile later via the compile API.
            user_id: Optional user ID for data isolation.

        Returns:
            The persisted Source record.

        Raises:
            HTTPException: If ingestion fails due to invalid input or network error.
        """
        try:
            source, doc = await self._adapter.ingest_url(url, session, user_id=user_id)
        except (httpx.HTTPError, ValueError, OSError) as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        self._log_ingest(source)

        if auto_compile:
            await self._schedule_compile(source, doc)
        return source

    async def ingest_pdf(
        self,
        file_bytes: bytes,
        filename: str,
        session: AsyncSession,
        *,
        auto_compile: bool = True,
        user_id: str | None = None,
    ) -> Source:
        """Ingest a PDF file and optionally schedule compilation.

        Args:
            file_bytes: Raw PDF bytes.
            filename: Original filename.
            session: Async database session.
            auto_compile: When ``True`` (default), schedule background compilation
                immediately after persisting the source. When ``False``, persist
                only.
            user_id: Optional user ID for data isolation.

        Returns:
            The persisted Source record.
        """
        source, doc = await self._adapter.ingest_pdf(file_bytes, filename, session, user_id=user_id)
        self._log_ingest(source)

        if auto_compile:
            await self._schedule_compile(source, doc)
        return source

    async def ingest_text(
        self,
        content: str,
        title: str | None,
        session: AsyncSession,
        *,
        auto_compile: bool = True,
        user_id: str | None = None,
    ) -> Source:
        """Ingest raw text content and optionally schedule compilation.

        Args:
            content: The text content to ingest.
            title: Optional title for the source.
            session: Async database session.
            auto_compile: When ``True`` (default), schedule background compilation
                immediately after persisting the source. When ``False``, persist
                only.
            user_id: Optional user ID for data isolation.

        Returns:
            The persisted Source record.
        """
        source, doc = await self._adapter.ingest_text(content, title, session, user_id=user_id)
        self._log_ingest(source)

        if auto_compile:
            await self._schedule_compile(source, doc)
        return source

    @staticmethod
    def _log_ingest(source: Source) -> None:
        """Write an ingest entry to the activity log, swallowing failures."""
        try:
            append_log_entry(
                "ingest",
                source.title or "untitled",
                extra={"source_type": source.source_type, "source_url": source.source_url},
            )
        except OSError:
            log.warning("activity log write failed", op="ingest", source_id=source.id)

    @staticmethod
    async def _schedule_compile(
        source: Source,
        doc: NormalizedDocument | None = None,
    ) -> None:
        """Schedule background compilation, unless the source is already compiled.

        A content-hash dedup hit (#67) returns a Source whose ``compiled_at``
        is already set — re-running the compiler would just produce identical
        output and burn LLM tokens. We skip the enqueue in that case so the
        whole point of dedup (no wasted work) actually holds end-to-end.

        When *doc* is provided, it is forwarded to the in-process compiler
        so the worker does not need to re-read and re-chunk the source file.
        In the ARQ (Redis) path, *doc* is not serializable and is ignored —
        the worker falls back to reading from disk.

        Args:
            source: The Source returned by an adapter (new or dedup hit).
            doc: The NormalizedDocument already produced by the adapter.
        """
        if source.compiled_at is not None:
            log.info(
                "compile skipped (dedup hit, already compiled)",
                source_id=source.id,
                compiled_at=source.compiled_at.isoformat(),
            )
            return
        compiler = get_background_compiler()
        await compiler.schedule_compile(source.id, user_id=source.user_id, doc=doc)
        log.info("compilation scheduled", source_id=source.id)

    async def list_sources(
        self,
        session: AsyncSession,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
        user_id: str | None = None,
    ) -> list[Source]:
        """List ingested sources with optional status filtering.

        Args:
            session: Async database session.
            status: Optional status filter.
            limit: Maximum number of results.
            offset: Pagination offset.
            user_id: Optional user ID filter.

        Returns:
            List of Source records.
        """
        query = select(Source).offset(offset).limit(limit)
        if user_id:
            query = query.where(Source.user_id == user_id)
        if status:
            query = query.where(Source.status == status)
        result = await session.execute(query)
        return list(result.scalars().all())

    async def get_source(
        self,
        source_id: str,
        session: AsyncSession,
        user_id: str | None = None,
    ) -> Source:
        """Retrieve a single source by ID.

        Args:
            source_id: The source UUID.
            session: Async database session.
            user_id: When provided, verify the source belongs to this user.

        Returns:
            The Source record.

        Raises:
            HTTPException: If the source is not found or doesn't belong to the user.
        """
        source = await session.get(Source, source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")
        if user_id and source.user_id != user_id:
            raise HTTPException(status_code=404, detail="Source not found")
        return source

    async def delete_source(
        self,
        source_id: str,
        session: AsyncSession,
        user_id: str | None = None,
    ) -> dict[str, str]:
        """Delete a source by ID and remove its raw and cleaned files from disk.

        Adapters write a cleaned ``{id}.txt`` and may also write a sibling raw
        file (``{id}.html`` for URL, ``{id}.pdf`` for PDF). Both are removed
        when the source is deleted so the raw directory does not accumulate
        orphaned files. Missing files are tolerated — deletion of the database
        row is the source of truth.

        Args:
            source_id: The source UUID.
            session: Async database session.
            user_id: When provided, verify the source belongs to this user.

        Returns:
            Confirmation dict with the deleted ID.

        Raises:
            HTTPException: If the source is not found or doesn't belong to the user.
        """
        source = await session.get(Source, source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")
        if user_id and source.user_id != user_id:
            raise HTTPException(status_code=404, detail="Source not found")

        self._remove_source_files(source)

        await session.delete(source)
        await session.commit()
        return {"deleted": source_id}

    @staticmethod
    def _remove_source_files(source: Source) -> None:
        """Remove the cleaned ``.txt`` file and any sibling raw file for a source.

        The cleaned file path is resolved via ``resolve_raw_path()`` which
        scopes to the user's directory when ``user_id`` is set. The raw
        sibling is discovered by scanning the same directory for files sharing
        the ``{source_id}`` stem (e.g. ``{id}.pdf``, ``{id}.html``). Missing
        files are silently ignored — this method is best-effort cleanup.
        """
        if source.file_path:
            resolved = resolve_raw_path(source.file_path, user_id=source.user_id)
            with suppress(OSError):
                resolved.unlink(missing_ok=True)

        # Resolve the user-scoped raw directory to find sibling files
        raw_dir = resolve_raw_path(f"{source.id}.txt", user_id=source.user_id).parent
        if not raw_dir.is_dir():
            return
        for sibling in raw_dir.glob(f"{source.id}.*"):
            with suppress(OSError):
                sibling.unlink(missing_ok=True)


@functools.lru_cache(maxsize=1)
def get_ingest_service() -> IngestService:
    """Return a singleton IngestService instance for FastAPI dependency injection."""
    return IngestService()
