"""Job and observability tables — async jobs, cost logs, LLM traces, sync logs."""

import uuid
from datetime import datetime

from sqlalchemy import Text
from sqlmodel import Field, SQLModel

from wikimind._datetime import utcnow_naive
from wikimind.models.enums import JobStatus, JobType, Provider, TaskType


class Job(SQLModel, table=True):
    """Async job record."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    job_type: JobType
    status: JobStatus = JobStatus.QUEUED
    source_id: str | None = None
    article_id: str | None = None
    priority: int = 5
    queued_at: datetime = Field(default_factory=utcnow_naive)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    result_summary: str | None = None


class CostLog(SQLModel, table=True):
    """LLM API cost tracking."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    provider: Provider
    model: str
    task_type: TaskType
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    job_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow_naive)


class LLMTrace(SQLModel, table=True):
    """Opt-in LLM call trace for debugging and cost monitoring.

    Always stores lightweight metrics (tokens, latency, model, operation).
    Prompt/completion text is only stored when ``trace_store_content`` is enabled.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: float
    created_at: datetime = Field(default_factory=utcnow_naive, index=True)
    prompt_text: str | None = Field(default=None, sa_type=Text)
    completion_text: str | None = Field(default=None, sa_type=Text)
    source_id: str | None = None
    operation: str  # "compile", "query", "synthesis", etc.


class SyncLog(SQLModel, table=True):
    """Cloud sync history."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    direction: str  # push | pull
    articles_pushed: int = 0
    articles_pulled: int = 0
    conflicts: int = 0
    started_at: datetime = Field(default_factory=utcnow_naive)
    completed_at: datetime | None = None
    error: str | None = None
