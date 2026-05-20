"""Base class for ambient capture adapters (issue #442).

Ambient adapters poll external sources on a schedule and yield
``CapturedItem`` objects for each new piece of content discovered.
Concrete adapters extend ``AmbientAdapter`` and implement ``poll()``.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from wikimind._datetime import utcnow_naive

if TYPE_CHECKING:
    from datetime import datetime

    from sqlmodel.ext.asyncio.session import AsyncSession

    from wikimind.models import CaptureKind


@dataclass
class CapturedItem:
    """A single item discovered by an ambient adapter.

    Attributes:
        kind: The adapter kind that produced this item.
        title: Human-readable title (if available).
        content: Raw payload text.
        source_url: URL associated with the content (if any).
        external_id: External identifier for dedup (e.g. browser history URL).
    """

    kind: CaptureKind
    title: str | None = None
    content: str = ""
    source_url: str | None = None
    external_id: str | None = None


@dataclass
class AdapterConfig:
    """Runtime configuration for an ambient adapter instance.

    Attributes:
        enabled: Whether this adapter is active.
        adapter_type: String identifier for the adapter (e.g. "browser_history").
        settings: Adapter-specific key-value settings.
    """

    enabled: bool = False
    adapter_type: str = ""
    settings: dict[str, str] = field(default_factory=dict)


class AmbientAdapter(abc.ABC):
    """Abstract base class for ambient capture adapters.

    Subclasses must implement ``poll()`` which returns new items since
    the last poll. The ``last_polled_at`` timestamp tracks recency so
    adapters can avoid re-fetching old data.
    """

    def __init__(self, config: AdapterConfig) -> None:
        self.config = config
        self.last_polled_at: datetime | None = None

    @property
    def adapter_type(self) -> str:
        """Return the adapter type identifier."""
        return self.config.adapter_type

    @property
    def enabled(self) -> bool:
        """Return whether this adapter is currently enabled."""
        return self.config.enabled

    @abc.abstractmethod
    async def poll(self, session: AsyncSession, user_id: str) -> list[CapturedItem]:
        """Fetch new items since the last poll.

        Args:
            session: Async database session (for dedup checks).
            user_id: The user this adapter is polling for.

        Returns:
            A list of newly discovered items.
        """
        ...  # pragma: no cover

    def mark_polled(self) -> None:
        """Update the last_polled_at timestamp to now."""
        self.last_polled_at = utcnow_naive()
