"""Capture tables — ambient capture sources, RSS feeds, and adapter settings."""

import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from wikimind._datetime import utcnow_naive
from wikimind.models.enums import CaptureKind, CaptureStatus


class CaptureSource(SQLModel, table=True):
    """An item captured by an ambient capture adapter (issue #442).

    Captures are cheap and promiscuous: every item matching an adapter's
    filter is logged here. A triage step (manual or auto) decides whether
    to promote the capture to a full Source for compilation, or discard it.

    Lifecycle: captured -> triaged -> ingested | discarded
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    kind: CaptureKind
    external_id: str | None = Field(default=None, index=True)
    title: str | None = None
    raw_payload: str  # JSON blob or plain text
    content_hash: str = Field(default="", index=True)
    status: CaptureStatus = CaptureStatus.CAPTURED
    source_url: str | None = None
    source_id: str | None = Field(default=None, foreign_key="source.id")
    received_at: datetime = Field(default_factory=utcnow_naive)
    triaged_at: datetime | None = None
    ingested_at: datetime | None = None
    discarded_at: datetime | None = None
    discard_reason: str | None = None


class AmbientAdapterSetting(SQLModel, table=True):
    """Persisted configuration for an ambient capture adapter (issue #442).

    Each row represents one adapter type for one user. The ``settings_json``
    column stores adapter-specific key-value pairs as a JSON string.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    adapter_type: str = Field(index=True)
    enabled: bool = True
    settings_json: str = "{}"
    last_polled_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow_naive)


class RssFeed(SQLModel, table=True):
    """A user-subscribed RSS/Atom feed (issue #442).

    The RSS adapter polls each enabled feed on a schedule, creating
    CaptureSource rows for new entries (deduped by guid or link).
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    feed_url: str
    title: str | None = None
    enabled: bool = True
    last_polled_at: datetime | None = None
    last_entry_id: str | None = None  # guid or link of most recent entry
    error_message: str | None = None
    created_at: datetime = Field(default_factory=utcnow_naive)
