"""Browser history ambient capture adapter (issue #442).

Reads Chrome or Firefox SQLite history databases and yields URLs that
match configurable patterns and haven't already been captured.

The adapter copies the browser history DB to a temp file before reading
because browsers hold an exclusive lock on the live database.
"""

from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from sqlmodel import select

from wikimind.config import get_settings
from wikimind.ingest.adapters.ambient import AdapterConfig, AmbientAdapter, CapturedItem
from wikimind.models import CaptureKind, CaptureSource

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

log = structlog.get_logger()

# Default Chrome history DB paths per platform
_CHROME_PATHS: dict[str, Path] = {
    "Darwin": Path.home() / "Library/Application Support/Google/Chrome/Default/History",
    "Linux": Path.home() / ".config/google-chrome/Default/History",
    "Windows": Path.home() / "AppData/Local/Google/Chrome/User Data/Default/History",
}

# Default Firefox history DB paths per platform
_FIREFOX_PATHS: dict[str, Path] = {
    "Darwin": Path.home() / "Library/Application Support/Firefox/Profiles",
    "Linux": Path.home() / ".mozilla/firefox",
    "Windows": Path.home() / "AppData/Roaming/Mozilla/Firefox/Profiles",
}


def _find_firefox_history_db() -> Path | None:
    """Find the Firefox places.sqlite in the default profile directory.

    Firefox stores history in ``places.sqlite`` inside a profile folder
    named ``<random>.default-release`` or similar. We find the first
    matching profile that contains the file.
    """
    system = platform.system()
    base = _FIREFOX_PATHS.get(system)
    if base is None or not base.exists():
        return None
    for profile_dir in base.iterdir():
        places = profile_dir / "places.sqlite"
        if places.exists():
            return places
    return None


def _resolve_history_db(config: AdapterConfig) -> Path | None:
    """Resolve the browser history SQLite database path.

    Uses only hardcoded platform-specific default paths for Chrome or
    Firefox. User-supplied paths are never accepted to prevent arbitrary
    local file reads.

    Args:
        config: Adapter configuration with ``browser`` setting.

    Returns:
        Path to the history database, or None if not found.
    """
    browser = config.settings.get("browser", "chrome")
    system = platform.system()

    if browser == "chrome":
        path = _CHROME_PATHS.get(system)
        if path and path.exists():
            return path
    elif browser == "firefox":
        return _find_firefox_history_db()

    return None


def _copy_db_to_temp(db_path: Path) -> Path:
    """Copy the browser history DB to a temp file for safe reading.

    Browsers hold exclusive locks on their SQLite databases, so we
    copy the file to a temporary location before opening it.

    Args:
        db_path: Path to the live browser history DB.

    Returns:
        Path to the temporary copy.
    """
    fd, tmp_name = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    tmp = Path(tmp_name)
    shutil.copy2(db_path, tmp)
    return tmp


def _read_chrome_history(
    db_path: Path,
    since_timestamp: int,
    max_entries: int,
) -> list[dict[str, str]]:
    """Read recent Chrome history entries from the SQLite database.

    Chrome stores visit timestamps as microseconds since 1601-01-01
    (Windows epoch). We convert our Unix timestamp to Chrome's format
    for the WHERE clause.

    Args:
        db_path: Path to the (copied) Chrome History SQLite file.
        since_timestamp: Unix timestamp — only entries after this time.
        max_entries: Maximum number of entries to return.

    Returns:
        List of dicts with ``url`` and ``title`` keys.
    """
    # Chrome epoch: 1601-01-01 00:00:00 UTC. Offset to Unix epoch in microseconds.
    chrome_epoch_offset = 11644473600 * 1_000_000
    chrome_since = since_timestamp * 1_000_000 + chrome_epoch_offset

    entries: list[dict[str, str]] = []
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cursor = conn.execute(
            """
            SELECT DISTINCT u.url, u.title
            FROM urls u
            JOIN visits v ON u.id = v.url
            WHERE v.visit_time > ?
            ORDER BY v.visit_time DESC
            LIMIT ?
            """,
            (chrome_since, max_entries),
        )
        entries.extend({"url": row[0], "title": row[1] or ""} for row in cursor)
        conn.close()
    except sqlite3.Error as e:
        log.warning("failed to read Chrome history", error=str(e))

    return entries


