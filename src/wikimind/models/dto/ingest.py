"""Ingest and source DTOs — dependency-light request/response schemas.

These Pydantic models carry source/ingest data through the API layer and
the ingest pipeline without pulling in SQLModel or database dependencies.
"""

import uuid
from datetime import date, datetime

from pydantic import AnyHttpUrl, BaseModel, Field

from wikimind.models.enums import IngestStatus, PageType, SourceType

# ---------------------------------------------------------------------------
# Pipeline models (not persisted — used for ingest → compile pipeline)
# ---------------------------------------------------------------------------


class DocumentChunk(BaseModel):
    """A chunk of a normalized document."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    document_id: str
    content: str
    heading_path: list[str] = []  # e.g. ["Introduction", "Key Claims"]
    embedding_id: str | None = None
    token_count: int = 0
    chunk_index: int = 0


class NormalizedDocument(BaseModel):
    """Normalized document ready for compilation."""

    raw_source_id: str
    clean_text: str
    title: str
    author: str | None = None
    published_date: date | None = None
    estimated_tokens: int = 0
    language: str = "en"
    chunks: list[DocumentChunk] = []


# ---------------------------------------------------------------------------
# API request/response models
# ---------------------------------------------------------------------------


class IngestURLRequest(BaseModel):
    """Request to ingest a URL.

    Only ``http`` and ``https`` schemes are accepted (enforced by ``AnyHttpUrl``).
    """

    url: AnyHttpUrl
    auto_compile: bool = True


class IngestTextRequest(BaseModel):
    """Request to ingest raw text."""

    content: str = Field(max_length=500000)
    title: str | None = None
    auto_compile: bool = True


class SourceResponse(BaseModel):
    """Provenance view of a raw ingested source exposed via the API.

    Trimmed view of :class:`Source` suitable for embedding in article and
    Q&A responses so callers can trace claims back to their origin
    (URL, PDF filename, upload date, etc.).
    """

    id: str
    source_type: SourceType
    title: str | None
    source_url: str | None
    ingested_at: datetime


class PipelineStep(BaseModel):
    """A single step in the source processing pipeline."""

    name: str
    status: str  # "complete" | "active" | "pending" | "failed"
    description: str


class SourceImageEntry(BaseModel):
    """An extracted image entry for the source detail view."""

    filename: str
    kind: str  # "figure" | "table"
    label: str


class LinkedArticleSummary(BaseModel):
    """Minimal article info for the source detail view."""

    id: str
    slug: str
    title: str
    page_type: PageType = PageType.SOURCE


class SourceDetailResponse(BaseModel):
    """Full source detail with pipeline steps, images, and linked articles."""

    id: str
    source_type: SourceType
    source_url: str | None
    title: str | None
    author: str | None
    published_date: date | None
    status: IngestStatus
    ingested_at: datetime
    compiled_at: datetime | None
    token_count: int | None
    error_message: str | None
    has_original: bool
    pipeline_steps: list[PipelineStep]
    images: list[SourceImageEntry]
    linked_articles: list[LinkedArticleSummary]


class SourceContentResponse(BaseModel):
    """Raw text content of an ingested source for side-by-side reading."""

    content: str
    source_type: SourceType
    title: str | None
    truncated: bool = False


class ArticleSourceSummary(BaseModel):
    """Minimal source descriptor returned with listing/search endpoints.

    A lightweight summary used when the full :class:`SourceResponse` is
    overkill — e.g. article list and search result payloads.
    """

    id: str
    source_type: SourceType
    title: str | None
