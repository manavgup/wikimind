"""Shared DTO types used across multiple DTO modules.

Types here have no imports from other DTO modules, breaking circular
dependency chains that CodeQL flags.
"""

from datetime import datetime

from pydantic import BaseModel


class TagResponse(BaseModel):
    """API response for a user tag."""

    id: str
    name: str
    color: str
    created_at: datetime
