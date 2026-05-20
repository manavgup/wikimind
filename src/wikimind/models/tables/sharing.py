"""Sharing tables — share links and saved searches."""

import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from wikimind._datetime import utcnow_naive


class ShareLink(SQLModel, table=True):
    """A signed, revocable read-only share link for a single article.

    Each share link has a cryptographically random token used in the public
    URL. Links can be revoked or set to expire. View counts are tracked
    for analytics.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    article_id: str = Field(foreign_key="article.id", index=True)
    token: str = Field(index=True, unique=True)
    created_at: datetime = Field(default_factory=utcnow_naive)
    expires_at: datetime | None = None
    revoked: bool = False
    view_count: int = 0
    last_viewed_at: datetime | None = None


class SavedSearch(SQLModel, table=True):
    """User-saved search with optional tag and concept filters.

    Stores a search query string plus a JSON blob of filters so users can
    one-click re-execute common searches like "Q2 Research" or "read-later
    items about prompt caching".
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    name: str
    query: str
    filters_json: str = "{}"  # JSON: {"tags": ["read-later"], "concepts": [...]}
    created_at: datetime = Field(default_factory=utcnow_naive)
