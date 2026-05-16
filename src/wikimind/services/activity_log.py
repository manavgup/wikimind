"""Append-only chronological activity log at ``{data_dir}/wiki/log.md``.

Implements Karpathy's LLM Wiki ``log.md`` primitive -- a flat, append-only
Markdown file that records ingest, compile, query, and file-back events.
The DB remains the source of truth; this file is a navigational aid.
"""

import os
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
    if user_id:
        # Sanitize: os.path.basename strips directory components (CodeQL sanitizer)
        safe_id = os.path.basename(user_id)
        if not safe_id or safe_id != user_id:
            msg = f"Path traversal blocked for user_id={user_id!r}"
            raise ValueError(msg)
    else:
        safe_id = ""

    # Build and verify path using os.path.realpath + startswith (CodeQL-safe pattern)
    base_real = os.path.realpath(str(base_dir))
    target = os.path.join(base_real, safe_id) if safe_id else base_real
    target_real = os.path.realpath(target)
    if not target_real.startswith(base_real):
        msg = f"Path traversal blocked for user_id={user_id!r}"
        raise ValueError(msg)

    resolved_dir = Path(target_real)
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
