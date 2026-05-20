"""Discussion (HITL) request/response DTOs (issue #418)."""

from datetime import datetime

from pydantic import BaseModel, Field


class DiscussionMessageRequest(BaseModel):
    """Request to post a message in an article's discussion thread."""

    message: str = Field(min_length=1, max_length=10000)


class DiscussionMessageResponse(BaseModel):
    """API response for a single discussion message."""

    id: str
    article_id: str
    role: str
    content: str
    created_at: datetime


class DiscussionThreadResponse(BaseModel):
    """Full discussion thread for an article."""

    article_id: str
    messages: list[DiscussionMessageResponse]


class CompileWithGuidanceResponse(BaseModel):
    """Response after triggering recompilation with discussion guidance."""

    status: str
    job_id: str
