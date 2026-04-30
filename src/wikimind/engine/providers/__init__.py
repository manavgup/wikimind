"""LLM provider implementations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from wikimind.engine.provider_base import StreamSession
    from wikimind.models import CompletionRequest, CompletionResponse

from wikimind.engine.providers.anthropic import AnthropicProvider
from wikimind.engine.providers.google import GoogleProvider
from wikimind.engine.providers.mock import (
    _MOCK_COMPILE_RESPONSE,
    _MOCK_LINT_RESPONSE,
    _MOCK_QA_RESPONSE,
    MockProvider,
)
from wikimind.engine.providers.ollama import OllamaProvider
from wikimind.engine.providers.openai import OpenAIProvider
from wikimind.engine.providers.openai_compatible import (
    ConfiguredOpenAICompatibleProvider,
    OpenAICompatibleProvider,
)


@runtime_checkable
class ProviderProtocol(Protocol):
    """Structural interface that all LLM providers must satisfy.

    Providers are not required to inherit from this class; they only need
    to implement the three methods with compatible signatures. The
    ``@runtime_checkable`` decorator allows ``isinstance()`` checks at
    runtime (useful for tests and assertions).
    """

    async def complete(self, request: CompletionRequest, model: str) -> CompletionResponse:
        """Execute a single-turn LLM completion."""
        ...

    async def complete_multimodal(
        self,
        system: str,
        content_parts: list[dict[str, Any]],
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> CompletionResponse:
        """Execute a multimodal completion with text and images."""
        ...

    async def stream(self, request: CompletionRequest, model: str) -> StreamSession:
        """Create a streaming completion and return a StreamSession."""
        ...


__all__ = [
    "_MOCK_COMPILE_RESPONSE",
    "_MOCK_LINT_RESPONSE",
    "_MOCK_QA_RESPONSE",
    "AnthropicProvider",
    "ConfiguredOpenAICompatibleProvider",
    "GoogleProvider",
    "MockProvider",
    "OllamaProvider",
    "OpenAICompatibleProvider",
    "OpenAIProvider",
    "ProviderProtocol",
]
