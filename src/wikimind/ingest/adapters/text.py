"""Text adapter for ingesting raw text (paste / direct input).

Plain text is already in its final format, so the raw and cleaned files
are the same ``.txt`` file.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from wikimind.ingest.utils import (
    _check_source_dedup,
    chunk_text,
    compute_hash,
    estimate_tokens,
)
from wikimind.models import IngestStatus, NormalizedDocument, Source, SourceType
from wikimind.storage import resolve_raw_path

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

log = structlog.get_logger()


class TextAdapter:
    """Adapter for ingesting raw text."""

    async def ingest(
        self,
        content: str,
        title: str | None,
        session: AsyncSession,
        user_id: str | None = None,
    ) -> tuple[Source, NormalizedDocument]:
        """Ingest raw text and return source and normalized document."""
        log.info("Ingesting text", title=title, chars=len(content))

        # Dedup: hash the UTF-8 bytes of the pasted content (issue #67).
        # Title differences do NOT contribute — re-pasting the same body
        # under a new title still hits the dedup.
        dedup = await _check_source_dedup(content.encode("utf-8"), session, "text")
        if dedup is not None:
            return dedup
        content_hash = compute_hash(content.encode("utf-8"))

        source = Source(
            source_type=SourceType.TEXT,
            title=title or "Untitled Note",
            status=IngestStatus.PROCESSING,
            token_count=estimate_tokens(content),
            content_hash=content_hash,
            user_id=user_id,
        )
        session.add(source)
        await session.commit()
        await session.refresh(source)

        # Pasted text is already plain text, so the raw and cleaned files are
        # the same .txt file. file_path always points at the .txt the worker
        # reads (see issue #59).
        text_path = resolve_raw_path(f"{source.id}.txt", user_id=source.user_id)
        text_path.parent.mkdir(parents=True, exist_ok=True)
        text_path.write_text(content, encoding="utf-8")
        source.file_path = f"{source.id}.txt"
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
