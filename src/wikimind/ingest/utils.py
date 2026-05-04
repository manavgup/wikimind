"""Shared utilities for the ingest subsystem.

Content-hash deduplication helpers, token estimation, and text chunking
functions used by all adapters and the orchestrating IngestService.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from typing import TYPE_CHECKING

import structlog
from sqlmodel import select

from wikimind.models import DocumentChunk, NormalizedDocument, Source
from wikimind.storage import get_raw_storage

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

log = structlog.get_logger()


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


async def _check_source_dedup(
    payload: bytes,
    session: AsyncSession,
    source_type: str,
) -> tuple[Source, NormalizedDocument] | None:
    """Return existing (source, doc) if content was already ingested, else None."""
    content_hash = compute_hash(payload)
    existing = await find_source_by_hash(session, content_hash)
    if existing is not None:
        if existing.file_path:
            log.info(
                "Source dedup hit",
                source_type=source_type,
                source_id=existing.id,
                hash=content_hash[:16],
            )
            doc = await asyncio.to_thread(reconstruct_normalized_doc, existing)
            return existing, doc
        log.warning("Deleting zombie source (no file_path)", source_id=existing.id)
        await session.delete(existing)
        await session.commit()
    return None


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
        msg = f"Source {source.id} has no file_path; cannot reconstruct NormalizedDocument"
        raise ValueError(msg)
    raw_storage = get_raw_storage(source.user_id)
    raw_path = raw_storage.root / source.file_path
    clean_text = raw_path.read_text(encoding="utf-8")
    return NormalizedDocument(
        raw_source_id=source.id,
        clean_text=clean_text,
        title=source.title or "Untitled",
        author=source.author,
        published_date=source.published_date,
        estimated_tokens=source.token_count or estimate_tokens(clean_text),
        chunks=chunk_text(clean_text, source.id),
    )
