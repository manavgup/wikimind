"""Endpoints for ambient capture — inbox, ingest/discard, and RSS feeds (issue #442)."""

from fastapi import APIRouter, Depends, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.api.deps import get_current_user_id
from wikimind.database import get_session
from wikimind.models import (
    CaptureKind,
    CaptureListResponse,
    CaptureRequest,
    CaptureResponse,
    CaptureStatus,
    DeleteConfirmation,
    DiscardCaptureRequest,
    RssFeedListResponse,
    RssFeedRequest,
    RssFeedResponse,
    RssFeedToggleRequest,
    RssPollResponse,
)
from wikimind.services.capture import CaptureService
from wikimind.services.factories import get_capture_service, get_rss_service
from wikimind.services.rss import RssService

router = APIRouter()


# ---------------------------------------------------------------------------
# Capture inbox endpoints
# ---------------------------------------------------------------------------


@router.post("/{kind}", response_model=CaptureResponse)
async def create_capture(
    kind: CaptureKind,
    request: CaptureRequest,
    session: AsyncSession = Depends(get_session),
    service: CaptureService = Depends(get_capture_service),
    user_id: str = Depends(get_current_user_id),
) -> CaptureResponse:
    """Push a raw capture from an ambient adapter."""
    return await service.create_capture(
        kind=kind,
        content=request.content,
        session=session,
        user_id=user_id,
        title=request.title,
        source_url=request.source_url,
        external_id=request.external_id,
    )


@router.get("", response_model=CaptureListResponse)
async def list_captures(
    status: CaptureStatus | None = None,
    kind: CaptureKind | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    service: CaptureService = Depends(get_capture_service),
    user_id: str = Depends(get_current_user_id),
) -> CaptureListResponse:
    """List captures (the capture inbox)."""
    return await service.list_captures(
        session=session,
        user_id=user_id,
        status=status,
        kind=kind,
        limit=limit,
        offset=offset,
    )


@router.post("/{capture_id}/ingest")
async def ingest_capture(
    capture_id: str,
    session: AsyncSession = Depends(get_session),
    service: CaptureService = Depends(get_capture_service),
    user_id: str = Depends(get_current_user_id),
):
    """Promote a capture to a full source for compilation."""
    return await service.ingest_capture(capture_id, session, user_id)


@router.post("/{capture_id}/discard")
async def discard_capture(
    capture_id: str,
    request: DiscardCaptureRequest | None = None,
    session: AsyncSession = Depends(get_session),
    service: CaptureService = Depends(get_capture_service),
    user_id: str = Depends(get_current_user_id),
):
    """Mark a capture as not-worth-keeping."""
    reason = request.reason if request else None
    return await service.discard_capture(capture_id, session, user_id, reason=reason)


# ---------------------------------------------------------------------------
# RSS feed management endpoints
# ---------------------------------------------------------------------------


@router.post("/rss/feeds", response_model=RssFeedResponse)
async def subscribe_rss_feed(
    request: RssFeedRequest,
    session: AsyncSession = Depends(get_session),
    rss_service: RssService = Depends(get_rss_service),
    user_id: str = Depends(get_current_user_id),
) -> RssFeedResponse:
    """Subscribe to an RSS/Atom feed."""
    return await rss_service.subscribe(
        feed_url=request.feed_url,
        session=session,
        user_id=user_id,
        title=request.title,
    )


@router.get("/rss/feeds", response_model=RssFeedListResponse)
async def list_rss_feeds(
    session: AsyncSession = Depends(get_session),
    rss_service: RssService = Depends(get_rss_service),
    user_id: str = Depends(get_current_user_id),
) -> RssFeedListResponse:
    """List all RSS feed subscriptions."""
    return await rss_service.list_feeds(session, user_id)


@router.patch("/rss/feeds/{feed_id}", response_model=RssFeedResponse)
async def toggle_rss_feed(
    feed_id: str,
    request: RssFeedToggleRequest,
    session: AsyncSession = Depends(get_session),
    rss_service: RssService = Depends(get_rss_service),
    user_id: str = Depends(get_current_user_id),
) -> RssFeedResponse:
    """Enable or disable an RSS feed."""
    return await rss_service.toggle_feed(feed_id, session, user_id, enabled=request.enabled)


@router.delete("/rss/feeds/{feed_id}", response_model=DeleteConfirmation)
async def delete_rss_feed(
    feed_id: str,
    session: AsyncSession = Depends(get_session),
    rss_service: RssService = Depends(get_rss_service),
    user_id: str = Depends(get_current_user_id),
) -> DeleteConfirmation:
    """Delete an RSS feed subscription."""
    await rss_service.delete_feed(feed_id, session, user_id)
    return DeleteConfirmation(deleted=feed_id)


@router.post("/rss/feeds/{feed_id}/poll", response_model=RssPollResponse)
async def poll_rss_feed(
    feed_id: str,
    session: AsyncSession = Depends(get_session),
    rss_service: RssService = Depends(get_rss_service),
    user_id: str = Depends(get_current_user_id),
) -> RssPollResponse:
    """Manually trigger a poll for a single RSS feed."""
    return await rss_service.poll_feed(feed_id, session, user_id)
