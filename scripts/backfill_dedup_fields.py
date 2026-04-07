#!/usr/bin/env python3
"""One-time backfill for `Source.content_hash` (issue #67).

Existing databases predate the dedup column. The runtime migration in
`wikimind.database.init_db` adds the column itself, but every existing
row still has `content_hash IS NULL`, which means the very first re-ingest
of any pre-existing source would create a duplicate row.

This script walks every Source whose `content_hash` is null, reads the
appropriate raw file from disk based on `source_type`, computes the
SHA-256, and writes it back. It is idempotent and safe to re-run; sources
whose raw file is missing are logged and skipped (their next re-ingest
will populate the hash naturally).

Usage::

    python scripts/backfill_dedup_fields.py            # apply
    python scripts/backfill_dedup_fields.py --dry-run  # report only
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
from pathlib import Path

from sqlmodel import select

from wikimind.config import get_settings
from wikimind.database import close_db, get_session_factory, init_db
from wikimind.models import Source, SourceType


def _raw_file_for(source: Source) -> Path | None:
    """Return the path to the raw payload file for a Source, or None.

    Each adapter writes a different raw file under `~/.wikimind/raw/`:
    URL → `.html`, PDF → `.pdf`, Text/YouTube → `.txt`. We hash the
    raw file (not the cleaned text) so the value matches what
    `compute_hash` produces during a fresh ingest.
    """
    settings = get_settings()
    raw_dir = Path(settings.data_dir) / "raw"
    if source.source_type == SourceType.URL:
        return raw_dir / f"{source.id}.html"
    if source.source_type == SourceType.PDF:
        return raw_dir / f"{source.id}.pdf"
    # Text and YouTube store the raw payload as the same .txt the worker reads.
    if source.file_path:
        return Path(source.file_path)
    return None


async def backfill(dry_run: bool) -> int:
    """Run the backfill, returning the number of rows updated."""
    await init_db()
    factory = get_session_factory()

    updated = 0
    skipped: list[str] = []
    async with factory() as session:
        result = await session.execute(select(Source).where(Source.content_hash.is_(None)))  # type: ignore[union-attr]
        rows = result.scalars().all()
        print(f"Found {len(rows)} sources with NULL content_hash")
        for source in rows:
            raw_file = _raw_file_for(source)
            if raw_file is None or not raw_file.exists():
                skipped.append(f"{source.id} ({source.source_type}): raw file missing")
                continue
            digest = hashlib.sha256(raw_file.read_bytes()).hexdigest()
            print(f"  {source.id} ({source.source_type}): {digest[:16]}...")
            if not dry_run:
                source.content_hash = digest
                session.add(source)
                updated += 1
        if not dry_run:
            await session.commit()

    if skipped:
        print(f"\nSkipped {len(skipped)} sources (raw file missing):")
        for line in skipped:
            print(f"  {line}")
    print(f"\n{'Would update' if dry_run else 'Updated'} {updated} rows")
    await close_db()
    return updated


def main() -> int:
    """Parse CLI args and run the backfill."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Report what would change without writing")
    args = parser.parse_args()
    asyncio.run(backfill(dry_run=args.dry_run))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