def _read_firefox_history(
    db_path: Path,
    since_timestamp: int,
    max_entries: int,
) -> list[dict[str, str]]:
    """Read recent Firefox history entries from the SQLite database.

    Firefox stores visit timestamps as microseconds since Unix epoch.

    Args:
        db_path: Path to the (copied) Firefox places.sqlite file.
        since_timestamp: Unix timestamp — only entries after this time.
        max_entries: Maximum number of entries to return.

    Returns:
        List of dicts with ``url`` and ``title`` keys.
    """
    firefox_since = since_timestamp * 1_000_000

    entries: list[dict[str, str]] = []
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cursor = conn.execute(
            """
            SELECT DISTINCT p.url, p.title
            FROM moz_places p
            JOIN moz_historyvisits v ON p.id = v.place_id
            WHERE v.visit_date > ?
            ORDER BY v.visit_date DESC
            LIMIT ?
            """,
            (firefox_since, max_entries),
        )
        entries.extend({"url": row[0], "title": row[1] or ""} for row in cursor)
        conn.close()
    except sqlite3.Error as e:
        log.warning("failed to read Firefox history", error=str(e))

    return entries


def _matches_patterns(url: str, patterns: list[str]) -> bool:
    """Check if a URL matches any of the configured filter patterns.

    An empty pattern list means "match everything". Patterns are
    compiled as regular expressions for flexibility.

    Args:
        url: The URL to check.
        patterns: List of regex patterns to match against.

    Returns:
        True if the URL matches any pattern or patterns is empty.
    """
    if not patterns:
        return True
    return any(re.search(p, url) for p in patterns)


class BrowserHistoryAdapter(AmbientAdapter):
    """Ambient adapter that reads browser history and yields new URLs.

    **Security**: This adapter reads the local filesystem and only makes
    sense in self-hosted mode. The ``history_db_path`` setting is never
    accepted from user input — only the hardcoded platform-default paths
    for Chrome/Firefox are used.

    Configuration settings (via ``AdapterConfig.settings``):
        - ``browser``: "chrome" or "firefox" (default: "chrome")
        - ``url_patterns``: Comma-separated regex patterns to filter URLs.
            Empty means capture all URLs.
        - ``exclude_patterns``: Comma-separated regex patterns to exclude.
            Applied after include patterns.
    """

    def __init__(self, config: AdapterConfig | None = None) -> None:
        if config is None:
            config = AdapterConfig(adapter_type="browser_history")
        super().__init__(config)

    async def poll(self, session: AsyncSession, user_id: str) -> list[CapturedItem]:
        """Read browser history and return new URLs not yet captured.

        Args:
            session: Async database session for dedup checks.
            user_id: The user to check captures for.

        Returns:
            List of CapturedItem for each new URL.
        """
        settings = get_settings()
        max_entries = settings.capture.browser_history_max_entries_per_poll

        db_path = _resolve_history_db(self.config)
        if db_path is None:
            log.info("browser history DB not found, skipping poll")
            self.mark_polled()
            return []

        # Copy to temp file to avoid locking issues
        tmp_path = _copy_db_to_temp(db_path)
        try:
            # Determine since-timestamp from last poll
            since_ts = 0
            if self.last_polled_at is not None:
                since_ts = int(self.last_polled_at.timestamp())

            browser = self.config.settings.get("browser", "chrome")
            if browser == "firefox":
                entries = _read_firefox_history(tmp_path, since_ts, max_entries)
            else:
                entries = _read_chrome_history(tmp_path, since_ts, max_entries)
        finally:
            tmp_path.unlink(missing_ok=True)

        if not entries:
            self.mark_polled()
            return []

        # Parse filter patterns
        include_raw = self.config.settings.get("url_patterns", "")
        include_patterns = [p.strip() for p in include_raw.split(",") if p.strip()]
        exclude_raw = self.config.settings.get("exclude_patterns", "")
        exclude_patterns = [p.strip() for p in exclude_raw.split(",") if p.strip()]

        items: list[CapturedItem] = []
        for entry in entries:
            url = entry["url"]
            title = entry.get("title", "")

            # Apply include/exclude filters
            if not _matches_patterns(url, include_patterns):
                continue
            if exclude_patterns and _matches_patterns(url, exclude_patterns):
                continue

            # Dedup: check if already captured
            content_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()
            existing = await session.execute(
                select(CaptureSource).where(
                    CaptureSource.user_id == user_id,
                    CaptureSource.content_hash == content_hash,
                )
            )
            if existing.scalars().first() is not None:
                continue

            items.append(
                CapturedItem(
                    kind=CaptureKind.BROWSER_HISTORY,
                    title=title or None,
                    content=url,
                    source_url=url,
                    external_id=url,
                )
            )

        self.mark_polled()

        log.info(
            "browser history polled",
            entries_scanned=len(entries),
            new_items=len(items),
            browser=self.config.settings.get("browser", "chrome"),
        )
        return items
