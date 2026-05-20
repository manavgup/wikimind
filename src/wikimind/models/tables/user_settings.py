"""User settings tables — API keys, preferences, compilation schemas."""

import uuid
from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from wikimind._datetime import utcnow_naive
from wikimind.models.enums import Provider


class UserApiKey(SQLModel, table=True):
    """Encrypted user-provided API key for an LLM provider (BYOK).

    Each row stores a Fernet-encrypted API key with a per-row salt.
    The encryption key is derived from ``JWT_SECRET_KEY + salt`` via
    PBKDF2-HMAC-SHA256.  See ADR-026.
    """

    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_userapikey_user_provider"),)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    provider: Provider
    encrypted_key: str  # Fernet-encrypted API key (base64)
    salt: str  # Per-row salt (hex-encoded)
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)


class UserPreference(SQLModel, table=True):
    """Lightweight key-value store for runtime settings overrides.

    Precedence: DB row wins if it exists, otherwise falls back to .env defaults.
    """

    key: str = Field(primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    value: str
    updated_at: datetime = Field(default_factory=utcnow_naive)


class CompilationSchema(SQLModel, table=True):
    """User-defined compilation rules that guide how sources become wiki articles.

    Each schema contains structured directives (article structure, style,
    extraction rules, concept taxonomy preferences) that are injected into
    the compiler's LLM prompt at compilation time. Only one schema per user
    can be active at a time (issue #420).
    """

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_compilationschema_user_name"),)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    name: str
    description: str | None = None
    is_active: bool = False
    # Structured rule fields (JSON strings for flexibility)
    article_max_length: int | None = None
    required_sections: str | None = None  # JSON array: ["summary", "key_claims"]
    style: str | None = None  # Freeform style directive
    focus: str | None = None  # What to emphasize
    concept_max_depth: int | None = None
    concept_naming: str | None = None  # e.g. "lowercase, hyphenated"
    extraction_always_note: str | None = None  # JSON array: ["methodology"]
    extraction_ignore: str | None = None  # JSON array: ["author bios"]
    custom_directives: str | None = None  # Freeform additional directives
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)
