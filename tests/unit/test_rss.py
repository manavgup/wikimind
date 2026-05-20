"""Tests for the RSS adapter (ingest/adapters/rss.py) and RSS service (services/rss.py).

Covers XML parsing (RSS 2.0 and Atom), deduplication, feed polling with
mocked HTTP, and the service-layer CRUD operations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlmodel import select

from tests.conftest import TEST_USER_ID
from wikimind.ingest.adapters.rss import (
    RssAdapter,
    _parse_feed_entries,
)
from wikimind.models import (
    CaptureKind,
    CaptureSource,
    CaptureStatus,
    RssFeed,
)
from wikimind.services.rss import RssService, _feed_to_response

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# XML parsing — _parse_feed_entries
# ---------------------------------------------------------------------------

RSS_FEED_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <guid>entry-1</guid>
      <title>First Post</title>
      <link>https://example.com/1</link>
      <description>First post summary.</description>
    </item>
    <item>
      <guid>entry-2</guid>
      <title>Second Post</title>
      <link>https://example.com/2</link>
      <description>Second post summary.</description>
    </item>
  </channel>
</rss>
"""

ATOM_FEED_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Test Feed</title>
  <entry>
    <id>urn:atom:entry-1</id>
    <title>Atom First</title>
    <link href="https://example.com/atom/1" />
    <summary>Atom first summary.</summary>
  </entry>
  <entry>
    <id>urn:atom:entry-2</id>
    <title>Atom Second</title>
    <link href="https://example.com/atom/2" />
    <content>Atom second full content.</content>
  </entry>
</feed>
"""


class TestParseFeedEntries:
    def test_rss_20_parsing(self):
        entries = _parse_feed_entries(RSS_FEED_XML)
        assert len(entries) == 2
        assert entries[0]["guid"] == "entry-1"
        assert entries[0]["title"] == "First Post"
        assert entries[0]["link"] == "https://example.com/1"
        assert entries[0]["summary"] == "First post summary."

    def test_atom_parsing(self):
        entries = _parse_feed_entries(ATOM_FEED_XML)
        assert len(entries) == 2
        assert entries[0]["guid"] == "urn:atom:entry-1"
        assert entries[0]["title"] == "Atom First"
        assert entries[0]["link"] == "https://example.com/atom/1"
        assert entries[0]["summary"] == "Atom first summary."
        # Second entry: summary is empty, falls back to content
        assert entries[1]["summary"] == "Atom second full content."

    def test_invalid_xml_returns_empty(self):
        entries = _parse_feed_entries("not valid xml <broken>")
        assert entries == []

    def test_empty_feed_returns_empty(self):
        xml = '<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>'
        entries = _parse_feed_entries(xml)
        assert entries == []

    def test_rss_item_without_guid_uses_link(self):
        xml = """\
<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>No GUID</title>
    <link>https://example.com/no-guid</link>
    <description>Body.</description>
  </item>
</channel></rss>
"""
        entries = _parse_feed_entries(xml)
        assert len(entries) == 1
        assert entries[0]["guid"] == "https://example.com/no-guid"

    def test_rss_item_without_guid_or_link_is_skipped(self):
        xml = """\
<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Ghost Entry</title>
    <description>No identifier.</description>
  </item>
