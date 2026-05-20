"""Core tables — migration history and user accounts."""

import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from wikimind._datetime import utcnow_naive


class MigrationHistory(SQLModel, table=True):
    """Tracks which data migrations have been applied.

    Each row records a unique migration version string and when it ran.
    init_db() checks this table to skip already-applied migrations,
    turning O(n) startup scans into a constant-time version check.
    """

    version: str = Field(primary_key=True)
    applied_at: datetime = Field(default_factory=utcnow_naive)


class User(SQLModel, table=True):
    """Authenticated user account."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    email: str = Field(index=True, unique=True)
    name: str | None = None
    avatar_url: str | None = None
    auth_provider: str  # "google" | "github"
    auth_provider_id: str  # provider's unique user ID
    is_admin: bool = Field(default=False)
    plan_id: str | None = None
    plan_effective_until: datetime | None = None
    lemon_squeezy_customer_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)
