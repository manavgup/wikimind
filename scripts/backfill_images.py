#!/usr/bin/env python3
"""Backfill images for existing PDF sources using Docling.

Scans all PDF sources, runs Docling with generate_picture_images=True,
and saves extracted PictureItem/TableItem images to disk.

Usage:
    python scripts/backfill_images.py          # process all PDFs
    python scripts/backfill_images.py --dry-run # show what would be done
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Any

import structlog
from sqlmodel import select

from wikimind.config import get_settings
from wikimind.database import get_session_factory, init_db
from wikimind.models import Source

log = structlog.get_logger()


def _get_converter() -> Any:
    """Create a singleton docling converter with picture extraction enabled."""
    global _converter
    if _converter is not None:
        return _converter

    try:
        from docling.datamodel.base_models import InputFormat  # noqa: PLC0415
        from docling.datamodel.pipeline_options import PdfPipelineOptions  # noqa: PLC0415
        from docling.document_converter import DocumentConverter, PdfFormatOption  # noqa: PLC0415
    except ImportError:
        log.error("Docling not installed. Install with: pip install 'wikimind[pdf]'")
        return None

    pipeline_options = PdfPipelineOptions()
    pipeline_options.images_scale = 2.0
    pipeline_options.generate_picture_images = True

    _converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)})
    return _converter


_converter: Any = None


def _extract_with_docling(raw_pdf_path: Path, source_id: str, images_dir: Path, max_images: int = 30) -> int:
    """Run Docling with picture extraction and save images to disk."""
    from docling_core.types.doc import PictureItem, TableItem  # noqa: PLC0415

    converter = _get_converter()
    if converter is None:
        return 0

    conv_res = converter.convert(str(raw_pdf_path))
    out_dir = images_dir / source_id
    out_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    pic_idx = 0
    tbl_idx = 0
    for element, _level in conv_res.document.iterate_items():
        if count >= max_images:
            break
        if isinstance(element, PictureItem):
            pic_idx += 1
            img = element.get_image(conv_res.document)
            if img:
                filename = f"test-picture-{pic_idx}.png"
                img.save(out_dir / filename, "PNG")
                count += 1
        elif isinstance(element, TableItem):
            tbl_idx += 1
            img = element.get_image(conv_res.document)
            if img:
                filename = f"test-table-{tbl_idx}.png"
                img.save(out_dir / filename, "PNG")
                count += 1

    return count


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

            if source_images_dir.exists() and any(source_images_dir.iterdir()):
                log.info("Already has images, skipping", source_id=source.id, title=source.title)
                skipped += 1
                continue

            if not raw_pdf.exists():
                log.warning("Raw PDF missing, skipping", source_id=source.id, title=source.title)
                skipped += 1
                continue

            if dry_run:
                log.info("Would process", source_id=source.id, title=source.title)
                processed += 1
                continue

            try:
                count = await asyncio.to_thread(
                    _extract_with_docling, raw_pdf, source.id, images_base, settings.image_max_per_pdf
                )
                log.info("Backfilled images", source_id=source.id, title=source.title, image_count=count)
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
