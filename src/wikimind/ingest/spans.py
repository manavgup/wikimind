"""Span-level citation utilities for source paragraph anchoring.

Provides text fingerprinting for re-anchoring and span extraction
helpers used by ingest adapters to produce SourceSpan rows.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from typing import TYPE_CHECKING

import structlog

from wikimind.models.enums import LocatorKind
from wikimind.models.tables.wiki import SourceSpan

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Text fingerprinting
# ---------------------------------------------------------------------------

_PUNCTUATION_RE = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_text(text: str) -> str:
    """Normalize text for fingerprinting: lowercase, strip punctuation, collapse whitespace.

    Args:
        text: Raw verbatim text.

    Returns:
        Normalized string suitable for hashing.
    """
    lowered = text.lower()
    no_punct = _PUNCTUATION_RE.sub("", lowered)
    return " ".join(no_punct.split())


def compute_fingerprint(text: str) -> str:
    """Compute a SHA-256 fingerprint of normalized text.

    Used for re-anchoring: if a source is re-ingested with minor formatting
    changes, the fingerprint remains stable so existing claim-to-span links
    can be preserved.

    Args:
        text: Raw verbatim text to fingerprint.

    Returns:
        Hex-encoded SHA-256 digest of the normalized text.
    """
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Paragraph splitting
# ---------------------------------------------------------------------------


def _split_paragraphs(text: str) -> list[str]:
    """Split text into non-empty paragraphs on double-newline boundaries.

    Args:
        text: The full source text.

    Returns:
        List of paragraph strings with leading/trailing whitespace stripped.
    """
    raw = re.split(r"\n\n+", text)
    return [p.strip() for p in raw if p.strip()]


# ---------------------------------------------------------------------------
# Adapter-specific span extraction
# ---------------------------------------------------------------------------


def extract_text_spans(
    text: str,
    source_id: str,
    user_id: str,
) -> list[SourceSpan]:
    """Extract byte-range spans from plain text content.

    Splits on paragraph boundaries and records the byte offset of each
    paragraph in the UTF-8 encoding of the full text.

    Args:
        text: Full source text content.
        source_id: Parent source UUID.
        user_id: Owner user UUID.

    Returns:
        List of SourceSpan instances (not yet persisted).
    """
    try:
        paragraphs = _split_paragraphs(text)
        spans: list[SourceSpan] = []
        text_bytes = text.encode("utf-8")

        search_start = 0
        for para in paragraphs:
            para_bytes = para.encode("utf-8")
            byte_start = text_bytes.find(para_bytes, search_start)
            if byte_start == -1:
                continue
            byte_end = byte_start + len(para_bytes)
            search_start = byte_end

            spans.append(
                SourceSpan(
                    id=str(uuid.uuid4()),
                    source_id=source_id,
                    user_id=user_id,
                    locator_kind=LocatorKind.TEXT_BYTE_RANGE,
                    locator={"start": byte_start, "end": byte_end},
                    text=para,
                    fingerprint=compute_fingerprint(para),
                )
            )

        return spans
    except Exception:
        log.warning("Failed to extract text spans", source_id=source_id, exc_info=True)
        return []


def extract_pdf_spans(
    text: str,
    source_id: str,
    user_id: str,
    page_texts: list[str] | None = None,
) -> list[SourceSpan]:
    """Extract page-level paragraph spans from PDF extracted text.

    When per-page text is available (via fitz), each paragraph is anchored
    to its page number. Otherwise falls back to paragraph-level spans
    without page anchoring.

    Args:
        text: Full extracted text from the PDF.
        source_id: Parent source UUID.
        user_id: Owner user UUID.
        page_texts: Optional list of per-page text strings from fitz.

    Returns:
        List of SourceSpan instances (not yet persisted).
    """
    try:
        spans: list[SourceSpan] = []

        if page_texts:
            for page_num, page_text in enumerate(page_texts):
                paragraphs = _split_paragraphs(page_text)
                for para_idx, para in enumerate(paragraphs):
                    spans.append(
                        SourceSpan(
                            id=str(uuid.uuid4()),
                            source_id=source_id,
                            user_id=user_id,
                            locator_kind=LocatorKind.PDF_PAGE_RECT,
                            locator={"page": page_num + 1, "paragraph": para_idx},
                            text=para,
                            fingerprint=compute_fingerprint(para),
                        )
                    )
        else:
            # Fallback: treat as plain paragraphs without page info
            paragraphs = _split_paragraphs(text)
            for para_idx, para in enumerate(paragraphs):
                spans.append(
                    SourceSpan(
                        id=str(uuid.uuid4()),
                        source_id=source_id,
                        user_id=user_id,
                        locator_kind=LocatorKind.PDF_PAGE_RECT,
                        locator={"page": 1, "paragraph": para_idx},
                        text=para,
                        fingerprint=compute_fingerprint(para),
                    )
                )

        return spans
    except Exception:
        log.warning("Failed to extract PDF spans", source_id=source_id, exc_info=True)
        return []


def extract_url_spans(
    text: str,
    source_id: str,
    user_id: str,
) -> list[SourceSpan]:
    """Extract paragraph-level spans from URL-extracted text.

    Splits on paragraph boundaries and records paragraph index as the
    locator. Uses HTML_PARAGRAPH_OFFSET since we store paragraph index
    and character offset, not actual XPath selectors.

    Args:
        text: Extracted text content from the web page.
        source_id: Parent source UUID.
        user_id: Owner user UUID.

    Returns:
        List of SourceSpan instances (not yet persisted).
    """
    try:
        paragraphs = _split_paragraphs(text)
        spans: list[SourceSpan] = []

        for para_idx, para in enumerate(paragraphs):
            spans.append(
                SourceSpan(
                    id=str(uuid.uuid4()),
                    source_id=source_id,
                    user_id=user_id,
                    locator_kind=LocatorKind.HTML_PARAGRAPH_OFFSET,
                    locator={"paragraph": para_idx, "offset": 0, "length": len(para)},
                    text=para,
                    fingerprint=compute_fingerprint(para),
                )
            )

        return spans
    except Exception:
        log.warning("Failed to extract URL spans", source_id=source_id, exc_info=True)
        return []


# ---------------------------------------------------------------------------
# Persistence helper
# ---------------------------------------------------------------------------


async def persist_spans(
    spans: list[SourceSpan],
    session: AsyncSession,
) -> None:
    """Persist a batch of SourceSpan instances to the database.

    Args:
        spans: List of SourceSpan instances to save.
        session: Async database session.
    """
    if not spans:
        return
    for span in spans:
        session.add(span)
    await session.flush()
    log.info("Persisted source spans", count=len(spans), source_id=spans[0].source_id)
