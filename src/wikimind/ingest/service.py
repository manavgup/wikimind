"""WikiMind Ingest Service.

Source adapters for all supported input types. Each adapter fetches or reads raw
content, persists a ``Source`` record alongside both the original raw file and a
cleaned ``.txt`` extraction, and returns the source. Compilation is scheduled
separately by the service layer, not by adapters.

File lineage convention (see issue #59):

* Every adapter writes the cleaned text to ``~/.wikimind/raw/{source_id}.txt``
  and points ``Source.file_path`` at it. The compile worker only reads ``.txt``.
* Adapters whose original payload is not already plain text additionally write
  the raw bytes to ``~/.wikimind/raw/{source_id}.{ext}`` (``.html`` for URL,
  ``.pdf`` for PDF). Text and YouTube payloads are already plain text, so the
  raw and clean files are the same ``.txt`` file.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import fitz
import httpx
import structlog
import trafilatura
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from youtube_transcript_api import YouTubeTranscriptApi

from wikimind.config import get_settings
from wikimind.models import DocumentChunk, IngestStatus, NormalizedDocument, Source, SourceType

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Optional Docling integration (issue #57)
#
# Docling is a structured PDF parser that preserves heading hierarchy, tables,
# multi-column layouts, and OCR'd text. It is opt-in via the ``parse-advanced``
# extras group because it pulls in ~500MB of ML models on first use. When
# docling is not installed the PDF adapter falls back to ``fitz`` plain-text
# extraction (the previous behaviour), so the test suite and lightweight
# installs continue to work without modification.
# ---------------------------------------------------------------------------

try:
    from docling.document_converter import DocumentConverter as _DocumentConverter

    _DOCLING_AVAILABLE = True
except ImportError:
    _DocumentConverter = None  # type: ignore[assignment,misc]
    _DOCLING_AVAILABLE = False

# Lazy-initialized singleton converter — instantiating ``DocumentConverter``
# triggers ML model loading (slow, ~500MB), so we defer it until the first PDF
# is actually ingested.
_docling_converter: Any = None


def _get_docling_converter() -> Any:
    """Lazy-initialize the Docling converter singleton.

    Loads the underlying ML models on first call. Subsequent calls return the
    cached converter so model initialization only happens once per process.

    Returns:
        The shared :class:`docling.document_converter.DocumentConverter`
        instance. Typed as :class:`Any` because docling is an optional
        dependency that may not be installed.
    """
    global _docling_converter
    if _docling_converter is None:
        if _DocumentConverter is None:  # pragma: no cover - guarded by caller
            raise RuntimeError("Docling is not installed. Install with: pip install -e '.[parse-advanced]'")
        _docling_converter = _DocumentConverter()
    return _docling_converter


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
# Content-hash deduplication helpers (issue #67)
#
# Each adapter computes a SHA-256 of its raw payload (HTML bytes for URL,
# PDF bytes for PDF, UTF-8 text for Text/YouTube) and consults the database
# before creating a new Source row. A hit short-circuits the rest of the
# adapter — we return the existing source plus a NormalizedDocument
# reconstructed from the cached `.txt` so the caller's contract is
# unchanged.
# ---------------------------------------------------------------------------


def compute_hash(payload: bytes) -> str:
    """Return the SHA-256 hex digest of raw payload bytes.

    Args:
        payload: The raw bytes to hash. For URL/PDF this is the network
            response or upload bytes; for Text/YouTube it is the UTF-8
            encoding of the source string.

    Returns:
        Hex-encoded SHA-256 digest (64 characters).
    """
    return hashlib.sha256(payload).hexdigest()


async def find_source_by_hash(session: AsyncSession, content_hash: str) -> Source | None:
    """Look up an existing :class:`Source` by its content hash.

    Args:
        session: Async database session.
        content_hash: SHA-256 hex digest produced by :func:`compute_hash`.

    Returns:
        The matching `Source`, or ``None`` if no source has this hash.
    """
    result = await session.execute(select(Source).where(Source.content_hash == content_hash))
    return result.scalar_one_or_none()


def reconstruct_normalized_doc(source: Source) -> NormalizedDocument:
    """Rebuild a :class:`NormalizedDocument` from a previously-ingested source.

    Used by the dedup hit path so the adapter's return contract
    (``tuple[Source, NormalizedDocument]``) stays consistent whether the
    source is new or replayed from the cache.

    Args:
        source: A persisted Source whose ``file_path`` points at the
            cached cleaned text on disk.

    Returns:
        A NormalizedDocument loaded from the cached `.txt` file.

    Raises:
        ValueError: If the source has no `file_path` set.
    """
    if not source.file_path:
        raise ValueError(f"Source {source.id} has no file_path; cannot reconstruct NormalizedDocument")
    clean_text = Path(source.file_path).read_text(encoding="utf-8")
    return NormalizedDocument(
        raw_source_id=source.id,
        clean_text=clean_text,
        title=source.title or "Untitled",
        author=source.author,
        published_date=source.published_date,
        estimated_tokens=source.token_count or estimate_tokens(clean_text),
        chunks=chunk_text(clean_text, source.id),
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

        # Dedup: hash the raw HTML response and short-circuit if we've already
        # ingested this exact content (issue #67). We use the HTML bytes — not
        # the cleaned extraction — so the hash is stable across changes to the
        # trafilatura extraction pipeline.
        content_hash = compute_hash(html.encode("utf-8"))
        existing = await find_source_by_hash(session, content_hash)
        if existing is not None:
            log.info("Source dedup hit (URL)", source_id=existing.id, hash=content_hash[:16])
            return existing, reconstruct_normalized_doc(existing)

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
            content_hash=content_hash,
        )
        session.add(source)
        await session.commit()
        await session.refresh(source)

        # Save clean extracted text (used by the compiler worker) and
        # keep the raw HTML alongside it for reference/reprocessing.
        settings = get_settings()
        raw_dir = Path(settings.data_dir) / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / f"{source.id}.html").write_text(html, encoding="utf-8")
        text_path = raw_dir / f"{source.id}.txt"
        text_path.write_text(downloaded, encoding="utf-8")
        source.file_path = str(text_path)

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
    """Adapter for ingesting PDF files.

    Uses :mod:`docling` for structured extraction (heading hierarchy, tables,
    OCR fallback, multi-column layouts) when the ``parse-advanced`` extras
    group is installed. Falls back to plain-text extraction via
    :mod:`fitz` (pymupdf) when docling is not available, preserving the
    behaviour the project shipped with before issue #57.

    Both branches honour the dual-file lineage convention from issue #59: the
    raw ``.pdf`` bytes are written to ``~/.wikimind/raw/{source_id}.pdf`` and
    the cleaned extraction is written to ``~/.wikimind/raw/{source_id}.txt``,
    with ``Source.file_path`` pointing at the latter.
    """

    async def ingest(
        self,
        file_bytes: bytes,
        filename: str,
        session: AsyncSession,
    ) -> tuple[Source, NormalizedDocument]:
        """Ingest a PDF file and return source and normalized document.

        Args:
            file_bytes: Raw PDF binary contents.
            filename: Original upload filename, used for the source title.
            session: Async database session.

        Returns:
            A tuple of the persisted :class:`Source` row and the in-memory
            :class:`NormalizedDocument` ready for compilation.
        """
        extractor = "docling" if _DOCLING_AVAILABLE else "fitz"
        log.info("Ingesting PDF", filename=filename, extractor=extractor)

        # Dedup: hash the raw PDF bytes and short-circuit if we've already
        # ingested this exact file (issue #67). The hash is computed before
        # any LLM work or extraction so re-uploads are essentially free.
        content_hash = compute_hash(file_bytes)
        existing = await find_source_by_hash(session, content_hash)
        if existing is not None:
            log.info("Source dedup hit (PDF)", source_id=existing.id, hash=content_hash[:16])
            return existing, reconstruct_normalized_doc(existing)

        # Create source record
        source = Source(
            source_type=SourceType.PDF,
            title=filename.replace(".pdf", ""),
            status=IngestStatus.PROCESSING,
            content_hash=content_hash,
        )
        session.add(source)
        await session.commit()
        await session.refresh(source)

        # Save the raw PDF binary alongside the extracted plain text. The
        # worker only ever reads the .txt file (see issue #59), so file_path
        # always points at the cleaned text. The raw .pdf is kept for lineage
        # and future re-extraction (e.g. Docling — see issue #57).
        settings = get_settings()
        raw_dir = Path(settings.data_dir) / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_pdf_path = raw_dir / f"{source.id}.pdf"
        raw_pdf_path.write_bytes(file_bytes)

        # Extract text — prefer Docling for structured output (markdown with
        # heading hierarchy, table-aware), fall back to fitz plain text when
        # docling is not installed.
        if _DOCLING_AVAILABLE:
            clean_text, page_count = self._extract_via_docling(raw_pdf_path)
        else:
            clean_text, page_count = self._extract_via_fitz(file_bytes)

        text_path = raw_dir / f"{source.id}.txt"
        text_path.write_text(clean_text, encoding="utf-8")
        source.file_path = str(text_path)

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

        log.info(
            "PDF ingested",
            title=source.title,
            tokens=token_count,
            pages=page_count,
            extractor=extractor,
        )
        return source, normalized

    @staticmethod
    def _extract_via_fitz(file_bytes: bytes) -> tuple[str, int]:
        """Extract plain text from a PDF using :mod:`fitz` (pymupdf).

        This is the fallback path used when docling is not installed. It
        produces the exact same output the adapter shipped with prior to
        issue #57 — pages joined with a blank line.

        Args:
            file_bytes: Raw PDF binary contents.

        Returns:
            A tuple of ``(cleaned_text, page_count)``.
        """
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        pages_text: list[str] = [str(page.get_text()) for page in doc]
        doc.close()
        return "\n\n".join(pages_text), len(pages_text)

    @staticmethod
    def _extract_via_docling(raw_pdf_path: Path) -> tuple[str, int]:
        """Extract structured markdown from a PDF using :mod:`docling`.

        Docling preserves heading hierarchy, tables, multi-column layouts,
        and OCR'd text in images. The result is markdown — a strict
        improvement over fitz plain text for slide decks and academic papers.

        Args:
            raw_pdf_path: Path to the saved raw PDF on disk. Docling reads
                from a path rather than a byte stream.

        Returns:
            A tuple of ``(markdown_text, page_count)``.
        """
        converter = _get_docling_converter()
        result = converter.convert(str(raw_pdf_path))
        markdown = result.document.export_to_markdown()
        # Docling exposes pages on the document; fall back to 0 if the
        # attribute is missing on a future release.
        pages = getattr(result.document, "pages", None)
        page_count = len(pages) if pages is not None else 0
        return markdown, page_count


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

        # Dedup: hash the UTF-8 bytes of the pasted content (issue #67).
        # Title differences do NOT contribute — re-pasting the same body
        # under a new title still hits the dedup.
        content_hash = compute_hash(content.encode("utf-8"))
        existing = await find_source_by_hash(session, content_hash)
        if existing is not None:
            log.info("Source dedup hit (text)", source_id=existing.id, hash=content_hash[:16])
            return existing, reconstruct_normalized_doc(existing)

        source = Source(
            source_type=SourceType.TEXT,
            title=title or "Untitled Note",
            status=IngestStatus.PROCESSING,
            token_count=estimate_tokens(content),
            content_hash=content_hash,
        )
        session.add(source)
        await session.commit()
        await session.refresh(source)

        # Pasted text is already plain text, so the raw and cleaned files are
        # the same .txt file. file_path always points at the .txt the worker
        # reads (see issue #59).
        settings = get_settings()
        raw_dir = Path(settings.data_dir) / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        text_path = raw_dir / f"{source.id}.txt"
        text_path.write_text(content, encoding="utf-8")
        source.file_path = str(text_path)
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

        # Dedup: hash the assembled transcript (issue #67). YouTube transcripts
        # are stable for a given video so the hash is effectively a video-id
        # alias, but hashing the actual content also catches the (rare) case
        # where the same transcript appears under multiple URLs.
        content_hash = compute_hash(transcript_text.encode("utf-8"))
        existing = await find_source_by_hash(session, content_hash)
        if existing is not None:
            log.info("Source dedup hit (YouTube)", source_id=existing.id, hash=content_hash[:16])
            return existing, reconstruct_normalized_doc(existing)

        source = Source(
            source_type=SourceType.YOUTUBE,
            source_url=url,
            title=f"YouTube: {video_id}",  # Will be enriched later
            status=IngestStatus.PROCESSING,
            token_count=estimate_tokens(transcript_text),
            content_hash=content_hash,
        )
        session.add(source)
        await session.commit()
        await session.refresh(source)

        # YouTube transcripts are already plain text, so the raw and cleaned
        # files are the same .txt. There is no separate raw video payload.
        settings = get_settings()
        raw_dir = Path(settings.data_dir) / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        text_path = raw_dir / f"{source.id}.txt"
        text_path.write_text(transcript_text, encoding="utf-8")
        source.file_path = str(text_path)
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
        """Ingest a URL, routing to the appropriate adapter.

        Routing order:
        1. YouTube URLs -> YouTubeAdapter
        2. PDF URLs (path ends with ``.pdf`` or Content-Type is
           ``application/pdf``) -> download bytes, delegate to PDFAdapter
        3. Everything else -> URLAdapter (trafilatura HTML extraction)
        """
        if "youtube.com" in url or "youtu.be" in url:
            source, _doc = await self.youtube_adapter.ingest(url, session)
            return source

        if self._looks_like_pdf_url(url):
            return await self._ingest_pdf_url(url, session)

        return await self._ingest_html_url_with_pdf_fallback(url, session)

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

    async def _ingest_pdf_url(self, url: str, session: AsyncSession) -> Source:
        """Download a PDF from *url* and delegate to :class:`PDFAdapter`."""
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            response = await client.get(
                url,
                headers={"User-Agent": "WikiMind/0.1 (knowledge compiler)"},
            )
            response.raise_for_status()

        filename = Path(urlparse(url).path).name or "download.pdf"
        source, _doc = await self.pdf_adapter.ingest(response.content, filename, session)
        source.source_url = url
        session.add(source)
        await session.commit()
        return source

    async def _ingest_html_url_with_pdf_fallback(self, url: str, session: AsyncSession) -> Source:
        """Fetch a URL; if the response is a PDF, fall back to the PDF adapter.

        Some PDF URLs lack a ``.pdf`` extension (e.g. behind a CDN or
        download gateway). We detect ``application/pdf`` in the
        ``Content-Type`` header and re-route accordingly.
        """
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
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
            source, _doc = await self.pdf_adapter.ingest(response.content, filename, session)
            source.source_url = url
            session.add(source)
            await session.commit()
            return source

        # Normal HTML path — delegate to the URL adapter which does its
        # own fetch. We cannot easily reuse the response we already have
        # because URLAdapter.ingest() encapsulates the full fetch+extract
        # pipeline. The overhead of a second fetch is acceptable for the
        # non-PDF case.
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
