"""Append-only chronological activity log at ``{data_dir}/wiki/log.md``.

Implements Karpathy's LLM Wiki ``log.md`` primitive -- a flat, append-only
Markdown file that records ingest, compile, query, and file-back events.
The DB remains the source of truth; this file is a navigational aid.
"""

from pathlib import Path

import structlog

from wikimind._datetime import utcnow_naive
from wikimind.config import get_settings

log = structlog.get_logger()

_LOG_HEADER = "# Activity Log\n\n"


def append_log_entry(
    op: str,
    title: str,
    user_id: str,
    extra: dict | None = None,
) -> None:
    """Append an entry to wiki/log.md.

    Line format::

        ## [YYYY-MM-DD] op | title

    With optional indented detail lines for extra context::

        - key: value

    Args:
        op: Short operation tag (e.g. ``ingest``, ``compile``, ``query``, ``filed``).
        title: Human-readable subject of the entry.
        extra: Optional dict of supplementary key/value pairs written as
            indented detail lines beneath the heading.
        user_id: Optional user ID for path scoping.
    """
    base_dir = Path(get_settings().data_dir) / "wiki"
    wiki_dir = base_dir
    if user_id:
        # Sanitize: use only the basename to prevent path traversal.
        safe_id = Path(user_id).name
        wiki_dir = base_dir / safe_id

    # Defense-in-depth: resolve and verify the path stays under base_dir.
    resolved_dir = wiki_dir.resolve()
    if not resolved_dir.is_relative_to(base_dir.resolve()):
        msg = f"Path traversal blocked for user_id={user_id!r}"
        raise ValueError(msg)

    resolved_dir.mkdir(parents=True, exist_ok=True)
    log_path = resolved_dir / "log.md"

    datestamp = utcnow_naive().strftime("%Y-%m-%d")
    lines = [f"## [{datestamp}] {op} | {title}\n"]
    if extra:
        for key, value in extra.items():
            lines.append(f"- {key}: {value}\n")
    lines.append("\n")

    # Open in append mode and write the header atomically if the file is
    # new.  Using fh.tell() == 0 inside the same open avoids the TOCTOU
    # race between exists() and write_text() that could truncate a
    # concurrent writer's header.
    with log_path.open("a", encoding="utf-8") as fh:
        if fh.tell() == 0:
            fh.write(_LOG_HEADER)
        fh.writelines(lines)
