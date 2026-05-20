"""Tag tables — user-created tags and article-tag join table."""

import uuid
from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from wikimind._datetime import utcnow_naive


class Tag(SQLModel, table=True):
    """User-created organizational tag (separate from LLM-derived concepts).

    Tags like ``read-later``, ``favorite``, ``to-revisit`` give users their own
    retrieval layer. Each tag has a display color for pill-badge rendering.
    """

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_tag_user_name"),)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    name: str
    color: str = "#6366f1"  # Default indigo
    created_at: datetime = Field(default_factory=utcnow_naive)


class ArticleTag(SQLModel, table=True):
    """Join table linking articles to user-created tags."""

    __table_args__ = (UniqueConstraint("article_id", "tag_id", name="uq_articletag_article_tag"),)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    article_id: str = Field(foreign_key="article.id", index=True)
    tag_id: str = Field(foreign_key="tag.id", index=True)
    created_at: datetime = Field(default_factory=utcnow_naive)
