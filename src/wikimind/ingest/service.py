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

import asyncio
import base64
import hashlib
import re
from datetime import date
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import urlparse

import fitz
import httpx
import structlog
import trafilatura
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from youtube_transcript_api import YouTubeTranscriptApi

from wikimind.api.routes.ws import emit_source_progress
from wikimind.config import get_settings
from wikimind.engine.llm_router import get_llm_router
from wikimind.models import (
    DocumentChunk,
    IngestStatus,
    NormalizedDocument,
    Source,
    SourceType,
    TaskType,
)

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Docling integration (issue #57)
#
# Docling is a structured document parser that preserves heading hierarchy,
# tables, multi-column layouts, and OCR'd text. It is a core dependency
# (installed by default). The PDF adapter falls back to ``fitz`` plain-text
# extraction only if the import fails (e.g. in a stripped-down CI image).
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
            raise RuntimeError("Docling is not installed. Install with: pip install -e '.[dev]'")
        _docling_converter = _DocumentConverter()
    return _docling_converter


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return len(text) // 4


def _split_by_paragraphs(
    text: str,
    doc_id: str,
    heading_path: list[str],
    max_chunk_tokens: int,
    start_index: int,
) -> list[DocumentChunk]:
    """Split text on paragraph boundaries (double newlines).

    If any resulting paragraph still exceeds *max_chunk_tokens*, it is
    further split using :func:`_split_by_token_window`.

    Args:
        text: The text to split.
        doc_id: Document ID for the chunks.
        heading_path: Heading path to assign to each chunk.
        max_chunk_tokens: Maximum tokens per chunk.
        start_index: Starting chunk_index for numbering.

    Returns:
        A list of :class:`DocumentChunk` instances, each within the token limit.
    """
    paragraphs = re.split(r"\n\n+", text)
    chunks: list[DocumentChunk] = []
    current_parts: list[str] = []
    chunk_index = start_index

    for para in paragraphs:
        candidate = "\n\n".join([*current_parts, para]).strip()
        if estimate_tokens(candidate) > max_chunk_tokens and current_parts:
            # Flush accumulated paragraphs
            content = "\n\n".join(current_parts).strip()
            if estimate_tokens(content) > max_chunk_tokens:
                sub = _split_by_token_window(content, doc_id, heading_path, max_chunk_tokens, chunk_index)
                chunks.extend(sub)
                chunk_index += len(sub)
            else:
                chunks.append(
                    DocumentChunk(
                        document_id=doc_id,
                        content=content,
                        heading_path=list(heading_path),
                        token_count=estimate_tokens(content),
                        chunk_index=chunk_index,
                    )
                )
                chunk_index += 1
            current_parts = [para]
        else:
            current_parts.append(para)

    # Flush remaining
    if current_parts:
        content = "\n\n".join(current_parts).strip()
        if content:
            if estimate_tokens(content) > max_chunk_tokens:
                sub = _split_by_token_window(content, doc_id, heading_path, max_chunk_tokens, chunk_index)
                chunks.extend(sub)
            else:
                chunks.append(
                    DocumentChunk(
                        document_id=doc_id,
                        content=content,
                        heading_path=list(heading_path),
                        token_count=estimate_tokens(content),
                        chunk_index=chunk_index,
                    )
                )

    return chunks


def _split_by_token_window(
    text: str,
    doc_id: str,
    heading_path: list[str],
    max_chunk_tokens: int,
    start_index: int,
) -> list[DocumentChunk]:
    """Split text into fixed token-sized windows on the nearest whitespace.

    This is the last-resort fallback when neither heading-based nor
    paragraph-based splitting produces chunks within the token limit.

    Args:
        text: The text to split.
        doc_id: Document ID for the chunks.
        heading_path: Heading path to assign to each chunk.
        max_chunk_tokens: Maximum tokens per chunk.
        start_index: Starting chunk_index for numbering.

    Returns:
        A list of :class:`DocumentChunk` instances, each within the token limit.
    """
    # Convert token limit to an approximate character budget.
    max_chars = max_chunk_tokens * 4
    chunks: list[DocumentChunk] = []
    chunk_index = start_index
    pos = 0

    while pos < len(text):
        end = min(pos + max_chars, len(text))
        if end < len(text):
            # Walk back to nearest whitespace so we don't split mid-word.
            split_at = text.rfind(" ", pos, end)
            if split_at <= pos:
                # No whitespace found — hard split at max_chars.
                split_at = end
            end = split_at

        content = text[pos:end].strip()
        if content:
            chunks.append(
                DocumentChunk(
                    document_id=doc_id,
                    content=content,
                    heading_path=list(heading_path),
                    token_count=estimate_tokens(content),
                    chunk_index=chunk_index,
                )
            )
            chunk_index += 1
        pos = end
        # Skip whitespace at the split point to avoid leading spaces in next chunk.
        while pos < len(text) and text[pos] == " ":
            pos += 1

    return chunks


def chunk_text(text: str, doc_id: str, max_chunk_tokens: int = 4000) -> list[DocumentChunk]:
    """Split text into semantic chunks preserving heading structure.

    Strategy (in order of preference):

    1. **Heading-based** — split on markdown headings (``# ``, ``## ``, ``### ``).
    2. **Paragraph-based** — if any heading-based chunk exceeds
       *max_chunk_tokens*, split it further on paragraph boundaries
       (double newlines).
    3. **Token-window** — if a single paragraph still exceeds the limit,
       hard-split on the nearest whitespace at *max_chunk_tokens* boundaries.

    This ensures no chunk ever exceeds the token limit regardless of input
    format (e.g. PDF-extracted text with no markdown headings).
    """
    chunks: list[DocumentChunk] = []
    current_headings: list[str] = []

    # Split on headings
    sections = re.split(r"(#{1,3} .+)", text)
    current_content: list[str] = []
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

    if not chunks:
        chunks = [
            DocumentChunk(
                document_id=doc_id,
                content=text,
                heading_path=[],
                token_count=estimate_tokens(text),
                chunk_index=0,
            )
        ]

    # --- Token-aware fallback: re-split oversized chunks ---
    needs_resplit = any(c.token_count > max_chunk_tokens for c in chunks)
    if not needs_resplit:
        return chunks

    result: list[DocumentChunk] = []
    idx = 0
    for chunk in chunks:
        if chunk.token_count > max_chunk_tokens:
            sub = _split_by_paragraphs(chunk.content, doc_id, chunk.heading_path, max_chunk_tokens, idx)
            result.extend(sub)
            idx += len(sub)
        else:
            chunk.chunk_index = idx
            result.append(chunk)
            idx += 1

    return result


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
# PDF metadata helpers
# ---------------------------------------------------------------------------


class _PdfMetadata(NamedTuple):
    """Metadata extracted from a PDF's info dictionary via fitz."""

    title: str | None
    author: str | None
    published_date: date | None


def _extract_pdf_metadata(file_bytes: bytes) -> _PdfMetadata:
    """Read title, author, and creation date from a PDF's info dictionary.

    Uses :mod:`fitz` (pymupdf) which reads the metadata dict instantly without
    any ML processing.  Returns ``None`` for any field that is missing or empty.
    """
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    meta = doc.metadata or {}
    doc.close()

    title = (meta.get("title") or "").strip() or None
    author = (meta.get("author") or "").strip() or None
    published_date = _parse_pdf_date(meta.get("creationDate"))

    return _PdfMetadata(title=title, author=author, published_date=published_date)


def _parse_pdf_date(raw: str | None) -> date | None:
    """Parse a PDF date string (``D:YYYYMMDDHHmmSS...``) into a date.

    Returns ``None`` if the string is missing, empty, or unparseable.
    """
    if not raw:
        return None
    # Strip the ``D:`` prefix that PDF date strings use.
    cleaned = raw.strip()
    if cleaned.startswith("D:"):
        cleaned = cleaned[2:]
    # We only need YYYYMMDD — ignore time/timezone suffixes.
    if len(cleaned) < 8:
        return None
    try:
        return date(int(cleaned[:4]), int(cleaned[4:6]), int(cleaned[6:8]))
    except (ValueError, IndexError):
        return None


def _first_markdown_heading(text: str) -> str | None:
    """Return the text of the first top-level markdown heading, or ``None``."""
    match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else None


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

        # Extract metadata (title, author, date) from the PDF info dictionary.
        # This is an instant fitz dict lookup — no ML processing.
        pdf_meta = _extract_pdf_metadata(file_bytes)
        fallback_title = filename.replace(".pdf", "")

        # Create source record
        source = Source(
            source_type=SourceType.PDF,
            title=pdf_meta.title or fallback_title,
            author=pdf_meta.author,
            published_date=pdf_meta.published_date,
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
        # docling is not installed.  The batched path offloads each Docling
        # call to a thread and emits extraction progress via WebSocket.
        if _DOCLING_AVAILABLE:
            clean_text, page_count = await self._extract_via_docling_batched(raw_pdf_path, source.id)
        else:
            clean_text, page_count = self._extract_via_fitz(file_bytes)

        # If the title is still the filename fallback (no PDF metadata title),
        # try extracting the first markdown heading from the converted text.
        if source.title == fallback_title:
            heading = _first_markdown_heading(clean_text)
            if heading:
                source.title = heading

        # Vision enhancement (issue #68): detect text-sparse pages and
        # describe them via the multimodal LLM. This is a post-processing
        # step that merges LLM descriptions for diagrams/charts/covers
        # back into the extracted text.
        clean_text = await self._enhance_with_vision(file_bytes, clean_text, source.id)

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

    # Image extraction is handled by the frontend FiguresPanel which
    # reads from ~/.wikimind/images/{source_id}/ populated during
    # ingestion by the docling PictureItem/TableItem extraction.
    # See issue #142 for the full design.

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

    async def _extract_via_docling_batched(self, raw_pdf_path: Path, source_id: str) -> tuple[str, int]:
        """Extract markdown from a PDF in page-range batches with progress.

        Uses ``fitz`` to read the total page count instantly, then converts
        in batches of ``settings.docling_batch_pages`` pages via
        ``asyncio.to_thread`` so the event loop is never blocked. Between
        batches an ``extraction.progress`` WebSocket event is emitted.

        For small PDFs where the total page count is at or below the batch
        size this collapses to a single batch (functionally identical to the
        unbatched path, but still non-blocking).

        Args:
            raw_pdf_path: Path to the saved raw PDF on disk.
            source_id: Source ID used as the key for progress events.

        Returns:
            A tuple of ``(markdown_text, total_pages)``.
        """
        # Get total page count instantly via fitz (always available).
        doc = fitz.open(str(raw_pdf_path))
        total_pages = doc.page_count
        doc.close()

        settings = get_settings()
        batch_size = settings.docling_batch_pages

        await emit_source_progress(source_id, f"Extracting PDF ({total_pages} pages)...")

        # Warm up the converter off the event loop — the first call to
        # _get_docling_converter() triggers ~500 MB of model downloads
        # and weight loading, which must not block the async event loop.
        converter = await asyncio.to_thread(_get_docling_converter)
        markdown_parts: list[str] = []

        for start in range(1, total_pages + 1, batch_size):
            end = min(start + batch_size - 1, total_pages)

            def _convert_batch(
                _conv: Any = converter,
                _path: str = str(raw_pdf_path),
                _start: int = start,
                _end: int = end,
            ) -> str:
                result = _conv.convert(_path, page_range=(_start, _end))
                return result.document.export_to_markdown()

            batch_md = await asyncio.to_thread(_convert_batch)
            markdown_parts.append(batch_md)
            await emit_source_progress(source_id, f"Extracting pages {end}/{total_pages}...")

        markdown = "\n\n".join(markdown_parts)
        return markdown, total_pages

    # -----------------------------------------------------------------------
    # Vision-enhanced slide deck ingestion (issue #68)
    #
    # After text extraction, check per-page density. Pages with text below
    # the threshold (diagrams, charts, cover slides) are rendered as images
    # and described by the multimodal LLM. The descriptions are merged back
    # into the extracted text in page order.
    # -----------------------------------------------------------------------

    @staticmethod
    def _extract_per_page_text(file_bytes: bytes) -> list[str]:
        """Extract text from each page of a PDF using fitz.

        Args:
            file_bytes: Raw PDF binary contents.

        Returns:
            A list of strings, one per page, containing the extracted text.
        """
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        texts = [str(doc[i].get_text()) for i in range(doc.page_count)]
        doc.close()
        return texts

    @staticmethod
    def _classify_pages(
        per_page_text: list[str],
        threshold: int,
    ) -> tuple[list[int], list[int]]:
        """Classify pages as text-dense or image-sparse.

        Args:
            per_page_text: Text content per page (from _extract_per_page_text).
            threshold: Character count below which a page is considered sparse.

        Returns:
            A tuple of (dense_indices, sparse_indices) — zero-based page numbers.
        """
        dense: list[int] = []
        sparse: list[int] = []
        for i, text in enumerate(per_page_text):
            if len(text.strip()) >= threshold:
                dense.append(i)
            else:
                sparse.append(i)
        return dense, sparse

    @staticmethod
    def _render_pages_as_images(file_bytes: bytes, page_indices: list[int], dpi: int) -> list[bytes]:
        """Render specific PDF pages as PNG images.

        Args:
            file_bytes: Raw PDF binary contents.
            page_indices: Zero-based page indices to render.
            dpi: Resolution for rendering.

        Returns:
            A list of PNG byte strings, one per requested page.
        """
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        images: list[bytes] = []
        for idx in page_indices:
            page = doc[idx]
            pix = page.get_pixmap(dpi=dpi)
            images.append(bytes(pix.tobytes("png")))
        doc.close()
        return images

    @staticmethod
    async def _describe_images_via_llm(
        images: list[bytes],
        page_indices: list[int],
        max_per_batch: int,
    ) -> dict[int, str]:
        """Send rendered page images to the multimodal LLM for description.

        Images are batched to stay within provider limits. Each batch
        produces one LLM call whose response contains descriptions for
        all pages in that batch.

        Args:
            images: PNG bytes for each sparse page (parallel to page_indices).
            page_indices: Zero-based page indices corresponding to each image.
            max_per_batch: Maximum images per LLM call.

        Returns:
            A dict mapping page index to its LLM-generated description.
        """
        router = get_llm_router()
        descriptions: dict[int, str] = {}

        system_prompt = (
            "You are a document analysis assistant. For each page image provided, "
            "write a concise but complete textual description of its visual content "
            "including any diagrams, charts, graphs, tables, or images. "
            "Preserve any text visible in the image. "
            "Separate each page description with a blank line and prefix it with "
            "'[Page N]:' where N is the page number provided."
        )

        # Process in batches
        for batch_start in range(0, len(images), max_per_batch):
            batch_end = min(batch_start + max_per_batch, len(images))
            batch_images = images[batch_start:batch_end]
            batch_indices = page_indices[batch_start:batch_end]

            # Build multimodal content parts
            content_parts: list[dict[str, Any]] = []
            content_parts.append(
                {
                    "type": "text",
                    "text": (
                        f"Describe the following {len(batch_images)} page(s). "
                        "Page numbers: " + ", ".join(str(idx + 1) for idx in batch_indices) + "."
                    ),
                }
            )

            for idx, img_bytes in zip(batch_indices, batch_images, strict=True):
                content_parts.append(
                    {
                        "type": "text",
                        "text": f"[Page {idx + 1}]:",
                    }
                )
                content_parts.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": base64.b64encode(img_bytes).decode("ascii"),
                        },
                    }
                )

            response = await router.complete_multimodal(
                system=system_prompt,
                content_parts=content_parts,
                task_type=TaskType.INGEST,
                max_tokens=4096,
                temperature=0.2,
            )

            # Parse the response — assign descriptions to page indices.
            # The LLM is instructed to prefix each description with [Page N]:
            # but as a fallback we split on double-newlines and assign in order.
            raw_text = response.content.strip()
            page_sections = re.split(r"\[Page \d+\]:", raw_text)
            # First element is empty or preamble text before the first marker
            page_sections = [s.strip() for s in page_sections if s.strip()]

            for i, idx in enumerate(batch_indices):
                if i < len(page_sections):
                    descriptions[idx] = page_sections[i]
                else:
                    descriptions[idx] = raw_text  # fallback: entire response

        return descriptions

    @staticmethod
    def _merge_text_and_descriptions(
        per_page_text: list[str],
        descriptions: dict[int, str],
        sparse_indices: list[int],
    ) -> str:
        """Merge per-page extracted text with LLM descriptions for sparse pages.

        Dense pages keep their original extracted text. Sparse pages get
        their LLM-generated description prepended with a marker.

        Args:
            per_page_text: Original text per page.
            descriptions: LLM descriptions keyed by page index.
            sparse_indices: Indices of pages that were sent to the LLM.

        Returns:
            A single merged text string with all pages in order.
        """
        merged_pages: list[str] = []
        sparse_set = set(sparse_indices)

        for i, text in enumerate(per_page_text):
            if i in sparse_set and i in descriptions:
                # Use the LLM description for sparse pages, keeping any
                # minimal text that was present as well.
                desc = descriptions[i]
                if text.strip():
                    merged_pages.append(f"{text.strip()}\n\n[Visual content]: {desc}")
                else:
                    merged_pages.append(f"[Visual content]: {desc}")
            else:
                merged_pages.append(text)

        return "\n\n".join(merged_pages)

    async def _enhance_with_vision(
        self,
        file_bytes: bytes,
        clean_text: str,
        source_id: str,
    ) -> str:
        """Apply vision enhancement to PDF text extraction.

        Detects text-sparse pages, renders them as images, and sends to
        the multimodal LLM. Merges the descriptions back with the
        original text.

        Args:
            file_bytes: Raw PDF binary contents.
            clean_text: The text already extracted (fitz or docling).
            source_id: Source ID for progress logging.

        Returns:
            Enhanced text with LLM descriptions for sparse pages merged in.
        """
        settings = get_settings()

        if not settings.vision_enabled:
            return clean_text

        per_page_text = self._extract_per_page_text(file_bytes)
        _dense, sparse = self._classify_pages(per_page_text, settings.vision_text_threshold)

        if not sparse:
            log.info("Vision: no sparse pages detected", source_id=source_id)
            return clean_text

        log.info(
            "Vision: enhancing sparse pages",
            source_id=source_id,
            sparse_pages=len(sparse),
            total_pages=len(per_page_text),
        )

        await emit_source_progress(
            source_id,
            f"Describing {len(sparse)} visual page(s) via LLM...",
        )

        images = self._render_pages_as_images(file_bytes, sparse, settings.vision_dpi)
        descriptions = await self._describe_images_via_llm(
            images,
            sparse,
            settings.vision_max_pages_per_batch,
        )

        # Append vision descriptions to the original clean_text (which may
        # be docling structured markdown). We do NOT rebuild from fitz pages
        # because that would discard docling's heading hierarchy and tables.
        if descriptions:
            desc_lines = ["\n\n---\n"]
            for page_idx, desc in sorted(descriptions.items()):
                desc_lines.append(f"[Visual content (page {page_idx + 1})]: {desc}")
            return clean_text + "\n".join(desc_lines)
        return clean_text


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
