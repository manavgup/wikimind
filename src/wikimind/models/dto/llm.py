"""LLM DTOs — dependency-light request/response schemas.

Covers LLM completion requests/responses, provider status, and traces.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from wikimind.models.enums import Provider, TaskType


class CompletionRequest(BaseModel):
    """Request for LLM completion."""

    system: str
    messages: list[dict[str, str]]
    max_tokens: int = 4096
    temperature: float = 0.3
    response_format: str = "json"  # text | json
    task_type: TaskType = TaskType.COMPILE
    preferred_provider: Provider | None = None
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "xhigh"] | None = None
    model_override: str | None = None
    disable_fallback: bool = False


class CompletionResponse(BaseModel):
    """Response from LLM completion."""

    content: str
    provider_used: Provider
    model_used: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int


class LLMProviderStatus(BaseModel):
    """Status of an LLM provider."""

    provider: Provider
    enabled: bool
    configured: bool  # API key present
    model: str
    cost_this_month_usd: float


class LLMTraceResponse(BaseModel):
    """API response for a single LLM trace entry."""

    id: str
    user_id: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: float
    created_at: datetime
    prompt_text: str | None = None
    completion_text: str | None = None
    source_id: str | None = None
    operation: str


class LLMTraceListResponse(BaseModel):
    """Paginated list of LLM traces."""

    items: list[LLMTraceResponse]
    total: int
