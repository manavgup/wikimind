"""OpenAI-compatible Chat Completions provider helpers."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Literal, cast

import openai

from wikimind.config import get_api_key, get_runtime_config, get_settings
from wikimind.engine.provider_base import StreamSession, _calc_cost
from wikimind.models import CompletionRequest, CompletionResponse, Provider

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

MaxTokensField = Literal["max_tokens", "max_completion_tokens"]
ReasoningFormat = Literal["none", "openai", "openrouter"]


class OpenAICompatibleProvider:
    """Provider for OpenAI Chat Completions-compatible endpoints."""

    def __init__(
        self,
        *,
        provider: Provider = Provider.OPENAI_COMPATIBLE,
        api_key_name: str = "openai_compatible",
        api_key_override: str | None = None,
        base_url: str | None = None,
        default_headers: dict[str, str] | None = None,
        supports_json_response_format: bool = True,
        supports_stream_usage: bool = True,
        supports_reasoning_effort: bool = True,
        max_tokens_field: MaxTokensField = "max_tokens",
        reasoning_format: ReasoningFormat = "openai",
    ) -> None:
        api_key = api_key_override or get_api_key(api_key_name)
        if not api_key:
            msg = f"{provider.value} API key not configured"
            raise ValueError(msg)
        if provider == Provider.OPENAI_COMPATIBLE and not base_url:
            msg = "OpenAI-compatible base URL not configured"
            raise ValueError(msg)
        if max_tokens_field not in {"max_tokens", "max_completion_tokens"}:
            msg = "max_tokens_field must be 'max_tokens' or 'max_completion_tokens'"
            raise ValueError(msg)
        if reasoning_format not in {"none", "openai", "openrouter"}:
            msg = "reasoning_format must be 'none', 'openai', or 'openrouter'"
            raise ValueError(msg)

        self.provider = provider
        self.supports_json_response_format = supports_json_response_format
        self.supports_stream_usage = supports_stream_usage
        self.supports_reasoning_effort = supports_reasoning_effort
        self.max_tokens_field: MaxTokensField = max_tokens_field
        self.reasoning_format: ReasoningFormat = reasoning_format
        self.client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers=default_headers or None,
        )

    async def complete(self, request: CompletionRequest, model: str) -> CompletionResponse:
        """Complete a request using an OpenAI-compatible endpoint."""
        start = time.monotonic()

        messages = [{"role": "system", "content": request.system}]
        messages.extend(request.messages)

        kwargs: dict[str, object] = {
            "model": model,
            self.max_tokens_field: request.max_tokens,
            "temperature": request.temperature,
            "messages": messages,
        }
        if request.response_format == "json" and self.supports_json_response_format:
            kwargs["response_format"] = {"type": "json_object"}
        self._add_reasoning_kwargs(kwargs, request)

        response = await self.client.chat.completions.create(**kwargs)  # type: ignore[call-overload]

        latency_ms = int((time.monotonic() - start) * 1000)
        content = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
        output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0

        return CompletionResponse(
            content=content,
            provider_used=self.provider,
            model_used=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=self._calc_response_cost(model, input_tokens, output_tokens, usage),
            latency_ms=latency_ms,
        )

    async def complete_multimodal(
        self,
        system: str,
        content_parts: list[dict[str, Any]],
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> CompletionResponse:
        """Complete a multimodal request with text and images."""
        start = time.monotonic()

        openai_parts: list[dict[str, Any]] = []
        for part in content_parts:
            if part["type"] == "text":
                openai_parts.append({"type": "text", "text": part["text"]})
            elif part["type"] == "image":
                media_type = part["source"]["media_type"]
                data = part["source"]["data"]
                openai_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{media_type};base64,{data}"},
                    }
                )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": openai_parts},
        ]

        kwargs: dict[str, object] = {
            "model": model,
            self.max_tokens_field: max_tokens,
            "temperature": temperature,
            "messages": messages,
        }
        response = await self.client.chat.completions.create(**kwargs)  # type: ignore[call-overload]

        latency_ms = int((time.monotonic() - start) * 1000)
        content = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
        output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0

        return CompletionResponse(
            content=content,
            provider_used=self.provider,
            model_used=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=self._calc_response_cost(model, input_tokens, output_tokens, usage),
            latency_ms=latency_ms,
        )

    async def stream(self, request: CompletionRequest, model: str) -> StreamSession:
        """Stream a completion request using an OpenAI-compatible endpoint."""
        messages: list[dict[str, str]] = [{"role": "system", "content": request.system}]
        messages.extend(request.messages)
        start = time.monotonic()

        kwargs: dict[str, object] = {
            "model": model,
            self.max_tokens_field: request.max_tokens,
            "temperature": request.temperature,
            "messages": messages,
            "stream": True,
        }
        if self.supports_stream_usage:
            kwargs["stream_options"] = {"include_usage": True}
        if request.response_format == "json" and self.supports_json_response_format:
            kwargs["response_format"] = {"type": "json_object"}
        self._add_reasoning_kwargs(kwargs, request)

        async def _generate() -> AsyncIterator[str]:
            full_text_parts: list[str] = []
            input_tokens = 0
            output_tokens = 0
            usage = None
            response_stream = await self.client.chat.completions.create(**kwargs)  # type: ignore[call-overload]
            async for chunk in response_stream:
                usage = getattr(chunk, "usage", None) or usage
                if usage:
                    input_tokens = getattr(usage, "prompt_tokens", 0) or 0
                    output_tokens = getattr(usage, "completion_tokens", 0) or 0
                choices = getattr(chunk, "choices", None) or []
                text = getattr(choices[0].delta, "content", None) if choices else None
                if text:
                    full_text_parts.append(text)
                    yield text

            latency_ms = int((time.monotonic() - start) * 1000)
            session.result = CompletionResponse(
                content="".join(full_text_parts),
                provider_used=self.provider,
                model_used=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=self._calc_response_cost(model, input_tokens, output_tokens, usage),
                latency_ms=latency_ms,
            )

        session = StreamSession(_chunks=_generate())
        return session

    def _add_reasoning_kwargs(self, kwargs: dict[str, object], request: CompletionRequest) -> None:
        """Add provider-specific reasoning controls when explicitly requested."""
        effort = request.reasoning_effort
        if not effort or effort == "none" or not self.supports_reasoning_effort:
            return
        if self.reasoning_format == "openrouter":
            kwargs["extra_body"] = {"reasoning": {"effort": effort}}
        elif self.reasoning_format == "openai":
            kwargs["reasoning_effort"] = effort

    def _calc_response_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        usage: object | None,
    ) -> float:
        """Use provider-reported cost when present, otherwise static pricing."""
        for attr in ("cost", "total_cost"):
            raw_cost = getattr(usage, attr, None)
            if isinstance(raw_cost, (int, float)):
                return float(raw_cost)
            if isinstance(raw_cost, str):
                try:
                    return float(raw_cost)
                except ValueError:
                    continue
        return _calc_cost(self.provider, model, input_tokens, output_tokens)


class ConfiguredOpenAICompatibleProvider(OpenAICompatibleProvider):
    """OpenAI-compatible provider configured from RuntimeConfig overlay."""

    def __init__(self, api_key_override: str | None = None) -> None:
        settings = get_settings()
        rc = get_runtime_config()
        cfg = settings.llm.openai_compatible
        headers = self._default_headers(cfg.site_url, cfg.app_name)
        super().__init__(
            provider=Provider.OPENAI_COMPATIBLE,
            api_key_name="openai_compatible",
            api_key_override=api_key_override,
            base_url=rc.get_openai_compatible_base_url() or None,
            default_headers=headers,
            supports_json_response_format=rc.get_openai_compatible_field("supports_json_response_format"),
            supports_stream_usage=rc.get_openai_compatible_field("supports_stream_usage"),
            supports_reasoning_effort=rc.get_openai_compatible_field("supports_reasoning_effort"),
            max_tokens_field=cast("MaxTokensField", rc.get_openai_compatible_field("max_tokens_field")),
            reasoning_format=rc.get_openai_compatible_field("reasoning_format"),
        )

    @staticmethod
    def _default_headers(site_url: str, app_name: str) -> dict[str, str]:
        """Build optional attribution headers for compatible gateways."""
        headers: dict[str, str] = {}
        if site_url:
            headers["HTTP-Referer"] = site_url
        if app_name:
            headers["X-Title"] = app_name
        return headers
