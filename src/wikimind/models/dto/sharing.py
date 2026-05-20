"""Share link and export DTOs — dependency-light request/response schemas."""

from datetime import datetime

from pydantic import BaseModel, Field

from wikimind.models.dto.ingest import SourceResponse
from wikimind.models.enums import ExportFormat, WikiExportFormat


class CreateShareLinkRequest(BaseModel):
    """Request to create a share link for an article."""

    article_id: str
    expires_in_days: int | None = Field(default=None, ge=1, le=365)


class ShareLinkResponse(BaseModel):
    """API response for a share link."""

    id: str
    article_id: str
    token: str
    created_at: datetime
    expires_at: datetime | None
    revoked: bool
    view_count: int
    last_viewed_at: datetime | None
    article_title: str | None = None


class PublicArticleResponse(BaseModel):
    """Read-only public article content for share links."""

    title: str
    content_html: str
    summary: str | None
    sources: list[SourceResponse] = []
    created_at: datetime
    updated_at: datetime


class ExportResponse(BaseModel):
    """Response for text-based exports (LinkedIn, slides)."""

    format: ExportFormat
    content: str
    article_id: str
    article_title: str


class WikiExportResponse(BaseModel):
    """Response metadata for wiki export (actual file is streamed)."""

    format: WikiExportFormat
    article_count: int
    filename: str
