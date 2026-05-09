"""RSS feed subscription management service (issue #442).

Manages feed CRUD and delegates polling to the RSS adapter.
"""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING

import structlog
from sqlmodel import select

from wikimind.errors import NotFoundError
from wikimind.ingest.adapters.rss import RssAdapter
from wikimind.models import (
    RssFeed,
    RssFeedListResponse,
    RssFeedResponse,
    RssPollResponse,
)

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

log = structlog.get_logger()


def _feed_to_response(feed: RssFeed) -> RssFeedResponse:
    """Convert an RssFeed row to an API response."""
    return RssFeedResponse(
        id=feed.id,
        feed_url=feed.feed_url,
        title=feed.title,
        enabled=feed.enabled,
        last_polled_at=feed.last_polled_at,
        error_message=feed.error_message,
        created_at=feed.created_at,
    )


class RssService:
    """Manages RSS feed subscriptions and polling."""

    def __init__(self) -> None:
        self._adapter = RssAdapter()

    async def subscribe(
        self,
        feed_url: str,
        session: AsyncSession,
        user_id: str,
        *,
        title: str | None = None,
    ) -> RssFeedResponse:
        """Subscribe to an RSS feed.

        Args:
            feed_url: The URL of the RSS/Atom feed.
            session: Async database session.
            user_id: Owner of this subscription.
            title: Optional human-readable title for the feed.

        Returns:
            RssFeedResponse for the new subscription.
        """
        # Check for existing subscription to same URL
        existing = await session.execute(
            select(RssFeed).where(
                RssFeed.user_id == user_id,
                RssFeed.feed_url == feed_url,
            )
        )
        found = existing.scalars().first()
        if found is not None:
            return _feed_to_response(found)

        feed = RssFeed(
            user_id=user_id,
            feed_url=feed_url,
            title=title,
        )
        session.add(feed)
        await session.commit()
        await session.refresh(feed)

        log.info("RSS feed subscribed", feed_id=feed.id, feed_url=feed_url)
        return _feed_to_response(feed)

    async def list_feeds(
        self,
        session: AsyncSession,
        user_id: str,
    ) -> RssFeedListResponse:
        """List all RSS feed subscriptions for a user.

        Args:
            session: Async database session.
            user_id: Owner filter.

        Returns:
            RssFeedListResponse with all feeds.
        """
        result = await session.execute(
            select(RssFeed).where(RssFeed.user_id == user_id).order_by(RssFeed.created_at.desc())  # type: ignore[attr-defined]
        )
        feeds = list(result.scalars().all())
        return RssFeedListResponse(feeds=[_feed_to_response(f) for f in feeds])

    async def get_feed(
        self,
        feed_id: str,
        session: AsyncSession,
        user_id: str,
    ) -> RssFeed:
        """Retrieve a single feed by ID.

        Args:
            feed_id: The feed UUID.
            session: Async database session.
            user_id: Owner verification.

        Returns:
            The RssFeed record.

        Raises:
            NotFoundError: If the feed doesn't exist or belongs to another user.
        """
        feed = await session.get(RssFeed, feed_id)
        msg = "Feed not found"
        if not feed:
            raise NotFoundError(msg)
        if feed.user_id != user_id:
            raise NotFoundError(msg)
        return feed

    async def toggle_feed(
        self,
        feed_id: str,
        session: AsyncSession,
        user_id: str,
        *,
        enabled: bool,
    ) -> RssFeedResponse:
        """Enable or disable an RSS feed.

        Args:
            feed_id: The feed UUID.
            session: Async database session.
            user_id: Owner verification.
            enabled: Whether the feed should be enabled.

        Returns:
            Updated RssFeedResponse.
        """
        feed = await self.get_feed(feed_id, session, user_id)
        feed.enabled = enabled
        session.add(feed)
        await session.commit()
        return _feed_to_response(feed)

    async def delete_feed(
        self,
        feed_id: str,
        session: AsyncSession,
        user_id: str,
    ) -> None:
        """Delete an RSS feed subscription.

        Args:
            feed_id: The feed UUID.
            session: Async database session.
            user_id: Owner verification.

        Raises:
            NotFoundError: If the feed doesn't exist or belongs to another user.
        """
        feed = await self.get_feed(feed_id, session, user_id)
        await session.delete(feed)
        await session.commit()
        log.info("RSS feed deleted", feed_id=feed_id)

    async def poll_feed(
        self,
        feed_id: str,
        session: AsyncSession,
        user_id: str,
    ) -> RssPollResponse:
        """Manually trigger a poll for a single feed.

        Args:
            feed_id: The feed UUID.
            session: Async database session.
            user_id: Owner verification.

        Returns:
            RssPollResponse with the number of new captures.
        """
        feed = await self.get_feed(feed_id, session, user_id)
        new_count = await self._adapter.poll_feed(feed, session)
        return RssPollResponse(
            feed_id=feed.id,
            new_captures=new_count,
        )

    async def poll_all_feeds(
        self,
        session: AsyncSession,
        user_id: str,
    ) -> int:
        """Poll all enabled feeds for a user.

        Args:
            session: Async database session.
            user_id: Owner filter.

        Returns:
            Total number of new captures across all feeds.
        """
        result = await session.execute(
            select(RssFeed).where(
                RssFeed.user_id == user_id,
                RssFeed.enabled == True,  # noqa: E712
            )
        )
        feeds = list(result.scalars().all())

        total_new = 0
        for feed in feeds:
            new_count = await self._adapter.poll_feed(feed, session)
            total_new += new_count

        return total_new


@functools.lru_cache(maxsize=1)
def get_rss_service() -> RssService:
    """Return a singleton RssService instance for FastAPI dependency injection."""
    return RssService()
