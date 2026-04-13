#!/usr/bin/env python3
"""Backfill images for existing PDF sources.

Scans all PDF sources, extracts embedded images from the raw PDF files
(still on disk at ~/.wikimind/raw/{source_id}.pdf), and updates the
extracted text files with real image URLs.

Usage:
    python scripts/backfill_images.py          # process all PDFs
    python scripts/backfill_images.py --dry-run # show what would be done
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import structlog
from sqlmodel import select

from wikimind.config import get_settings
from wikimind.database import get_session_factory, init_db
from wikimind.ingest.service import PDFAdapter
from wikimind.models import Source

log = structlog.get_logger()


async def backfill(dry_run: bool = False) -> int:
    """Backfill images for all PDF sources that don't have them yet."""
    settings = get_settings()
    await init_db()
    session_factory = get_session_factory()

    images_base = Path(settings.data_dir) / "images"
    raw_dir = Path(settings.data_dir) / "raw"
    processed = 0
    skipped = 0
    errors = 0

    async with session_factory() as session:
        result = await session.execute(
            select(Source).where(Source.source_type == "pdf")  # type: ignore[attr-defined]
        )
        sources = list(result.scalars().all())

        log.info("Found PDF sources", count=len(sources))

        for source in sources:
            source_images_dir = images_base / source.id
            raw_pdf = raw_dir / f"{source.id}.pdf"
            text_file = Path(source.file_path) if source.file_path else None

            # Skip if images already extracted
            if source_images_dir.exists() and any(source_images_dir.iterdir()):
                log.info("Already has images, skipping", source_id=source.id, title=source.title)
                skipped += 1
                continue

            # Skip if raw PDF is missing
            if not raw_pdf.exists():
                log.warning("Raw PDF missing, skipping", source_id=source.id, title=source.title)
                skipped += 1
                continue

            if dry_run:
                log.info("Would process", source_id=source.id, title=source.title)
                processed += 1
                continue

            try:
                file_bytes = raw_pdf.read_bytes()
                images = PDFAdapter._extract_pdf_images(file_bytes, source.id, settings)

                if not images:
                    log.info("No qualifying images found", source_id=source.id, title=source.title)
                    skipped += 1
                    continue

                # Update the text file with image references
                if text_file and text_file.exists():
                    text = text_file.read_text(encoding="utf-8")
                    updated = PDFAdapter._insert_image_references(text, images, source.id, settings)
                    text_file.write_text(updated, encoding="utf-8")

                log.info(
                    "Backfilled images",
                    source_id=source.id,
                    title=source.title,
                    image_count=len(images),
                )
                processed += 1

            except Exception:
                log.error("Failed to process", source_id=source.id, title=source.title, exc_info=True)
                errors += 1

    log.info("Backfill complete", processed=processed, skipped=skipped, errors=errors)
    return 0 if errors == 0 else 1


def main() -> int:
    """Entry point for the backfill script."""
    parser = argparse.ArgumentParser(description="Backfill images for existing PDF sources")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
    args = parser.parse_args()

    return asyncio.run(backfill(dry_run=args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
