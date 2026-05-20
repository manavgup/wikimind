"""Consolidated service factory functions for FastAPI dependency injection.

All get_*_service() factories live here so route handlers have a single
import location. Each factory returns a ready-to-use service instance.
"""

from __future__ import annotations

import functools

import structlog

from wikimind.services.admin import AdminService
from wikimind.services.capture import CaptureService
from wikimind.services.citation import CitationService
from wikimind.services.compilation_schema import CompilationSchemaService
from wikimind.services.compiler import CompilerService
from wikimind.services.contradiction import ContradictionService
from wikimind.services.draft import DraftService
from wikimind.services.embedding import EmbeddingService
from wikimind.services.export import ExportService
from wikimind.services.ingest import IngestService
from wikimind.services.linter import LinterService
from wikimind.services.query import QueryService
from wikimind.services.rss import RssService
from wikimind.services.saved_searches import SavedSearchService
from wikimind.services.search import SearchService
from wikimind.services.sharing import SharingService
from wikimind.services.tags import TagService
from wikimind.services.user import UserService
from wikimind.services.wiki import WikiService
from wikimind.services.wiki_export import WikiExportService

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Singleton cache for AdminService (manual pattern preserved from original)
# ---------------------------------------------------------------------------

_admin_service: AdminService | None = None


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------


def get_admin_service() -> AdminService:
    """Return a singleton AdminService instance for FastAPI DI."""
    global _admin_service
    if _admin_service is None:
        _admin_service = AdminService()
    return _admin_service


@functools.lru_cache(maxsize=1)
def get_capture_service() -> CaptureService:
    """Return a singleton CaptureService instance for FastAPI dependency injection."""
    return CaptureService()


@functools.lru_cache(maxsize=1)
def get_citation_service() -> CitationService:
    """Return a singleton CitationService instance for FastAPI dependency injection."""
    return CitationService()


@functools.lru_cache(maxsize=1)
def get_compilation_schema_service() -> CompilationSchemaService:
    """Return a singleton CompilationSchemaService for FastAPI dependency injection."""
    return CompilationSchemaService()


@functools.lru_cache(maxsize=1)
def get_compiler_service() -> CompilerService:
    """Return a singleton CompilerService instance for FastAPI dependency injection."""
    return CompilerService()


@functools.lru_cache(maxsize=1)
def get_contradiction_service() -> ContradictionService:
    """Return a singleton ContradictionService instance."""
    return ContradictionService()


@functools.lru_cache(maxsize=1)
def get_draft_service() -> DraftService:
    """Return a singleton DraftService instance for FastAPI DI."""
    return DraftService()


@functools.lru_cache(maxsize=1)
def get_embedding_service() -> EmbeddingService | None:
    """Return a singleton EmbeddingService, or None if search extras are missing."""
    from wikimind.services.embedding import (  # noqa: PLC0415
        _SEARCH_AVAILABLE,
    )

    if not _SEARCH_AVAILABLE:
        return None
    try:
        return EmbeddingService()
    except (OSError, RuntimeError, ValueError):
        log.warning("Failed to initialize EmbeddingService")
        return None


@functools.lru_cache(maxsize=1)
def get_export_service() -> ExportService:
    """Return the singleton export service."""
    return ExportService()


@functools.lru_cache(maxsize=1)
def get_ingest_service() -> IngestService:
    """Return a singleton IngestService instance for FastAPI dependency injection."""
    return IngestService()


@functools.lru_cache(maxsize=1)
def get_linter_service() -> LinterService:
    """Return a singleton LinterService instance."""
    return LinterService()


@functools.lru_cache(maxsize=1)
def get_query_service() -> QueryService:
    """Return a singleton QueryService instance for FastAPI dependency injection."""
    return QueryService()


@functools.lru_cache(maxsize=1)
def get_rss_service() -> RssService:
    """Return a singleton RssService instance for FastAPI dependency injection."""
    return RssService()


@functools.lru_cache(maxsize=1)
def get_saved_search_service() -> SavedSearchService:
    """Return a singleton SavedSearchService for FastAPI dependency injection."""
    return SavedSearchService()


@functools.lru_cache(maxsize=1)
def get_search_service() -> SearchService:
    """Return a singleton SearchService for FastAPI dependency injection."""
    return SearchService()


@functools.lru_cache(maxsize=1)
def get_sharing_service() -> SharingService:
    """Return the singleton sharing service."""
    return SharingService()


@functools.lru_cache(maxsize=1)
def get_tag_service() -> TagService:
    """Return a singleton TagService instance for FastAPI dependency injection."""
    return TagService()


@functools.lru_cache(maxsize=1)
def get_user_service() -> UserService:
    """Return a singleton UserService instance for FastAPI dependency injection."""
    return UserService()


@functools.lru_cache(maxsize=1)
def get_wiki_service() -> WikiService:
    """Return a singleton WikiService instance for FastAPI dependency injection."""
    return WikiService()


@functools.lru_cache(maxsize=1)
def get_wiki_export_service() -> WikiExportService:
    """Return the singleton wiki export service."""
    return WikiExportService()
