"""Ingest adapters — re-exports for backward compatibility."""

from wikimind.ingest.adapters.pdf import (
    _DOCLING_AVAILABLE,
    PDFAdapter,
    _docling_converter,
    _DocumentConverter,
    _extract_pdf_metadata,
    _first_markdown_heading,
    _get_docling_converter,
    _parse_pdf_date,
)
from wikimind.ingest.adapters.text import TextAdapter
from wikimind.ingest.adapters.url import URLAdapter
from wikimind.ingest.adapters.youtube import YouTubeAdapter

__all__ = [
    "_DOCLING_AVAILABLE",
    "PDFAdapter",
    "TextAdapter",
    "URLAdapter",
    "YouTubeAdapter",
    "_DocumentConverter",
    "_docling_converter",
    "_extract_pdf_metadata",
    "_first_markdown_heading",
    "_get_docling_converter",
    "_parse_pdf_date",
]
