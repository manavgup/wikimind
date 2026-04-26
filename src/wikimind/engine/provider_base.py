"""Shared provider helpers that do not depend on the LLM router."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from wikimind.models import CompletionResponse, Provider

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


# Pricing (USD per 1M tokens) -- update as providers change pricing.
PRICING = {
    Provider.ANTHROPIC: {
        "claude-sonnet-4-5": {"input": 3.00, "output": 15.00},
        "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    },
    Provider.OPENAI: {
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    },
    Provider.OPENAI_COMPATIBLE: {
        "*": {"input": 0.0, "output": 0.0},
    },
    Provider.GOOGLE: {
        "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    },
    Provider.OLLAMA: {
        "*": {"input": 0.0, "output": 0.0},
    },
    Provider.MOCK: {
        "*": {"input": 0.0, "output": 0.0},
    },
}


def _calc_cost(provider: Provider, model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate the USD cost of an LLM call based on token counts."""
    provider_pricing = PRICING.get(provider, {})
    model_pricing = provider_pricing.get(model) or provider_pricing.get("*", {"input": 0, "output": 0})
    return (input_tokens * model_pricing["input"] + output_tokens * model_pricing["output"]) / 1_000_000


@dataclass
class StreamSession:
    """Wrap a streaming LLM response.

    Async-iterate for text chunks. After iteration completes, ``result`` is
    populated with token counts and cost information from the provider.
    """

    _chunks: AsyncIterator[str]
    result: CompletionResponse | None = field(default=None, init=True)

    def __aiter__(self) -> AsyncIterator[str]:  # noqa: D105
        return self._chunks
