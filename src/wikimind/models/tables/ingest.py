"""Ingest tables — raw sources and extracted images."""

import uuid
from datetime import date, datetime

from pydantic import computed_field
from sqlalchemy import Column, ForeignKey, LargeBinary, String, Text
from sqlmodel import Field, SQLModel

from wikimind._datetime import utcnow_naive
from wikimind.models.enums import IngestStatus, SourceType
from wikimind.storage import find_original_sibling, get_raw_storage


class Source(SQLModel, table=True):
    """Raw ingested source — before compilation."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    source_type: SourceType
    source_url: str | None = None
    title: str | None = None
    author: str | None = None
    published_date: date | None = None
    status: IngestStatus = IngestStatus.PENDING
    ingested_at: datetime = Field(default_factory=utcnow_naive)
    compiled_at: datetime | None = None
    token_count: int | None = None
    error_message: str | None = None
    file_path: str | None = None  # Path in raw/ directory
    clean_text: str | None = Field(
        default=None,
        sa_type=Text,
        exclude=True,
    )  # DB-backed source content; excluded from API responses
    # SHA-256 hex digest of the raw payload (issue #67). Used by the ingest
    # layer to detect duplicates: re-ingesting the same content returns the
    # existing source instead of creating a second row.
    content_hash: str | None = Field(default=None, index=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_original(self) -> bool:
        """Whether the original document (PDF, HTML) exists alongside the .txt."""
        if not self.file_path:
            return False
        raw_storage = get_raw_storage(self.user_id)
        try:
            txt_path = raw_storage.resolve_path(self.file_path)
        except ValueError:
            return False
        return find_original_sibling(txt_path) is not None


class SourceImage(SQLModel, table=True):
    """Image extracted from a PDF source, stored in Postgres.

    Replaces filesystem storage so web and worker machines can both
    access extracted images without shared volumes (issue #638).
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    source_id: str = Field(
        sa_column=Column(String, ForeignKey("source.id", ondelete="CASCADE"), index=True),
    )
    user_id: str = Field(foreign_key="user.id", index=True)
    filename: str  # e.g. "picture-1.png", "table-2.png"
    kind: str  # "figure" or "table"
    image_data: bytes = Field(sa_type=LargeBinary, exclude=True)
    created_at: datetime = Field(default_factory=utcnow_naive)