</channel></rss>
"""
        entries = _parse_feed_entries(xml)
        assert len(entries) == 0


# ---------------------------------------------------------------------------
# RssAdapter.poll_feed — mocked HTTP
# ---------------------------------------------------------------------------


def _make_feed(**overrides) -> RssFeed:
    """Create an RssFeed instance for testing."""
    defaults = {
        "user_id": TEST_USER_ID,
        "feed_url": "https://example.com/rss.xml",
        "title": "Test Feed",
        "enabled": True,
    }
    defaults.update(overrides)
    return RssFeed(**defaults)


@pytest.mark.asyncio
async def test_poll_feed_creates_captures(db_session: AsyncSession) -> None:
    """Polling a feed with new entries creates CaptureSource rows."""
    feed = _make_feed()
    db_session.add(feed)
    await db_session.commit()
    await db_session.refresh(feed)

    mock_response = httpx.Response(200, text=RSS_FEED_XML, request=httpx.Request("GET", feed.feed_url))

    with patch("wikimind.ingest.adapters.rss.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        adapter = RssAdapter()
        new_count = await adapter.poll_feed(feed, db_session)

    assert new_count == 2

    result = await db_session.execute(select(CaptureSource).where(CaptureSource.user_id == TEST_USER_ID))
    captures = list(result.scalars().all())
    assert len(captures) == 2
    assert all(c.kind == CaptureKind.RSS for c in captures)
    assert all(c.status == CaptureStatus.CAPTURED for c in captures)

    # Feed metadata updated
    await db_session.refresh(feed)
    assert feed.last_polled_at is not None
    assert feed.error_message is None


@pytest.mark.asyncio
async def test_poll_feed_deduplicates(db_session: AsyncSession) -> None:
    """Polling the same feed twice does not create duplicate captures."""
    feed = _make_feed()
    db_session.add(feed)
    await db_session.commit()
    await db_session.refresh(feed)

    mock_response = httpx.Response(200, text=RSS_FEED_XML, request=httpx.Request("GET", feed.feed_url))

    with patch("wikimind.ingest.adapters.rss.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        adapter = RssAdapter()
        first_count = await adapter.poll_feed(feed, db_session)
        second_count = await adapter.poll_feed(feed, db_session)

    assert first_count == 2
    assert second_count == 0  # all entries already captured


@pytest.mark.asyncio
async def test_poll_feed_http_error(db_session: AsyncSession) -> None:
    """HTTP error sets error_message on the feed and returns 0."""
    feed = _make_feed()
    db_session.add(feed)
    await db_session.commit()
    await db_session.refresh(feed)

    with patch("wikimind.ingest.adapters.rss.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        adapter = RssAdapter()
        count = await adapter.poll_feed(feed, db_session)

    assert count == 0
    await db_session.refresh(feed)
    assert feed.error_message is not None
    assert feed.last_polled_at is not None


# ---------------------------------------------------------------------------
# RssService — CRUD operations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rss_service_subscribe(db_session: AsyncSession) -> None:
    """Subscribe creates a new RssFeed row."""
    service = RssService()
    resp = await service.subscribe(
        "https://blog.example.com/feed",
        db_session,
        TEST_USER_ID,
        title="My Blog",
    )
    assert resp.feed_url == "https://blog.example.com/feed"
    assert resp.title == "My Blog"
    assert resp.enabled is True


@pytest.mark.asyncio
async def test_rss_service_subscribe_idempotent(db_session: AsyncSession) -> None:
    """Subscribing to the same URL twice returns the existing feed."""
    service = RssService()
    first = await service.subscribe("https://blog.example.com/feed", db_session, TEST_USER_ID)
    second = await service.subscribe("https://blog.example.com/feed", db_session, TEST_USER_ID)
    assert first.id == second.id


@pytest.mark.asyncio
async def test_rss_service_list_feeds(db_session: AsyncSession) -> None:
    """list_feeds returns all subscriptions for the user."""
    service = RssService()
    await service.subscribe("https://a.example.com/feed", db_session, TEST_USER_ID)
    await service.subscribe("https://b.example.com/feed", db_session, TEST_USER_ID)

    feeds = await service.list_feeds(db_session, TEST_USER_ID)
    assert len(feeds.feeds) == 2


@pytest.mark.asyncio
async def test_rss_service_toggle_feed(db_session: AsyncSession) -> None:
    """toggle_feed enables/disables a feed."""
    service = RssService()
    resp = await service.subscribe("https://a.example.com/feed", db_session, TEST_USER_ID)

    toggled = await service.toggle_feed(resp.id, db_session, TEST_USER_ID, enabled=False)
    assert toggled.enabled is False

    toggled_back = await service.toggle_feed(resp.id, db_session, TEST_USER_ID, enabled=True)
    assert toggled_back.enabled is True


@pytest.mark.asyncio
async def test_rss_service_delete_feed(db_session: AsyncSession) -> None:
    """delete_feed removes the subscription."""
    service = RssService()
    resp = await service.subscribe("https://a.example.com/feed", db_session, TEST_USER_ID)

    await service.delete_feed(resp.id, db_session, TEST_USER_ID)

    feeds = await service.list_feeds(db_session, TEST_USER_ID)
    assert len(feeds.feeds) == 0


@pytest.mark.asyncio
async def test_rss_service_get_feed_not_found(db_session: AsyncSession) -> None:
    """get_feed raises NotFoundError for non-existent feed."""
    from wikimind.errors import NotFoundError

    service = RssService()
    with pytest.raises(NotFoundError):
        await service.get_feed("nonexistent-id", db_session, TEST_USER_ID)


@pytest.mark.asyncio
async def test_rss_service_get_feed_wrong_user(db_session: AsyncSession) -> None:
    """get_feed raises NotFoundError when user_id doesn't match."""
    from wikimind.errors import NotFoundError

    service = RssService()
    resp = await service.subscribe("https://a.example.com/feed", db_session, TEST_USER_ID)

    with pytest.raises(NotFoundError):
        await service.get_feed(resp.id, db_session, "other-user")


@pytest.mark.asyncio
async def test_feed_to_response_mapping() -> None:
    """_feed_to_response correctly maps model fields to response fields."""
    feed = _make_feed(title="My Feed")
    resp = _feed_to_response(feed)
    assert resp.feed_url == "https://example.com/rss.xml"
    assert resp.title == "My Feed"
    assert resp.enabled is True
    assert resp.last_polled_at is None
