"""Orchestrate source ingestion across URL, PDF, text, and YouTube adapters.

Routes delegate to this service for all ingest operations. The service
coordinates adapter selection, source persistence, and compilation enqueue.
"""

from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.ingest.service import IngestService as IngestAdapter
from wikimind.models import Source


class IngestService:
    """Orchestrate source ingestion and compilation enqueue."""

    def __init__(self) -> None:
        self._adapter = IngestAdapter()

    async def ingest_url(self, url: str, session: AsyncSession) -> Source:
        """Ingest a URL (web page or YouTube) and enqueue compilation.

        Args:
            url: The URL to ingest.
            session: Async database session.

        Returns:
            The persisted Source record.

        Raises:
            HTTPException: If ingestion fails due to invalid input or network error.
        """
        try:
            return await self._adapter.ingest_url(url, session)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    async def ingest_pdf(self, file_bytes: bytes, filename: str, session: AsyncSession) -> Source:
        """Ingest a PDF file and enqueue compilation.

        Args:
            file_bytes: Raw PDF bytes.
            filename: Original filename.
            session: Async database session.

        Returns:
            The persisted Source record.
        """
        return await self._adapter.ingest_pdf(file_bytes, filename, session)

    async def ingest_text(self, content: str, title: str | None, session: AsyncSession) -> Source:
        """Ingest raw text content and enqueue compilation.

        Args:
            content: The text content to ingest.
            title: Optional title for the source.
            session: Async database session.

        Returns:
            The persisted Source record.
        """
        return await self._adapter.ingest_text(content, title, session)

    async def list_sources(
        self, session: AsyncSession, status: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[Source]:
        """List ingested sources with optional status filtering.

        Args:
            session: Async database session.
            status: Optional status filter.
            limit: Maximum number of results.
            offset: Pagination offset.

        Returns:
            List of Source records.
        """
        query = select(Source).offset(offset).limit(limit)
        if status:
            query = query.where(Source.status == status)
        result = await session.execute(query)
        return list(result.scalars().all())

    async def get_source(self, source_id: str, session: AsyncSession) -> Source:
        """Retrieve a single source by ID.

        Args:
            source_id: The source UUID.
            session: Async database session.

        Returns:
            The Source record.

        Raises:
            HTTPException: If the source is not found.
        """
        source = await session.get(Source, source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")
        return source

    async def delete_source(self, source_id: str, session: AsyncSession) -> dict[str, str]:
        """Delete a source by ID.

        Args:
            source_id: The source UUID.
            session: Async database session.

        Returns:
            Confirmation dict with the deleted ID.

        Raises:
            HTTPException: If the source is not found.
        """
        source = await session.get(Source, source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")
        await session.delete(source)
        await session.commit()
        return {"deleted": source_id}


_ingest_service: IngestService | None = None


def get_ingest_service() -> IngestService:
    """Return a singleton IngestService instance for FastAPI dependency injection."""
    global _ingest_service
    if _ingest_service is None:
        _ingest_service = IngestService()
    return _ingest_service
