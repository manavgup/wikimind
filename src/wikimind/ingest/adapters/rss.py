"""RSS/Atom feed adapter for ambient capture (issue #442).

Polls subscribed feeds, creates CaptureSource rows for new entries,
and deduplicates by entry guid or link.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import defusedxml.ElementTree as DefusedET
import httpx
import structlog

from wikimind._datetime import utcnow_naive
from wikimind.config import get_settings
from wikimind.models import (
    CaptureKind,
    CaptureSource,
    CaptureStatus,
    RssFeed,
)

if TYPE_CHECKING:
    from xml.etree.ElementTree import Element

    from sqlmodel.ext.asyncio.session import AsyncSession

log = structlog.get_logger()

# Namespace prefixes used in Atom feeds
_ATOM_NS = "{http://www.w3.org/2005/Atom}"


def _parse_feed_entries(xml_text: str) -> list[dict[str, str]]:
    """Parse RSS 2.0 or Atom feed XML into a list of entry dicts.

    Each dict contains keys: guid, title, link, summary.
    Returns entries in document order (newest first for well-formed feeds).
    """
    from xml.etree.ElementTree import ParseError  # noqa: PLC0415

    try:
        root = DefusedET.fromstring(xml_text)
    except ParseError:
        log.warning("failed to parse feed XML")
        return []

    entries: list[dict[str, str]] = []

    # RSS 2.0: <rss><channel><item>...</item></channel></rss>
    for item in root.iter("item"):
        entry = _parse_rss_item(item)
        if entry:
            entries.append(entry)

    # Atom: <feed><entry>...</entry></feed>
    if not entries:
        for atom_entry in root.iter(f"{_ATOM_NS}entry"):
            entry = _parse_atom_entry(atom_entry)
            if entry:
                entries.append(entry)

    return entries


def _text(elem: Element | None) -> str:
    """Safely extract text content from an XML element."""
    if elem is None:
        return ""
    return (elem.text or "").strip()


def _parse_rss_item(item: Element) -> dict[str, str] | None:
    """Parse an RSS 2.0 <item> element."""
    guid = _text(item.find("guid"))
    link = _text(item.find("link"))
    title = _text(item.find("title"))
    description = _text(item.find("description"))

    if not guid and not link:
        return None

    return {
        "guid": guid or link,
        "title": title,
        "link": link,
        "summary": description,
    }


def _parse_atom_entry(entry: Element) -> dict[str, str] | None:
    """Parse an Atom <entry> element."""
    entry_id = _text(entry.find(f"{_ATOM_NS}id"))
    title = _text(entry.find(f"{_ATOM_NS}title"))

    link_elem = entry.find(f"{_ATOM_NS}link")
    link = ""
    if link_elem is not None:
        link = link_elem.get("href", "")

    summary_elem = entry.find(f"{_ATOM_NS}summary")
    content_elem = entry.find(f"{_ATOM_NS}content")
    summary = _text(summary_elem) or _text(content_elem)

    if not entry_id and not link:
        return None

    return {
        "guid": entry_id or link,
        "title": title,
        "link": link,
        "summary": summary,
    }


class RssAdapter:
    """Adapter for polling RSS/Atom feeds and creating captures."""

    async def poll_feed(
        self,
        feed: RssFeed,
        session: AsyncSession,
    ) -> int:
        """Poll a single feed and create CaptureSource rows for new entries.

        Args:
            feed: The RssFeed subscription to poll.
            session: Async database session.

        Returns:
            Number of new captures created.
        """
        settings = get_settings()
        timeout = settings.capture.rss_http_timeout_seconds
        max_entries = settings.capture.rss_max_entries_per_poll

        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
                response = await client.get(
                    feed.feed_url,
                    headers={"User-Agent": "WikiMind/0.1 (rss-adapter)"},
                )
                response.raise_for_status()
                xml_text = response.text
        except (httpx.HTTPError, OSError) as e:
            log.warning(
                "RSS fetch failed",
                feed_id=feed.id,
                feed_url=feed.feed_url,
                error=str(e),
            )
            feed.error_message = str(e)
            feed.last_polled_at = utcnow_naive()
            session.add(feed)
            await session.commit()
            return 0

        entries = _parse_feed_entries(xml_text)
        if not entries:
            feed.last_polled_at = utcnow_naive()
            feed.error_message = None
            session.add(feed)
            await session.commit()
            return 0

        new_count = 0
        for entry in entries[:max_entries]:
            guid = entry.get("guid", "")
            if not guid:
                continue

            content_hash = hashlib.sha256(guid.encode("utf-8")).hexdigest()

            # Dedup: skip if we already captured this guid for this user
            from sqlmodel import select  # noqa: PLC0415

            existing = await session.execute(
                select(CaptureSource).where(
                    CaptureSource.user_id == feed.user_id,
                    CaptureSource.content_hash == content_hash,
                )
            )
            if existing.scalars().first() is not None:
                continue

            # Build capture content from entry summary/title
            content = entry.get("summary", "") or entry.get("title", "")
            if not content:
                continue

            capture = CaptureSource(
                user_id=feed.user_id,
                kind=CaptureKind.RSS,
                title=entry.get("title", ""),
                raw_payload=content,
                content_hash=content_hash,
                source_url=entry.get("link", ""),
                external_id=guid,
                status=CaptureStatus.CAPTURED,
            )
            session.add(capture)
            new_count += 1

        feed.last_polled_at = utcnow_naive()
        feed.error_message = None
        if entries:
            feed.last_entry_id = entries[0].get("guid", "")
        session.add(feed)
        await session.commit()

        log.info(
            "RSS feed polled",
            feed_id=feed.id,
            feed_url=feed.feed_url,
            entries_found=len(entries),
            new_captures=new_count,
        )
        return new_count
