"""WikiMind Ingest Service — orchestrates adapters for all source types.

Adapters save the source and return immediately. Compilation is scheduled
separately by the outer service layer (see ``wikimind.services.ingest``).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx

from wikimind.config import get_settings
from wikimind.ingest.adapters.pdf import PDFAdapter
from wikimind.ingest.adapters.text import TextAdapter
from wikimind.ingest.adapters.url import URLAdapter
from wikimind.ingest.adapters.youtube import YouTubeAdapter
from wikimind.ingest.utils import is_youtube_url, validate_url_host

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from wikimind.models import NormalizedDocument, Source


class IngestService:
    """Orchestrate ingestion across all adapters.

    Adapters save the source and return immediately. Compilation is scheduled
    separately by the outer service layer (see ``wikimind.services.ingest``).
    """

    def __init__(self):
        self.url_adapter = URLAdapter()
        self.pdf_adapter = PDFAdapter()
        self.text_adapter = TextAdapter()
        self.youtube_adapter = YouTubeAdapter()

    async def ingest_url(
        self,
        url: str,
        session: AsyncSession,
        user_id: str,
    ) -> tuple[Source, NormalizedDocument]:
        """Ingest a URL, routing to the appropriate adapter.

        Routing order:
        1. YouTube URLs -> YouTubeAdapter
        2. PDF URLs (path ends with ``.pdf`` or Content-Type is
           ``application/pdf``) -> download bytes, delegate to PDFAdapter
        3. Everything else -> URLAdapter (trafilatura HTML extraction)
        """
        # SSRF protection: reject URLs that resolve to private/loopback
        validate_url_host(url)

        if is_youtube_url(url):
            return await self.youtube_adapter.ingest(url, session, user_id=user_id)

        if self._looks_like_pdf_url(url):
            return await self._ingest_pdf_url(url, session, user_id=user_id)

        return await self._ingest_html_url_with_pdf_fallback(url, session, user_id=user_id)

    # ------------------------------------------------------------------
    # Private helpers for PDF-URL routing
    # ------------------------------------------------------------------

    @staticmethod
    def _looks_like_pdf_url(url: str) -> bool:
        """Return ``True`` if the URL path ends with ``.pdf`` (case-insensitive).

        Query parameters and fragments are stripped before checking.
        """
        path = urlparse(url).path
        return path.lower().endswith(".pdf")

    async def _ingest_pdf_url(
        self,
        url: str,
        session: AsyncSession,
        user_id: str,
    ) -> tuple[Source, NormalizedDocument]:
        """Download a PDF from *url* and delegate to :class:`PDFAdapter`."""
        timeout = get_settings().ingest.http_timeout_seconds
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
            response = await client.get(
                url,
                headers={"User-Agent": "WikiMind/0.1 (knowledge compiler)"},
            )
            response.raise_for_status()

        filename = Path(urlparse(url).path).name or "download.pdf"
        source, doc = await self.pdf_adapter.ingest(response.content, filename, session, user_id=user_id)
        source.source_url = url
        session.add(source)
        await session.commit()
        return source, doc

    async def _ingest_html_url_with_pdf_fallback(
        self,
        url: str,
        session: AsyncSession,
        user_id: str,
    ) -> tuple[Source, NormalizedDocument]:
        """Fetch a URL; if the response is a PDF, fall back to the PDF adapter.

        Some PDF URLs lack a ``.pdf`` extension (e.g. behind a CDN or
        download gateway). We detect ``application/pdf`` in the
        ``Content-Type`` header and re-route accordingly.
        """
        timeout = get_settings().ingest.http_timeout_seconds
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
            response = await client.get(
                url,
                headers={"User-Agent": "WikiMind/0.1 (knowledge compiler)"},
            )
            response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        if "application/pdf" in content_type:
            filename = Path(urlparse(url).path).name or "download.pdf"
            if not filename.lower().endswith(".pdf"):
                filename += ".pdf"
            source, doc = await self.pdf_adapter.ingest(response.content, filename, session, user_id=user_id)
            source.source_url = url
            session.add(source)
            await session.commit()
            return source, doc

        # Normal HTML path — delegate to the URL adapter which does its
        # own fetch. We cannot easily reuse the response we already have
        # because URLAdapter.ingest() encapsulates the full fetch+extract
        # pipeline. The overhead of a second fetch is acceptable for the
        # non-PDF case.
        return await self.url_adapter.ingest(url, session, user_id=user_id)

    async def ingest_pdf(
        self,
        file_bytes: bytes,
        filename: str,
        session: AsyncSession,
        user_id: str,
    ) -> tuple[Source, NormalizedDocument]:
        """Ingest a PDF file."""
        return await self.pdf_adapter.ingest(file_bytes, filename, session, user_id=user_id)

    async def ingest_text(
        self,
        content: str,
        title: str | None,
        session: AsyncSession,
        user_id: str,
    ) -> tuple[Source, NormalizedDocument]:
        """Ingest raw text content."""
        return await self.text_adapter.ingest(content, title, session, user_id=user_id)


__all__ = [
    "IngestService",
    "PDFAdapter",
    "TextAdapter",
    "URLAdapter",
    "YouTubeAdapter",
    "is_youtube_url",
    "validate_url_host",
]
