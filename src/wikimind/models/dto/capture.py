"""Capture and RSS DTOs — dependency-light request/response schemas."""

from datetime import datetime

from pydantic import BaseModel, Field

from wikimind.models.enums import CaptureKind, CaptureStatus

# ---------------------------------------------------------------------------
# Capture models
# ---------------------------------------------------------------------------


class CaptureRequest(BaseModel):
    """Request to capture content from an ambient adapter."""

    title: str | None = None
    content: str = Field(max_length=500000)
    source_url: str | None = None
    external_id: str | None = None


class CaptureResponse(BaseModel):
    """API response for a captured item."""

    id: str
    kind: CaptureKind
    title: str | None
    source_url: str | None
    status: CaptureStatus
    external_id: str | None = None
    received_at: datetime
    triaged_at: datetime | None = None
    ingested_at: datetime | None = None
    discarded_at: datetime | None = None
    discard_reason: str | None = None
    source_id: str | None = None


class CaptureListResponse(BaseModel):
    """Paginated list of captures."""

    items: list[CaptureResponse]
    total: int


class CaptureIngestResponse(BaseModel):
    """Response after promoting a capture to a full source."""

    capture_id: str
    source_id: str
    status: str = "ingested"


class CaptureDiscardResponse(BaseModel):
    """Response after discarding a capture."""

    capture_id: str
    status: str = "discarded"


class DiscardCaptureRequest(BaseModel):
    """Optional request body when discarding a capture."""

    reason: str | None = None


# ---------------------------------------------------------------------------
# RSS models
# ---------------------------------------------------------------------------


class RssFeedRequest(BaseModel):
    """Request to subscribe to an RSS feed."""

    feed_url: str
    title: str | None = None


class RssFeedResponse(BaseModel):
    """API response for an RSS feed subscription."""

    id: str
    feed_url: str
    title: str | None
    enabled: bool
    last_polled_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime


class RssFeedListResponse(BaseModel):
    """List of RSS feed subscriptions."""

    feeds: list[RssFeedResponse]


class RssFeedToggleRequest(BaseModel):
    """Request to enable or disable an RSS feed."""

    enabled: bool


class RssPollResponse(BaseModel):
    """Response after triggering an RSS poll."""

    feed_id: str
    new_captures: int
    status: str = "polled"


# ---------------------------------------------------------------------------
# Ambient adapter configuration request/response models (issue #442)
# ---------------------------------------------------------------------------


class AmbientAdapterConfigureRequest(BaseModel):
    """Request to configure an ambient capture adapter."""

    adapter_type: str = Field(min_length=1, max_length=100)
    enabled: bool = True
    settings: dict[str, str] = Field(default_factory=dict)


class AmbientAdapterStatusResponse(BaseModel):
    """API response for an ambient adapter's status."""

    adapter_type: str
    enabled: bool
    last_polled_at: datetime | None = None
    settings: dict[str, str] = Field(default_factory=dict)


class AmbientAdapterListResponse(BaseModel):
    """List of configured ambient adapters."""

    adapters: list[AmbientAdapterStatusResponse]


class AmbientPollResponse(BaseModel):
    """Response after triggering an ambient adapter poll."""

    adapter_type: str
    new_captures: int
    status: str = "polled"
