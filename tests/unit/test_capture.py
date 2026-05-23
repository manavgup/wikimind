"""Tests for ambient capture — inbox, RSS feeds, ambient adapters, and browser history (#442)."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

if TYPE_CHECKING:
    from pathlib import Path

import httpx
import pytest
from sqlmodel import select

from tests.conftest import TEST_USER_ID
from wikimind.errors import NotFoundError
from wikimind.ingest.adapters.ambient import AdapterConfig, CapturedItem
from wikimind.ingest.adapters.browser_history import (
    BrowserHistoryAdapter,
    _matches_patterns,
    _read_chrome_history,
    _read_firefox_history,
)
from wikimind.ingest.adapters.rss import RssAdapter, _parse_feed_entries
from wikimind.models import (
    AmbientAdapterConfigureRequest,
    CaptureKind,
    CaptureSource,
    CaptureStatus,
    RssFeed,
)
from wikimind.services.ambient import AmbientService
from wikimind.services.capture import CaptureService
from wikimind.services.rss import RssService

# ---------------------------------------------------------------------------
# RSS XML parser unit tests
# ---------------------------------------------------------------------------


class TestRssXmlParser:
    """Test RSS/Atom XML parsing."""

    def test_parse_rss20_basic(self) -> None:
        xml = """<?xml version="1.0"?>
        <rss version="2.0">
          <channel>
            <title>Test Feed</title>
            <item>
              <title>First Post</title>
              <link>https://example.com/1</link>
              <guid>guid-1</guid>
              <description>Summary of first post</description>
            </item>
            <item>
              <title>Second Post</title>
              <link>https://example.com/2</link>
              <guid>guid-2</guid>
              <description>Summary of second post</description>
            </item>
          </channel>
        </rss>"""
        entries = _parse_feed_entries(xml)
        assert len(entries) == 2
        assert entries[0]["guid"] == "guid-1"
        assert entries[0]["title"] == "First Post"
        assert entries[0]["link"] == "https://example.com/1"
        assert entries[0]["summary"] == "Summary of first post"

    def test_parse_atom_basic(self) -> None:
        xml = """<?xml version="1.0" encoding="utf-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <title>Atom Feed</title>
          <entry>
            <id>atom-id-1</id>
            <title>Atom Entry</title>
            <link href="https://example.com/atom/1"/>
            <summary>Atom summary</summary>
          </entry>
        </feed>"""
        entries = _parse_feed_entries(xml)
        assert len(entries) == 1
        assert entries[0]["guid"] == "atom-id-1"
        assert entries[0]["title"] == "Atom Entry"
        assert entries[0]["link"] == "https://example.com/atom/1"

    def test_parse_rss_without_guid_uses_link(self) -> None:
        xml = """<?xml version="1.0"?>
        <rss version="2.0">
          <channel>
            <item>
              <title>No GUID</title>
              <link>https://example.com/no-guid</link>
              <description>Has link but no guid</description>
            </item>
          </channel>
        </rss>"""
        entries = _parse_feed_entries(xml)
        assert len(entries) == 1
        assert entries[0]["guid"] == "https://example.com/no-guid"

    def test_parse_invalid_xml_returns_empty(self) -> None:
        entries = _parse_feed_entries("not xml at all")
        assert entries == []

    def test_parse_empty_feed_returns_empty(self) -> None:
        xml = """<?xml version="1.0"?>
        <rss version="2.0">
          <channel>
            <title>Empty Feed</title>
          </channel>
        </rss>"""
        entries = _parse_feed_entries(xml)
        assert entries == []


# ---------------------------------------------------------------------------
# CaptureService unit tests
# ---------------------------------------------------------------------------


class TestCaptureService:
    """Test the capture service layer."""

    @pytest.fixture
    def service(self) -> CaptureService:
        return CaptureService()

    @pytest.mark.asyncio
    async def test_create_capture(self, service: CaptureService, db_session) -> None:
        resp = await service.create_capture(
            kind=CaptureKind.SHARE_TARGET,
            content="Some captured content",
            session=db_session,
            user_id=TEST_USER_ID,
            title="Test Capture",
            source_url="https://example.com/article",
        )
        assert resp.kind == CaptureKind.SHARE_TARGET
        assert resp.title == "Test Capture"
        assert resp.status == CaptureStatus.CAPTURED
        assert resp.source_url == "https://example.com/article"

    @pytest.mark.asyncio
    async def test_create_capture_dedup(self, service: CaptureService, db_session) -> None:
        """Creating the same capture twice returns the existing one."""
        resp1 = await service.create_capture(
            kind=CaptureKind.SHARE_TARGET,
            content="Duplicate content",
            session=db_session,
            user_id=TEST_USER_ID,
        )
        resp2 = await service.create_capture(
            kind=CaptureKind.SHARE_TARGET,
            content="Duplicate content",
            session=db_session,
            user_id=TEST_USER_ID,
        )
        assert resp1.id == resp2.id

    @pytest.mark.asyncio
    async def test_list_captures(self, service: CaptureService, db_session) -> None:
        for i in range(3):
            await service.create_capture(
                kind=CaptureKind.SHARE_TARGET,
                content=f"Content {i}",
                session=db_session,
                user_id=TEST_USER_ID,
            )
        result = await service.list_captures(db_session, TEST_USER_ID)
        assert result.total == 3
        assert len(result.items) == 3

    @pytest.mark.asyncio
    async def test_list_captures_filter_status(self, service: CaptureService, db_session) -> None:
        await service.create_capture(
            kind=CaptureKind.SHARE_TARGET,
            content="Captured item",
            session=db_session,
            user_id=TEST_USER_ID,
        )
        result = await service.list_captures(db_session, TEST_USER_ID, status=CaptureStatus.CAPTURED)
        assert result.total == 1

        result = await service.list_captures(db_session, TEST_USER_ID, status=CaptureStatus.INGESTED)
        assert result.total == 0

    @pytest.mark.asyncio
    async def test_list_captures_filter_kind(self, service: CaptureService, db_session) -> None:
        await service.create_capture(
            kind=CaptureKind.RSS,
            content="RSS item",
            session=db_session,
            user_id=TEST_USER_ID,
        )
        await service.create_capture(
            kind=CaptureKind.SHARE_TARGET,
            content="Share target item",
            session=db_session,
            user_id=TEST_USER_ID,
        )
        result = await service.list_captures(db_session, TEST_USER_ID, kind=CaptureKind.RSS)
        assert result.total == 1
        assert result.items[0].kind == CaptureKind.RSS

    @pytest.mark.asyncio
    async def test_discard_capture(self, service: CaptureService, db_session) -> None:
        resp = await service.create_capture(
            kind=CaptureKind.SHARE_TARGET,
            content="Will be discarded",
            session=db_session,
            user_id=TEST_USER_ID,
        )
        discard_resp = await service.discard_capture(resp.id, db_session, TEST_USER_ID, reason="Low quality")
        assert discard_resp.capture_id == resp.id
        assert discard_resp.status == "discarded"

        # Verify in DB
        capture = await db_session.get(CaptureSource, resp.id)
        assert capture is not None
        assert capture.status == CaptureStatus.DISCARDED
        assert capture.discard_reason == "Low quality"
        assert capture.discarded_at is not None

    @pytest.mark.asyncio
    async def test_ingest_capture_text(self, service: CaptureService, db_session) -> None:
        """Promoting a text capture creates a Source via the ingest service."""
        resp = await service.create_capture(
            kind=CaptureKind.SHARE_TARGET,
            content="Content to ingest into wiki",
            session=db_session,
            user_id=TEST_USER_ID,
            title="Ingested Capture",
        )

        mock_source = AsyncMock()
        mock_source.id = "source-123"
        mock_ingest = AsyncMock()
        mock_ingest.ingest_text = AsyncMock(return_value=mock_source)
        mock_ingest.ingest_url = AsyncMock(return_value=mock_source)

        with patch("wikimind.services.factories.get_ingest_service", return_value=mock_ingest):
            ingest_resp = await service.ingest_capture(resp.id, db_session, TEST_USER_ID)

        assert ingest_resp.capture_id == resp.id
        assert ingest_resp.source_id == "source-123"
        assert ingest_resp.status == "ingested"

        # Verify capture status updated
        capture = await db_session.get(CaptureSource, resp.id)
        assert capture is not None
        assert capture.status == CaptureStatus.INGESTED
        assert capture.source_id == "source-123"

    @pytest.mark.asyncio
    async def test_ingest_capture_url(self, service: CaptureService, db_session) -> None:
        """Promoting a capture with a URL ingests via ingest_url."""
        resp = await service.create_capture(
            kind=CaptureKind.SHARE_TARGET,
            content="Article content",
            session=db_session,
            user_id=TEST_USER_ID,
            source_url="https://example.com/article",
        )

        mock_source = AsyncMock()
        mock_source.id = "source-url-456"
        mock_ingest = AsyncMock()
        mock_ingest.ingest_url = AsyncMock(return_value=mock_source)

        with patch("wikimind.services.factories.get_ingest_service", return_value=mock_ingest):
            ingest_resp = await service.ingest_capture(resp.id, db_session, TEST_USER_ID)

        assert ingest_resp.source_id == "source-url-456"
        mock_ingest.ingest_url.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_capture_not_found(self, service: CaptureService, db_session) -> None:
        with pytest.raises(NotFoundError):
            await service.get_capture("nonexistent-id", db_session, TEST_USER_ID)

    @pytest.mark.asyncio
    async def test_get_capture_wrong_user(self, service: CaptureService, db_session) -> None:
        resp = await service.create_capture(
            kind=CaptureKind.SHARE_TARGET,
            content="Belongs to test-user",
            session=db_session,
            user_id=TEST_USER_ID,
        )
        with pytest.raises(NotFoundError):
            await service.get_capture(resp.id, db_session, "other-user")


# ---------------------------------------------------------------------------
# RssService unit tests
# ---------------------------------------------------------------------------


class TestRssService:
    """Test the RSS feed service layer."""

    @pytest.fixture
    def service(self) -> RssService:
        return RssService()

    @pytest.mark.asyncio
    async def test_subscribe(self, service: RssService, db_session) -> None:
        resp = await service.subscribe(
            feed_url="https://example.com/feed.xml",
            session=db_session,
            user_id=TEST_USER_ID,
            title="Example Feed",
        )
        assert resp.feed_url == "https://example.com/feed.xml"
        assert resp.title == "Example Feed"
        assert resp.enabled is True

    @pytest.mark.asyncio
    async def test_subscribe_idempotent(self, service: RssService, db_session) -> None:
        """Subscribing to the same URL twice returns the existing feed."""
        resp1 = await service.subscribe(
            feed_url="https://example.com/feed.xml",
            session=db_session,
            user_id=TEST_USER_ID,
        )
        resp2 = await service.subscribe(
            feed_url="https://example.com/feed.xml",
            session=db_session,
            user_id=TEST_USER_ID,
        )
        assert resp1.id == resp2.id

    @pytest.mark.asyncio
    async def test_list_feeds(self, service: RssService, db_session) -> None:
        await service.subscribe("https://a.com/feed", db_session, TEST_USER_ID)
        await service.subscribe("https://b.com/feed", db_session, TEST_USER_ID)
        result = await service.list_feeds(db_session, TEST_USER_ID)
        assert len(result.feeds) == 2

    @pytest.mark.asyncio
    async def test_toggle_feed(self, service: RssService, db_session) -> None:
        resp = await service.subscribe("https://a.com/feed", db_session, TEST_USER_ID)
        updated = await service.toggle_feed(resp.id, db_session, TEST_USER_ID, enabled=False)
        assert updated.enabled is False

    @pytest.mark.asyncio
    async def test_delete_feed(self, service: RssService, db_session) -> None:
        resp = await service.subscribe("https://a.com/feed", db_session, TEST_USER_ID)
        await service.delete_feed(resp.id, db_session, TEST_USER_ID)
        result = await service.list_feeds(db_session, TEST_USER_ID)
        assert len(result.feeds) == 0

    @pytest.mark.asyncio
    async def test_delete_feed_not_found(self, service: RssService, db_session) -> None:
        with pytest.raises(NotFoundError):
            await service.delete_feed("nonexistent-id", db_session, TEST_USER_ID)


# ---------------------------------------------------------------------------
# RSS Adapter poll test
# ---------------------------------------------------------------------------


class TestRssAdapterPoll:
    """Test RSS adapter polling with mocked HTTP."""

    @pytest.mark.asyncio
    async def test_poll_creates_captures(self, db_session) -> None:
        feed = RssFeed(
            user_id=TEST_USER_ID,
            feed_url="https://example.com/feed.xml",
            title="Test Feed",
        )
        db_session.add(feed)
        await db_session.commit()
        await db_session.refresh(feed)

        rss_xml = """<?xml version="1.0"?>
        <rss version="2.0">
          <channel>
            <title>Test</title>
            <item>
              <title>Post 1</title>
              <link>https://example.com/1</link>
              <guid>guid-1</guid>
              <description>First post summary</description>
            </item>
            <item>
              <title>Post 2</title>
              <link>https://example.com/2</link>
              <guid>guid-2</guid>
              <description>Second post summary</description>
            </item>
          </channel>
        </rss>"""

        mock_response = AsyncMock()
        mock_response.text = rss_xml
        mock_response.raise_for_status = lambda: None

        adapter = RssAdapter()
        with patch("wikimind.ingest.adapters.rss.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            new_count = await adapter.poll_feed(feed, db_session)

        assert new_count == 2

        # Verify captures created
        result = await db_session.exec(select(CaptureSource).where(CaptureSource.user_id == TEST_USER_ID))
        captures = list(result.all())
        assert len(captures) == 2
        assert all(c.kind == CaptureKind.RSS for c in captures)

    @pytest.mark.asyncio
    async def test_poll_deduplicates(self, db_session) -> None:
        """Polling the same feed twice doesn't create duplicate captures."""
        feed = RssFeed(
            user_id=TEST_USER_ID,
            feed_url="https://example.com/feed.xml",
        )
        db_session.add(feed)
        await db_session.commit()
        await db_session.refresh(feed)

        rss_xml = """<?xml version="1.0"?>
        <rss version="2.0">
          <channel>
            <item>
              <title>Post 1</title>
              <link>https://example.com/1</link>
              <guid>guid-1</guid>
              <description>Summary</description>
            </item>
          </channel>
        </rss>"""

        mock_response = AsyncMock()
        mock_response.text = rss_xml
        mock_response.raise_for_status = lambda: None

        adapter = RssAdapter()
        with patch("wikimind.ingest.adapters.rss.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            count1 = await adapter.poll_feed(feed, db_session)
            count2 = await adapter.poll_feed(feed, db_session)

        assert count1 == 1
        assert count2 == 0  # No new captures on second poll

    @pytest.mark.asyncio
    async def test_poll_handles_http_error(self, db_session) -> None:
        """HTTP errors during poll are recorded on the feed, not raised."""
        feed = RssFeed(
            user_id=TEST_USER_ID,
            feed_url="https://example.com/broken-feed.xml",
        )
        db_session.add(feed)
        await db_session.commit()
        await db_session.refresh(feed)

        adapter = RssAdapter()
        with patch("wikimind.ingest.adapters.rss.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            new_count = await adapter.poll_feed(feed, db_session)

        assert new_count == 0
        # Error recorded on feed
        await db_session.refresh(feed)
        assert feed.error_message is not None
        assert feed.last_polled_at is not None


# ---------------------------------------------------------------------------
# API route integration tests
# ---------------------------------------------------------------------------


class TestCaptureAPI:
    """Test capture API routes via the FastAPI test client."""

    @pytest.mark.asyncio
    async def test_create_capture_endpoint(self, client) -> None:
        resp = await client.post(
            "/api/capture/share_target",
            json={
                "content": "Shared article content",
                "title": "Shared Article",
                "source_url": "https://example.com/shared",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["kind"] == "share_target"
        assert data["title"] == "Shared Article"
        assert data["status"] == "captured"

    @pytest.mark.asyncio
    async def test_list_captures_endpoint(self, client) -> None:
        # Create a capture first
        await client.post(
            "/api/capture/share_target",
            json={"content": "Some content"},
        )
        resp = await client.get("/api/capture")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert len(data["items"]) >= 1

    @pytest.mark.asyncio
    async def test_list_captures_with_status_filter(self, client) -> None:
        await client.post(
            "/api/capture/share_target",
            json={"content": "Filtered content"},
        )
        resp = await client.get("/api/capture?status=captured")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1

        resp = await client.get("/api/capture?status=ingested")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_discard_capture_endpoint(self, client) -> None:
        create_resp = await client.post(
            "/api/capture/share_target",
            json={"content": "To be discarded"},
        )
        capture_id = create_resp.json()["id"]

        resp = await client.post(
            f"/api/capture/{capture_id}/discard",
            json={"reason": "Not relevant"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "discarded"

    @pytest.mark.asyncio
    async def test_rss_subscribe_endpoint(self, client) -> None:
        resp = await client.post(
            "/api/capture/rss/feeds",
            json={"feed_url": "https://example.com/feed.xml", "title": "My Feed"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["feed_url"] == "https://example.com/feed.xml"
        assert data["enabled"] is True

    @pytest.mark.asyncio
    async def test_rss_list_feeds_endpoint(self, client) -> None:
        await client.post(
            "/api/capture/rss/feeds",
            json={"feed_url": "https://example.com/feed1.xml"},
        )
        resp = await client.get("/api/capture/rss/feeds")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["feeds"]) >= 1

    @pytest.mark.asyncio
    async def test_rss_toggle_feed_endpoint(self, client) -> None:
        create_resp = await client.post(
            "/api/capture/rss/feeds",
            json={"feed_url": "https://example.com/toggle.xml"},
        )
        feed_id = create_resp.json()["id"]

        resp = await client.patch(
            f"/api/capture/rss/feeds/{feed_id}",
            json={"enabled": False},
        )
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

    @pytest.mark.asyncio
    async def test_rss_delete_feed_endpoint(self, client) -> None:
        create_resp = await client.post(
            "/api/capture/rss/feeds",
            json={"feed_url": "https://example.com/delete.xml"},
        )
        feed_id = create_resp.json()["id"]

        resp = await client.delete(f"/api/capture/rss/feeds/{feed_id}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == feed_id


# ---------------------------------------------------------------------------
# AmbientAdapter base class unit tests
# ---------------------------------------------------------------------------


class TestAmbientAdapterBase:
    """Test the AmbientAdapter base class contract."""

    def test_adapter_config_defaults(self) -> None:
        config = AdapterConfig()
        assert config.enabled is False
        assert config.adapter_type == ""
        assert config.settings == {}

    def test_captured_item_fields(self) -> None:
        item = CapturedItem(
            kind=CaptureKind.BROWSER_HISTORY,
            title="Test Page",
            content="https://example.com",
            source_url="https://example.com",
            external_id="https://example.com",
        )
        assert item.kind == CaptureKind.BROWSER_HISTORY
        assert item.title == "Test Page"
        assert item.source_url == "https://example.com"

    def test_adapter_mark_polled(self) -> None:
        """mark_polled() updates last_polled_at."""
        config = AdapterConfig(enabled=True, adapter_type="browser_history")
        adapter = BrowserHistoryAdapter(config)
        assert adapter.last_polled_at is None
        adapter.mark_polled()
        assert adapter.last_polled_at is not None

    def test_adapter_properties(self) -> None:
        config = AdapterConfig(enabled=True, adapter_type="browser_history")
        adapter = BrowserHistoryAdapter(config)
        assert adapter.adapter_type == "browser_history"
        assert adapter.enabled is True


# ---------------------------------------------------------------------------
# URL pattern matching tests
# ---------------------------------------------------------------------------


class TestUrlPatternMatching:
    """Test URL pattern matching for browser history filtering."""

    def test_empty_patterns_match_all(self) -> None:
        assert _matches_patterns("https://example.com/any/path", []) is True

    def test_matching_pattern(self) -> None:
        patterns = [r"github\.com", r"stackoverflow\.com"]
        assert _matches_patterns("https://github.com/repo", patterns) is True
        assert _matches_patterns("https://stackoverflow.com/q/123", patterns) is True

    def test_non_matching_pattern(self) -> None:
        patterns = [r"github\.com"]
        assert _matches_patterns("https://example.com", patterns) is False

    def test_regex_patterns(self) -> None:
        patterns = [r".*\.md$", r"docs/.*"]
        assert _matches_patterns("https://example.com/file.md", patterns) is True
        assert _matches_patterns("https://example.com/docs/guide", patterns) is True
        assert _matches_patterns("https://example.com/index.html", patterns) is False


# ---------------------------------------------------------------------------
# Browser history SQLite reader tests
# ---------------------------------------------------------------------------


def _create_chrome_db(db_path: Path) -> None:
    """Create a minimal Chrome-like history SQLite database."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT)")
    conn.execute("CREATE TABLE visits (id INTEGER PRIMARY KEY, url INTEGER, visit_time INTEGER)")
    # Chrome epoch offset: 11644473600 seconds → microseconds
    chrome_offset = 11644473600 * 1_000_000
    # Add entries at Unix timestamp 1000 (well after epoch 0)
    ts = 1000 * 1_000_000 + chrome_offset
    conn.execute("INSERT INTO urls VALUES (1, 'https://example.com/page1', 'Page 1')")
    conn.execute("INSERT INTO urls VALUES (2, 'https://example.com/page2', 'Page 2')")
    conn.execute(f"INSERT INTO visits VALUES (1, 1, {ts})")
    conn.execute(f"INSERT INTO visits VALUES (2, 2, {ts + 1000})")
    conn.commit()
    conn.close()


def _create_firefox_db(db_path: Path) -> None:
    """Create a minimal Firefox-like places SQLite database."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE moz_places (id INTEGER PRIMARY KEY, url TEXT, title TEXT)")
    conn.execute("CREATE TABLE moz_historyvisits (id INTEGER PRIMARY KEY, place_id INTEGER, visit_date INTEGER)")
    # Firefox uses microseconds since Unix epoch
    ts = 1000 * 1_000_000
    conn.execute("INSERT INTO moz_places VALUES (1, 'https://mozilla.org/page1', 'MozPage 1')")
    conn.execute("INSERT INTO moz_places VALUES (2, 'https://mozilla.org/page2', 'MozPage 2')")
    conn.execute(f"INSERT INTO moz_historyvisits VALUES (1, 1, {ts})")
    conn.execute(f"INSERT INTO moz_historyvisits VALUES (2, 2, {ts + 1000})")
    conn.commit()
    conn.close()


class TestBrowserHistoryReader:
    """Test Chrome and Firefox history reading from SQLite."""

    def test_read_chrome_history(self, tmp_path: Path) -> None:
        db_path = tmp_path / "History"
        _create_chrome_db(db_path)
        entries = _read_chrome_history(db_path, since_timestamp=0, max_entries=10)
        assert len(entries) == 2
        assert entries[0]["url"] == "https://example.com/page2"
        assert entries[0]["title"] == "Page 2"

    def test_read_chrome_history_since_timestamp(self, tmp_path: Path) -> None:
        db_path = tmp_path / "History"
        _create_chrome_db(db_path)
        # Since timestamp after the entries were created
        entries = _read_chrome_history(db_path, since_timestamp=2000, max_entries=10)
        assert len(entries) == 0

    def test_read_chrome_history_max_entries(self, tmp_path: Path) -> None:
        db_path = tmp_path / "History"
        _create_chrome_db(db_path)
        entries = _read_chrome_history(db_path, since_timestamp=0, max_entries=1)
        assert len(entries) == 1

    def test_read_chrome_history_missing_db(self, tmp_path: Path) -> None:
        """Missing DB returns empty list, not an error."""
        entries = _read_chrome_history(tmp_path / "nonexistent.db", since_timestamp=0, max_entries=10)
        assert entries == []

    def test_read_firefox_history(self, tmp_path: Path) -> None:
        db_path = tmp_path / "places.sqlite"
        _create_firefox_db(db_path)
        entries = _read_firefox_history(db_path, since_timestamp=0, max_entries=10)
        assert len(entries) == 2
        assert entries[0]["url"] == "https://mozilla.org/page2"
        assert entries[0]["title"] == "MozPage 2"

    def test_read_firefox_history_since_timestamp(self, tmp_path: Path) -> None:
        db_path = tmp_path / "places.sqlite"
        _create_firefox_db(db_path)
        entries = _read_firefox_history(db_path, since_timestamp=2000, max_entries=10)
        assert len(entries) == 0


# ---------------------------------------------------------------------------
# BrowserHistoryAdapter integration tests (with mocked DB path)
# ---------------------------------------------------------------------------


class TestBrowserHistoryAdapter:
    """Test the BrowserHistoryAdapter with mocked history databases.

    Since user-supplied ``history_db_path`` was removed (security fix),
    tests mock ``_resolve_history_db`` to point at a temp SQLite file.
    """

    _RESOLVE_TARGET = "wikimind.ingest.adapters.browser_history._resolve_history_db"

    @pytest.mark.asyncio
    async def test_poll_returns_items(self, tmp_path: Path, db_session) -> None:
        db_path = tmp_path / "History"
        _create_chrome_db(db_path)

        config = AdapterConfig(
            enabled=True,
            adapter_type="browser_history",
            settings={"browser": "chrome"},
        )
        adapter = BrowserHistoryAdapter(config)
        with patch(self._RESOLVE_TARGET, return_value=db_path):
            items = await adapter.poll(db_session, TEST_USER_ID)

        assert len(items) == 2
        assert all(i.kind == CaptureKind.BROWSER_HISTORY for i in items)
        assert items[0].source_url in (
            "https://example.com/page1",
            "https://example.com/page2",
        )

    @pytest.mark.asyncio
    async def test_poll_with_include_patterns(self, tmp_path: Path, db_session) -> None:
        db_path = tmp_path / "History"
        _create_chrome_db(db_path)

        config = AdapterConfig(
            enabled=True,
            adapter_type="browser_history",
            settings={"browser": "chrome", "url_patterns": "page1"},
        )
        adapter = BrowserHistoryAdapter(config)
        with patch(self._RESOLVE_TARGET, return_value=db_path):
            items = await adapter.poll(db_session, TEST_USER_ID)
        assert len(items) == 1
        assert items[0].source_url == "https://example.com/page1"

    @pytest.mark.asyncio
    async def test_poll_with_exclude_patterns(self, tmp_path: Path, db_session) -> None:
        db_path = tmp_path / "History"
        _create_chrome_db(db_path)

        config = AdapterConfig(
            enabled=True,
            adapter_type="browser_history",
            settings={"browser": "chrome", "exclude_patterns": "page2"},
        )
        adapter = BrowserHistoryAdapter(config)
        with patch(self._RESOLVE_TARGET, return_value=db_path):
            items = await adapter.poll(db_session, TEST_USER_ID)
        assert len(items) == 1
        assert items[0].source_url == "https://example.com/page1"

    @pytest.mark.asyncio
    async def test_poll_deduplicates_existing_captures(self, tmp_path: Path, db_session) -> None:
        db_path = tmp_path / "History"
        _create_chrome_db(db_path)

        config = AdapterConfig(
            enabled=True,
            adapter_type="browser_history",
            settings={"browser": "chrome"},
        )
        adapter = BrowserHistoryAdapter(config)

        with patch(self._RESOLVE_TARGET, return_value=db_path):
            # First poll gets items
            items1 = await adapter.poll(db_session, TEST_USER_ID)
            assert len(items1) == 2

            # Simulate saving them as captures
            from wikimind.services.ambient import AmbientService

            svc = AmbientService()
            await svc._save_captured_items(items1, db_session, TEST_USER_ID)

            # Second poll should find zero new items (dedup)
            adapter2 = BrowserHistoryAdapter(config)
            items2 = await adapter2.poll(db_session, TEST_USER_ID)
            assert len(items2) == 0

    @pytest.mark.asyncio
    async def test_poll_no_db_found(self, db_session) -> None:
        """When _resolve_history_db returns None, poll returns empty list."""
        config = AdapterConfig(
            enabled=True,
            adapter_type="browser_history",
            settings={"browser": "chrome"},
        )
        adapter = BrowserHistoryAdapter(config)
        with patch(self._RESOLVE_TARGET, return_value=None):
            items = await adapter.poll(db_session, TEST_USER_ID)
        assert items == []

    @pytest.mark.asyncio
    async def test_poll_firefox(self, tmp_path: Path, db_session) -> None:
        db_path = tmp_path / "places.sqlite"
        _create_firefox_db(db_path)

        config = AdapterConfig(
            enabled=True,
            adapter_type="browser_history",
            settings={"browser": "firefox"},
        )
        adapter = BrowserHistoryAdapter(config)
        with patch(self._RESOLVE_TARGET, return_value=db_path):
            items = await adapter.poll(db_session, TEST_USER_ID)
        assert len(items) == 2
        assert all(i.kind == CaptureKind.BROWSER_HISTORY for i in items)


# ---------------------------------------------------------------------------
# AmbientService unit tests
# ---------------------------------------------------------------------------


class TestAmbientService:
    """Test the ambient adapter management service."""

    @pytest.fixture
    def service(self) -> AmbientService:
        return AmbientService()

    @pytest.mark.asyncio
    async def test_configure_adapter(self, service: AmbientService, db_session) -> None:
        request = AmbientAdapterConfigureRequest(
            adapter_type="browser_history",
            enabled=True,
            settings={"browser": "chrome"},
        )
        resp = await service.configure_adapter(request, db_session, TEST_USER_ID)
        assert resp.adapter_type == "browser_history"
        assert resp.enabled is True
        assert resp.settings["browser"] == "chrome"

    @pytest.mark.asyncio
    async def test_configure_adapter_upsert(self, service: AmbientService, db_session) -> None:
        """Configuring the same adapter twice updates instead of creating."""
        request1 = AmbientAdapterConfigureRequest(
            adapter_type="browser_history",
            enabled=True,
            settings={"browser": "chrome"},
        )
        _resp1 = await service.configure_adapter(request1, db_session, TEST_USER_ID)

        request2 = AmbientAdapterConfigureRequest(
            adapter_type="browser_history",
            enabled=False,
            settings={"browser": "firefox"},
        )
        resp2 = await service.configure_adapter(request2, db_session, TEST_USER_ID)

        assert resp2.enabled is False
        assert resp2.settings["browser"] == "firefox"

        # Only one setting row should exist
        result = await service.list_adapters(db_session, TEST_USER_ID)
        assert len(result.adapters) == 1

    @pytest.mark.asyncio
    async def test_configure_unsupported_adapter(self, service: AmbientService, db_session) -> None:
        request = AmbientAdapterConfigureRequest(
            adapter_type="nonexistent_adapter",
            enabled=True,
        )
        with pytest.raises(ValueError, match="Unsupported adapter type"):
            await service.configure_adapter(request, db_session, TEST_USER_ID)

    @pytest.mark.asyncio
    async def test_list_adapters_empty(self, service: AmbientService, db_session) -> None:
        result = await service.list_adapters(db_session, TEST_USER_ID)
        assert result.adapters == []

    @pytest.mark.asyncio
    async def test_list_adapters(self, service: AmbientService, db_session) -> None:
        request = AmbientAdapterConfigureRequest(
            adapter_type="browser_history",
            enabled=True,
        )
        await service.configure_adapter(request, db_session, TEST_USER_ID)
        result = await service.list_adapters(db_session, TEST_USER_ID)
        assert len(result.adapters) == 1
        assert result.adapters[0].adapter_type == "browser_history"

    @pytest.mark.asyncio
    async def test_get_adapter_setting_not_found(self, service: AmbientService, db_session) -> None:
        with pytest.raises(NotFoundError):
            await service.get_adapter_setting("browser_history", db_session, TEST_USER_ID)

    @pytest.mark.asyncio
    async def test_save_captured_items(self, service: AmbientService, db_session) -> None:
        items = [
            CapturedItem(
                kind=CaptureKind.BROWSER_HISTORY,
                title="Test Page",
                content="https://example.com/test",
                source_url="https://example.com/test",
                external_id="https://example.com/test",
            ),
        ]
        count = await service._save_captured_items(items, db_session, TEST_USER_ID)
        assert count == 1

        # Verify it was saved
        result = await db_session.execute(
            select(CaptureSource).where(
                CaptureSource.user_id == TEST_USER_ID,
                CaptureSource.kind == CaptureKind.BROWSER_HISTORY,
            )
        )
        captures = list(result.scalars().all())
        assert len(captures) == 1
        assert captures[0].source_url == "https://example.com/test"

    @pytest.mark.asyncio
    async def test_save_captured_items_dedup(self, service: AmbientService, db_session) -> None:
        """Duplicate items are not saved twice."""
        items = [
            CapturedItem(
                kind=CaptureKind.BROWSER_HISTORY,
                content="https://example.com/dup",
            ),
        ]
        count1 = await service._save_captured_items(items, db_session, TEST_USER_ID)
        count2 = await service._save_captured_items(items, db_session, TEST_USER_ID)
        assert count1 == 1
        assert count2 == 0


# ---------------------------------------------------------------------------
# Ambient API route integration tests
# ---------------------------------------------------------------------------


class TestAmbientAPI:
    """Test ambient adapter API routes via the FastAPI test client."""

    @pytest.mark.asyncio
    async def test_configure_adapter_endpoint(self, client) -> None:
        resp = await client.post(
            "/api/capture/ambient/configure",
            json={
                "adapter_type": "browser_history",
                "enabled": True,
                "settings": {"browser": "chrome"},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["adapter_type"] == "browser_history"
        assert data["enabled"] is True
        assert data["settings"]["browser"] == "chrome"

    @pytest.mark.asyncio
    async def test_configure_unsupported_adapter_endpoint(self, client) -> None:
        resp = await client.post(
            "/api/capture/ambient/configure",
            json={"adapter_type": "nonexistent", "enabled": True},
        )
        assert resp.status_code in {422, 500}

    @pytest.mark.asyncio
    async def test_list_adapters_endpoint(self, client) -> None:
        # Configure one first
        await client.post(
            "/api/capture/ambient/configure",
            json={"adapter_type": "browser_history", "enabled": True},
        )
        resp = await client.get("/api/capture/ambient/adapters")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["adapters"]) >= 1

    @pytest.mark.asyncio
    async def test_disable_adapter_endpoint(self, client) -> None:
        """Configure then disable an adapter."""
        await client.post(
            "/api/capture/ambient/configure",
            json={"adapter_type": "browser_history", "enabled": True},
        )
        resp = await client.post(
            "/api/capture/ambient/configure",
            json={"adapter_type": "browser_history", "enabled": False},
        )
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

    @pytest.mark.asyncio
    async def test_ambient_endpoints_forbidden_in_hosted_mode(self, client) -> None:
        """Ambient capture endpoints return 403 when deployment_mode is 'hosted'."""
        with patch(
            "wikimind.api.routes.capture.get_settings",
        ) as mock_settings:
            mock_settings.return_value.deployment_mode = "hosted"

            resp = await client.post(
                "/api/capture/ambient/configure",
                json={"adapter_type": "browser_history", "enabled": True},
            )
            assert resp.status_code == 403

            resp = await client.get("/api/capture/ambient/adapters")
            assert resp.status_code == 403

            resp = await client.post(
                "/api/capture/ambient/adapters/browser_history/poll",
            )
            assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_configure_strips_history_db_path(self, client) -> None:
        """history_db_path in settings is stripped to prevent arbitrary file reads."""
        resp = await client.post(
            "/api/capture/ambient/configure",
            json={
                "adapter_type": "browser_history",
                "enabled": True,
                "settings": {
                    "browser": "chrome",
                    "history_db_path": "/etc/passwd",
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "history_db_path" not in data["settings"]
        assert data["settings"]["browser"] == "chrome"
