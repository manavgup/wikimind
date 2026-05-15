"""Ambient capture service — manages the capture inbox lifecycle (issue #442).

Captures are cheap, promiscuous records from ambient adapters (RSS, share-target,
clipboard, etc.). This service manages creating captures, listing the inbox,
promoting captures to full Sources for compilation, and discarding low-signal items.
"""

from __future__ import annotations

import functools
import hashlib
from typing import TYPE_CHECKING

import structlog
from sqlmodel import func, select

from wikimind._datetime import utcnow_naive
from wikimind.errors import NotFoundError
from wikimind.models import (
    CaptureDiscardResponse,
    CaptureIngestResponse,
    CaptureKind,
    CaptureListResponse,
    CaptureResponse,
    CaptureSource,
    CaptureStatus,
)
from wikimind.services.ingest import get_ingest_service

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

log = structlog.get_logger()


def _compute_content_hash(content: str) -> str:
    """Compute a SHA-256 hex digest of the content for dedup."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _capture_to_response(capture: CaptureSource) -> CaptureResponse:
    """Convert a CaptureSource row to an API response."""
    return CaptureResponse(
        id=capture.id,
        kind=capture.kind,
        title=capture.title,
        source_url=capture.source_url,
        status=capture.status,
        external_id=capture.external_id,
        received_at=capture.received_at,
        triaged_at=capture.triaged_at,
        ingested_at=capture.ingested_at,
        discarded_at=capture.discarded_at,
        discard_reason=capture.discard_reason,
        source_id=capture.source_id,
    )


class CaptureService:
    """Manages the ambient capture inbox."""

    async def create_capture(
        self,
        kind: CaptureKind,
        content: str,
        session: AsyncSession,
        user_id: str,
        *,
        title: str | None = None,
        source_url: str | None = None,
        external_id: str | None = None,
    ) -> CaptureResponse:
        """Create a new capture item.

        Args:
            kind: The adapter kind that produced this capture.
            content: Raw payload (text, JSON, etc.).
            session: Async database session.
            user_id: Owner of this capture.
            title: Optional human-readable title.
            source_url: Optional URL associated with the content.
            external_id: Optional external identifier for dedup (e.g. RSS guid).

        Returns:
            CaptureResponse for the newly created capture.
        """
        content_hash = _compute_content_hash(content)

        # Dedup: if we already captured identical content for this user, return it
        existing = await session.execute(
            select(CaptureSource).where(
                CaptureSource.user_id == user_id,
                CaptureSource.content_hash == content_hash,
            )
        )
        found = existing.scalars().first()
        if found is not None:
            log.info(
                "capture dedup hit",
                capture_id=found.id,
                kind=kind,
                user_id=user_id,
            )
            return _capture_to_response(found)

        capture = CaptureSource(
            user_id=user_id,
            kind=kind,
            title=title,
            raw_payload=content,
            content_hash=content_hash,
            source_url=source_url,
            external_id=external_id,
        )
        session.add(capture)
        await session.commit()
        await session.refresh(capture)

        log.info(
            "capture created",
            capture_id=capture.id,
            kind=kind,
            user_id=user_id,
        )
        return _capture_to_response(capture)

    async def list_captures(
        self,
        session: AsyncSession,
        user_id: str,
        *,
        status: CaptureStatus | None = None,
        kind: CaptureKind | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> CaptureListResponse:
        """List captures for the inbox view.

        Args:
            session: Async database session.
            user_id: Owner filter.
            status: Optional status filter.
            kind: Optional adapter kind filter.
            limit: Max results.
            offset: Pagination offset.

        Returns:
            CaptureListResponse with items and total count.
        """
        base = select(CaptureSource).where(CaptureSource.user_id == user_id)
        if status is not None:
            base = base.where(CaptureSource.status == status)
        if kind is not None:
            base = base.where(CaptureSource.kind == kind)

        # Total count
        count_result = await session.execute(select(func.count()).select_from(base.subquery()))
        total = count_result.scalar() or 0

        # Paginated results
        query = (
            base.order_by(CaptureSource.received_at.desc())  # type: ignore[attr-defined]
            .offset(offset)
            .limit(limit)
        )
        result = await session.execute(query)
        captures = list(result.scalars().all())

        return CaptureListResponse(
            items=[_capture_to_response(c) for c in captures],
            total=total,
        )

    async def get_capture(
        self,
        capture_id: str,
        session: AsyncSession,
        user_id: str,
    ) -> CaptureSource:
        """Retrieve a single capture by ID.

        Args:
            capture_id: The capture UUID.
            session: Async database session.
            user_id: Owner verification.

        Returns:
            The CaptureSource record.

        Raises:
            NotFoundError: If the capture doesn't exist or belongs to another user.
        """
        capture = await session.get(CaptureSource, capture_id)
        msg = "Capture not found"
        if not capture:
            raise NotFoundError(msg)
        if capture.user_id != user_id:
            raise NotFoundError(msg)
        return capture

    async def ingest_capture(
        self,
        capture_id: str,
        session: AsyncSession,
        user_id: str,
    ) -> CaptureIngestResponse:
        """Promote a capture to a full Source for compilation.

        Creates a Source via the text adapter (content is already extracted)
        and updates the capture status to INGESTED.

        Args:
            capture_id: The capture to promote.
            session: Async database session.
            user_id: Owner verification.

        Returns:
            CaptureIngestResponse with the new source ID.

        Raises:
            NotFoundError: If the capture doesn't exist or belongs to another user.
        """
        capture = await self.get_capture(capture_id, session, user_id)

        if capture.status == CaptureStatus.INGESTED:
            return CaptureIngestResponse(
                capture_id=capture.id,
                source_id=capture.source_id or "",
                status="already_ingested",
            )

        # Use the ingest service to create a real Source from the capture content
        ingest_svc = get_ingest_service()

        # If the capture has a URL, ingest as URL; otherwise ingest as text
        if capture.source_url:
            source = await ingest_svc.ingest_url(
                capture.source_url,
                session,
                auto_compile=True,
                user_id=user_id,
            )
        else:
            source = await ingest_svc.ingest_text(
                capture.raw_payload,
                capture.title,
                session,
                auto_compile=True,
                user_id=user_id,
            )

        now = utcnow_naive()
        capture.status = CaptureStatus.INGESTED
        capture.source_id = source.id
        capture.ingested_at = now
        session.add(capture)
        await session.commit()

        log.info(
            "capture ingested",
            capture_id=capture.id,
            source_id=source.id,
            user_id=user_id,
        )
        return CaptureIngestResponse(
            capture_id=capture.id,
            source_id=source.id,
        )

    async def discard_capture(
        self,
        capture_id: str,
        session: AsyncSession,
        user_id: str,
        *,
        reason: str | None = None,
    ) -> CaptureDiscardResponse:
        """Mark a capture as discarded (not worth keeping).

        Args:
            capture_id: The capture to discard.
            session: Async database session.
            user_id: Owner verification.
            reason: Optional reason for discarding.

        Returns:
            CaptureDiscardResponse confirming the discard.

        Raises:
            NotFoundError: If the capture doesn't exist or belongs to another user.
        """
        capture = await self.get_capture(capture_id, session, user_id)

        now = utcnow_naive()
        capture.status = CaptureStatus.DISCARDED
        capture.discarded_at = now
        capture.discard_reason = reason
        session.add(capture)
        await session.commit()

        log.info(
            "capture discarded",
            capture_id=capture.id,
            reason=reason,
            user_id=user_id,
        )
        return CaptureDiscardResponse(capture_id=capture.id)


@functools.lru_cache(maxsize=1)
def get_capture_service() -> CaptureService:
    """Return a singleton CaptureService instance for FastAPI dependency injection."""
    return CaptureService()
