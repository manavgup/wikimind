"""WikiMind Ingest Service.

Source adapters for all supported input types. Each adapter fetches or reads raw
content, persists a Source record and raw file, and returns the Source. Compilation
is scheduled separately by the service layer, not by adapters.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import fitz
import httpx
import structlog
import trafilatura
from sqlmodel.ext.asyncio.session import AsyncSession
from youtube_transcript_api import YouTubeTranscriptApi

from wikimind.config import get_settings
from wikimind.models import DocumentChunk, IngestStatus, NormalizedDocument, Source, SourceType

log = structlog.get_logger()


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return len(text) // 4


def chunk_text(text: str, doc_id: str, max_chunk_tokens: int = 4000) -> list[DocumentChunk]:
    """Split text into semantic chunks preserving heading structure."""
    chunks: list[DocumentChunk] = []
    current_headings: list[str] = []

    # Split on headings
    sections = re.split(r"(#{1,3} .+)", text)
    current_content = []
    chunk_index = 0

    for section in sections:
        heading_match = re.match(r"(#{1,3}) (.+)", section)
        if heading_match:
            level = len(heading_match.group(1))
            heading_text = heading_match.group(2).strip()
            # Update heading path
            current_headings = [*current_headings[: level - 1], heading_text]
        else:
            current_content.append(section)

        # Flush chunk if large enough
        content = "\n".join(current_content).strip()
        if estimate_tokens(content) >= max_chunk_tokens and content:
            chunks.append(
                DocumentChunk(
                    document_id=doc_id,
                    content=content,
                    heading_path=list(current_headings),
                    token_count=estimate_tokens(content),
                    chunk_index=chunk_index,
                )
            )
            chunk_index += 1
            current_content = []

    # Final chunk
    content = "\n".join(current_content).strip()
    if content:
        chunks.append(
            DocumentChunk(
                document_id=doc_id,
                content=content,
                heading_path=list(current_headings),
                token_count=estimate_tokens(content),
                chunk_index=chunk_index,
            )
        )

    return (
        chunks
        if chunks
        else [
            DocumentChunk(
                document_id=doc_id,
                content=text,
                heading_path=[],
                token_count=estimate_tokens(text),
                chunk_index=0,
            )
        ]
    )


# ---------------------------------------------------------------------------
# URL Adapter
# ---------------------------------------------------------------------------


class URLAdapter:
    """Adapter for ingesting web URLs."""

    async def ingest(self, url: str, session: AsyncSession) -> tuple[Source, NormalizedDocument]:
        """Ingest a web URL and return source and normalized document."""
        log.info("Ingesting URL", url=url)

        # Fetch page
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            response = await client.get(url, headers={"User-Agent": "WikiMind/0.1 (knowledge compiler)"})
            response.raise_for_status()
            html = response.text

        # Extract article text
        downloaded = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            output_format="markdown",
            with_metadata=True,
        )

        if not downloaded:
            raise ValueError(f"Could not extract content from {url}")

        # Parse metadata
        meta = trafilatura.extract_metadata(html)
        title = (meta.title if meta else None) or urlparse(url).netloc
        author = meta.author if meta else None

        # Create source record
        source = Source(
            source_type=SourceType.URL,
            source_url=url,
            title=title,
            author=author,
            status=IngestStatus.PROCESSING,
        )
        session.add(source)
        await session.commit()
        await session.refresh(source)

        # Save raw file
        settings = get_settings()
        raw_path = Path(settings.data_dir) / "raw" / f"{source.id}.html"
        raw_path.write_text(html, encoding="utf-8")
        source.file_path = str(raw_path)

        # Normalize
        clean_text = downloaded
        token_count = estimate_tokens(clean_text)
        source.token_count = token_count
        session.add(source)
        await session.commit()

        doc = NormalizedDocument(
            raw_source_id=source.id,
            clean_text=clean_text,
            title=title,
            author=author,
            estimated_tokens=token_count,
            chunks=chunk_text(clean_text, source.id),
        )

        log.info("URL ingested", title=title, tokens=token_count)
        return source, doc


# ---------------------------------------------------------------------------
# PDF Adapter
# ---------------------------------------------------------------------------


class PDFAdapter:
    """Adapter for ingesting PDF files."""

    async def ingest(
        self,
        file_bytes: bytes,
        filename: str,
        session: AsyncSession,
    ) -> tuple[Source, NormalizedDocument]:
        """Ingest a PDF file and return source and normalized document."""
        log.info("Ingesting PDF", filename=filename)

        # Create source record
        source = Source(
            source_type=SourceType.PDF,
            title=filename.replace(".pdf", ""),
            status=IngestStatus.PROCESSING,
        )
        session.add(source)
        await session.commit()
        await session.refresh(source)

        # Save raw file
        settings = get_settings()
        raw_path = Path(settings.data_dir) / "raw" / f"{source.id}.pdf"
        raw_path.write_bytes(file_bytes)
        source.file_path = str(raw_path)

        # Extract text — plain text is the most reliable format across PDFs
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        pages_text: list[str] = [str(page.get_text()) for page in doc]
        doc.close()

        clean_text = "\n\n".join(pages_text)
        token_count = estimate_tokens(clean_text)
        source.token_count = token_count
        session.add(source)
        await session.commit()

        normalized = NormalizedDocument(
            raw_source_id=source.id,
            clean_text=clean_text,
            title=source.title or "Untitled",
            estimated_tokens=token_count or 0,
            chunks=chunk_text(clean_text, source.id),
        )

        log.info("PDF ingested", title=source.title, tokens=token_count, pages=len(pages_text))
        return source, normalized


# ---------------------------------------------------------------------------
# Text Adapter (paste / direct input)
# ---------------------------------------------------------------------------


class TextAdapter:
    """Adapter for ingesting raw text."""

    async def ingest(
        self,
        content: str,
        title: str | None,
        session: AsyncSession,
    ) -> tuple[Source, NormalizedDocument]:
        """Ingest raw text and return source and normalized document."""
        log.info("Ingesting text", title=title, chars=len(content))

        source = Source(
            source_type=SourceType.TEXT,
            title=title or "Untitled Note",
            status=IngestStatus.PROCESSING,
            token_count=estimate_tokens(content),
        )
        session.add(source)
        await session.commit()
        await session.refresh(source)

        # Save raw
        settings = get_settings()
        raw_path = Path(settings.data_dir) / "raw" / f"{source.id}.txt"
        raw_path.write_text(content, encoding="utf-8")
        source.file_path = str(raw_path)
        session.add(source)
        await session.commit()

        doc = NormalizedDocument(
            raw_source_id=source.id,
            clean_text=content,
            title=source.title or "Untitled Note",
            estimated_tokens=source.token_count or 0,
            chunks=chunk_text(content, source.id),
        )

        return source, doc


# ---------------------------------------------------------------------------
# YouTube Adapter
# ---------------------------------------------------------------------------


class YouTubeAdapter:
    """Adapter for ingesting YouTube videos."""

    async def ingest(self, url: str, session: AsyncSession) -> tuple[Source, NormalizedDocument]:
        """Ingest a YouTube video transcript."""
        log.info("Ingesting YouTube", url=url)

        # Extract video ID
        video_id = self._extract_video_id(url)
        if not video_id:
            raise ValueError(f"Could not extract YouTube video ID from {url}")

        # Fetch transcript
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)  # type: ignore[attr-defined]
        transcript_text = " ".join([t["text"] for t in transcript_list])

        source = Source(
            source_type=SourceType.YOUTUBE,
            source_url=url,
            title=f"YouTube: {video_id}",  # Will be enriched later
            status=IngestStatus.PROCESSING,
            token_count=estimate_tokens(transcript_text),
        )
        session.add(source)
        await session.commit()
        await session.refresh(source)

        settings = get_settings()
        raw_path = Path(settings.data_dir) / "raw" / f"{source.id}.txt"
        raw_path.write_text(transcript_text, encoding="utf-8")
        source.file_path = str(raw_path)
        session.add(source)
        await session.commit()

        doc = NormalizedDocument(
            raw_source_id=source.id,
            clean_text=transcript_text,
            title=source.title or "YouTube Video",
            estimated_tokens=source.token_count or 0,
            chunks=chunk_text(transcript_text, source.id),
        )

        return source, doc

    def _extract_video_id(self, url: str) -> str | None:
        patterns = [
            r"(?:youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]{11})",
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None


# ---------------------------------------------------------------------------
# Ingest Service (orchestrates adapters)
# ---------------------------------------------------------------------------


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

    async def ingest_url(self, url: str, session: AsyncSession) -> Source:
        """Ingest a URL, routing to the appropriate adapter."""
        if "youtube.com" in url or "youtu.be" in url:
            source, _doc = await self.youtube_adapter.ingest(url, session)
        else:
            source, _doc = await self.url_adapter.ingest(url, session)

        return source

    async def ingest_pdf(self, file_bytes: bytes, filename: str, session: AsyncSession) -> Source:
        """Ingest a PDF file."""
        source, _doc = await self.pdf_adapter.ingest(file_bytes, filename, session)
        return source

    async def ingest_text(self, content: str, title: str | None, session: AsyncSession) -> Source:
        """Ingest raw text content."""
        source, _doc = await self.text_adapter.ingest(content, title, session)
        return source
