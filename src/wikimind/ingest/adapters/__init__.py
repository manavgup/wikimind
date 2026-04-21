"""Ingest adapters — re-exports for backward compatibility."""

from wikimind.ingest.adapters.pdf import (
    PDFAdapter,
    _convert_via_docling_serve,
    _extract_pdf_metadata,
    _first_markdown_heading,
    _parse_pdf_date,
)
from wikimind.ingest.adapters.text import TextAdapter
from wikimind.ingest.adapters.url import URLAdapter
from wikimind.ingest.adapters.youtube import YouTubeAdapter

__all__ = [
    "PDFAdapter",
    "TextAdapter",
    "URLAdapter",
    "YouTubeAdapter",
    "_convert_via_docling_serve",
    "_extract_pdf_metadata",
    "_first_markdown_heading",
    "_parse_pdf_date",
]
