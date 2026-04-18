"""OpenAI LLM provider."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

import openai

from wikimind.config import get_api_key
from wikimind.engine.llm_router import StreamSession, _calc_cost
from wikimind.models import CompletionRequest, CompletionResponse, Provider


class OpenAIProvider:
    """OpenAI LLM provider."""

    def __init__(self):
        api_key = get_api_key("openai")
        if not api_key:
            raise ValueError("OpenAI API key not configured")
        self.client = openai.AsyncOpenAI(api_key=api_key)

    async def complete(self, request: CompletionRequest, model: str) -> CompletionResponse:
        """Complete a request using OpenAI."""
        start = time.monotonic()

        messages = [{"role": "system", "content": request.system}]
        messages.extend(request.messages)

        kwargs: dict[str, object] = dict(
            model=model,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            messages=messages,
        )
        if request.response_format == "json":
            kwargs["response_format"] = {"type": "json_object"}

        response = await self.client.chat.completions.create(**kwargs)  # type: ignore[call-overload]

        latency_ms = int((time.monotonic() - start) * 1000)
        content = response.choices[0].message.content
        input_tokens = response.usage.prompt_tokens
        output_tokens = response.usage.completion_tokens

        return CompletionResponse(
            content=content,
            provider_used=Provider.OPENAI,
            model_used=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=_calc_cost(Provider.OPENAI, model, input_tokens, output_tokens),
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
        """Complete a multimodal request with text and images using OpenAI.

        Translates the Anthropic-style content blocks to OpenAI's
        ``image_url`` format before calling the API.

        Args:
            system: System prompt.
            content_parts: List of content blocks in Anthropic format.
            model: Model name to use.
            max_tokens: Maximum output tokens.
            temperature: Sampling temperature.

        Returns:
            CompletionResponse with the LLM's text output.
        """
        start = time.monotonic()

        # Translate Anthropic content blocks to OpenAI format
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

        response = await self.client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=messages,  # type: ignore[arg-type]
        )

        latency_ms = int((time.monotonic() - start) * 1000)
        content = response.choices[0].message.content or ""
        input_tokens = response.usage.prompt_tokens if response.usage else 0
        output_tokens = response.usage.completion_tokens if response.usage else 0

        return CompletionResponse(
            content=content,
            provider_used=Provider.OPENAI,
            model_used=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=_calc_cost(Provider.OPENAI, model, input_tokens, output_tokens),
            latency_ms=latency_ms,
        )

    async def stream(self, request: CompletionRequest, model: str) -> StreamSession:
        """Stream a completion request using OpenAI."""
        messages: list[dict[str, str]] = [{"role": "system", "content": request.system}]
        messages.extend(request.messages)
        start = time.monotonic()

        kwargs: dict[str, object] = dict(
            model=model,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            messages=messages,
            stream=True,
            stream_options={"include_usage": True},
        )
        if request.response_format == "json":
            kwargs["response_format"] = {"type": "json_object"}

        async def _generate() -> AsyncIterator[str]:
            full_text_parts: list[str] = []
            input_tokens = 0
            output_tokens = 0
            response_stream = await self.client.chat.completions.create(
                **kwargs  # type: ignore[call-overload]
            )
            async for chunk in response_stream:  # type: ignore[union-attr]
                if chunk.usage:
                    input_tokens = chunk.usage.prompt_tokens or 0
                    output_tokens = chunk.usage.completion_tokens or 0
                if chunk.choices and chunk.choices[0].delta.content:
                    text = chunk.choices[0].delta.content
                    full_text_parts.append(text)
                    yield text

            latency_ms = int((time.monotonic() - start) * 1000)
            session.result = CompletionResponse(
                content="".join(full_text_parts),
                provider_used=Provider.OPENAI,
                model_used=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=_calc_cost(Provider.OPENAI, model, input_tokens, output_tokens),
                latency_ms=latency_ms,
            )

        session = StreamSession(_chunks=_generate())
        return session
