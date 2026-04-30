"""Official OpenAI LLM provider."""

from __future__ import annotations

from wikimind.engine.providers.openai_compatible import OpenAICompatibleProvider
from wikimind.models import Provider


class OpenAIProvider(OpenAICompatibleProvider):
    """Official OpenAI provider using the default OpenAI API endpoint."""

    def __init__(self, api_key_override: str | None = None) -> None:
        super().__init__(
            provider=Provider.OPENAI,
            api_key_name="openai",
            api_key_override=api_key_override,
            base_url=None,
            supports_json_response_format=True,
            supports_stream_usage=True,
            supports_reasoning_effort=True,
            max_tokens_field="max_tokens",
            reasoning_format="openai",
        )
