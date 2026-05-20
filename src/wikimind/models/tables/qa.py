"""Q&A tables — conversations and query turns."""

import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from wikimind._datetime import utcnow_naive


class Conversation(SQLModel, table=True):
    """A conversation thread of one or more Q&A turns.

    Conversations group related Q&A turns that share LLM context. The
    first turn's question becomes the conversation's title (truncated).
    Filing a conversation back to the wiki is a per-conversation action,
    not per-turn — see ADR-011.

    Branching: when a user edits a prior turn, a new Conversation is
    created that shares turns 0..N-1 with the parent by reference.
    The original branch is preserved immutably.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    title: str
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)
    filed_article_id: str | None = Field(default=None, foreign_key="article.id")
    crystallized_article_id: str | None = Field(default=None, foreign_key="article.id")
    parent_conversation_id: str | None = Field(default=None, foreign_key="conversation.id", index=True)
    forked_at_turn_index: int | None = None


class Query(SQLModel, table=True):
    """Q&A history entry."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    question: str
    answer: str
    confidence: str | None = None
    source_article_ids: str | None = None  # JSON array
    related_article_ids: str | None = None  # JSON array
    filed_back: bool = False
    filed_article_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow_naive)
    # Conversation grouping (ADR-011). Nullable in the schema because the
    # repo's lightweight migration helper cannot add NOT NULL columns to
    # existing tables, but ALWAYS populated by app code — every Query
    # belongs to exactly one Conversation. Read it as "non-null in practice".
    conversation_id: str | None = Field(default=None, foreign_key="conversation.id", index=True)
    turn_index: int = 0  # 0 for first turn, 1 for second, etc.
