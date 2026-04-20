"""PDF adapter for ingesting PDF files.

Uses docling-serve (an HTTP sidecar) for structured extraction (heading
hierarchy, tables, OCR fallback, multi-column layouts). Falls back to
plain-text extraction via fitz (pymupdf) when docling-serve is unavailable.

Both branches honour the dual-file lineage convention from issue #59: the raw
``.pdf`` bytes are written to ``~/.wikimind/raw/{source_id}.pdf`` and the cleaned
extraction to ``~/.wikimind/raw/{source_id}.txt``, with ``Source.file_path``
pointing at the latter.
"""

from __future__ import annotations

import base64
import re
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

import fitz
import httpx
import structlog

from wikimind.api.routes.ws import emit_source_progress
from wikimind.config import get_settings
from wikimind.engine.llm_router import get_llm_router
from wikimind.ingest.utils import (
    _check_source_dedup,
    chunk_text,
    compute_hash,
    estimate_tokens,
)
from wikimind.models import IngestStatus, NormalizedDocument, Source, SourceType, TaskType

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Docling-serve HTTP client (replaces in-process docling)
#
# The docling-serve container exposes /v1/convert/source for PDF-to-markdown
# conversion. Falls back to fitz plain-text extraction if the sidecar is down.
# ---------------------------------------------------------------------------


async def _convert_via_docling_serve(pdf_path: Path) -> str:
    """Send PDF to docling-serve sidecar, return extracted markdown."""
    settings = get_settings()
    url = f"{settings.docling_serve_url}/v1/convert/source"
    async with httpx.AsyncClient(timeout=300.0) as client:
        with open(pdf_path, "rb") as f:
            resp = await client.post(
                url,
                files={"source": (pdf_path.name, f, "application/pdf")},
                data={"options": '{"to_format": "md"}'},
            )
        resp.raise_for_status()
        return resp.json().get("document", {}).get("md_content", resp.text)


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

    Uses docling-serve (HTTP sidecar) for structured extraction (heading
    hierarchy, tables, OCR fallback, multi-column layouts). Falls back to
    plain-text extraction via :mod:`fitz` (pymupdf) when docling-serve is
    unavailable.

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
        log.info("Ingesting PDF", filename=filename)

        # Dedup: hash the raw PDF bytes and short-circuit if we've already
        # ingested this exact file (issue #67). The hash is computed before
        # any LLM work or extraction so re-uploads are essentially free.
        dedup = await _check_source_dedup(file_bytes, session, "PDF")
        if dedup is not None:
            return dedup
        content_hash = compute_hash(file_bytes)

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

        # Extract text — prefer docling-serve for structured output (markdown
        # with heading hierarchy, table-aware), fall back to fitz plain text
        # when docling-serve is unavailable.
        try:
            clean_text, page_count = await self._extract_via_docling(raw_pdf_path, source.id)
        except (httpx.HTTPError, httpx.ConnectError) as exc:
            log.warning("docling-serve unavailable, falling back to fitz", error=str(exc))
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
        try:
            clean_text = await self._enhance_with_vision(file_bytes, clean_text, source.id)
        except Exception:  # TODO: narrow once provider error hierarchy is unified
            log.warning("Vision enhancement failed — using extracted text as-is", source_id=source.id)

        text_path = raw_dir / f"{source.id}.txt"
        text_path.write_text(clean_text, encoding="utf-8")
        source.file_path = f"{source.id}.txt"

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

    async def _extract_via_docling(self, raw_pdf_path: Path, source_id: str) -> tuple[str, int]:
        """Extract PDF text via docling-serve HTTP API.

        Sends the PDF to the docling-serve sidecar for structured markdown
        extraction (heading hierarchy, tables, multi-column layouts, OCR).
        Page count is determined via fitz (fast, no ML).

        Args:
            raw_pdf_path: Path to the saved raw PDF on disk.
            source_id: Source ID used as the key for progress events.

        Returns:
            A tuple of ``(markdown_text, page_count)``.
        """
        await emit_source_progress(source_id, "Sending to docling-serve...")
        md_content = await _convert_via_docling_serve(raw_pdf_path)
        # Count pages via fitz (fast, no ML)
        doc = fitz.open(str(raw_pdf_path))
        page_count = len(doc)
        doc.close()
        await emit_source_progress(source_id, "Extraction complete")
        return md_content, page_count

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
            A tuple of (dense_indices, sparse_indices) -- zero-based page numbers.
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
