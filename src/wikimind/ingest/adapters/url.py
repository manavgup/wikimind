"""URL adapter for ingesting web pages.

Fetches a URL, extracts article text via trafilatura, persists the source
and returns a NormalizedDocument for downstream compilation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx
import structlog
import trafilatura

from wikimind.config import get_settings
from wikimind.ingest.utils import (
    _check_source_dedup,
    chunk_text,
    compute_hash,
    estimate_tokens,
)
from wikimind.models import IngestStatus, NormalizedDocument, Source, SourceType
from wikimind.storage import get_raw_storage

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

log = structlog.get_logger()


class URLAdapter:
    """Adapter for ingesting web URLs."""

    async def ingest(
        self,
        url: str,
        session: AsyncSession,
        user_id: str,
    ) -> tuple[Source, NormalizedDocument]:
        """Ingest a web URL and return source and normalized document."""
        log.info("Ingesting URL", url=url)

        # Fetch page
        timeout = get_settings().ingest.http_timeout_seconds
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
            response = await client.get(url, headers={"User-Agent": "WikiMind/0.1 (knowledge compiler)"})
            response.raise_for_status()
            html = response.text

        # Dedup: hash the raw HTML response and short-circuit if we've already
        # ingested this exact content (issue #67). We use the HTML bytes — not
        # the cleaned extraction — so the hash is stable across changes to the
        # trafilatura extraction pipeline.
        dedup = await _check_source_dedup(html.encode("utf-8"), session, "URL", user_id)
        if dedup is not None:
            return dedup
        content_hash = compute_hash(html.encode("utf-8"))

        # Extract article text
        downloaded = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            output_format="markdown",
            with_metadata=True,
        )

        if not downloaded:
            msg = f"Could not extract content from {url}"
            raise ValueError(msg)

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
            user_id=user_id,
        )
        session.add(source)
        await session.commit()
        await session.refresh(source)

        # Save clean extracted text (used by the compiler worker) and
        # keep the raw HTML alongside it for reference/reprocessing.
        try:
            raw_storage = get_raw_storage(user_id)
            await raw_storage.write(f"{source.id}.html", html)
            await raw_storage.write(f"{source.id}.txt", downloaded)
            source.file_path = f"{source.id}.txt"
            source.clean_text = downloaded
        except Exception as exc:
            log.error(
                "File write failed after source commit — marking as failed",
                source_id=source.id,
                error=str(exc),
            )
            source.status = IngestStatus.FAILED
            source.error_message = f"File write failed: {exc}"
            session.add(source)
            await session.commit()
            raise

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
