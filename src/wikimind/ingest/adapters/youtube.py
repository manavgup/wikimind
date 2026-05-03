"""YouTube adapter for ingesting video transcripts.

Extracts the video transcript via the YouTube Transcript API and persists it
as a plain text source.
"""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING

import structlog
from youtube_transcript_api import YouTubeTranscriptApi

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


class YouTubeAdapter:
    """Adapter for ingesting YouTube videos."""

    async def ingest(
        self,
        url: str,
        session: AsyncSession,
        user_id: str,
    ) -> tuple[Source, NormalizedDocument]:
        """Ingest a YouTube video transcript."""
        log.info("Ingesting YouTube", url=url)

        # Extract video ID
        video_id = self._extract_video_id(url)
        if not video_id:
            msg = f"Could not extract YouTube video ID from {url}"
            raise ValueError(msg)

        # Fetch transcript — offload the synchronous HTTP call to a thread
        # so it doesn't block the uvicorn event loop (issue #181).
        transcript_list = await asyncio.to_thread(
            YouTubeTranscriptApi.get_transcript,  # type: ignore[attr-defined]
            video_id,
        )
        transcript_text = " ".join([t["text"] for t in transcript_list])

        # Dedup: hash the assembled transcript (issue #67). YouTube transcripts
        # are stable for a given video so the hash is effectively a video-id
        # alias, but hashing the actual content also catches the (rare) case
        # where the same transcript appears under multiple URLs.
        dedup = await _check_source_dedup(transcript_text.encode("utf-8"), session, "YouTube")
        if dedup is not None:
            return dedup
        content_hash = compute_hash(transcript_text.encode("utf-8"))

        source = Source(
            source_type=SourceType.YOUTUBE,
            source_url=url,
            title=f"YouTube: {video_id}",  # Will be enriched later
            status=IngestStatus.PROCESSING,
            token_count=estimate_tokens(transcript_text),
            content_hash=content_hash,
            user_id=user_id,
        )
        session.add(source)
        await session.commit()
        await session.refresh(source)

        # YouTube transcripts are already plain text, so the raw and cleaned
        # files are the same .txt. There is no separate raw video payload.
        storage = get_raw_storage(user_id)
        await storage.write(f"{source.id}.txt", transcript_text)
        source.file_path = f"{source.id}.txt"
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
