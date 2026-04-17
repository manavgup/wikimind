"""Anthropic LLM provider."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

import anthropic

from wikimind.config import get_api_key
from wikimind.engine.llm_router import StreamSession, _calc_cost
from wikimind.models import CompletionRequest, CompletionResponse, Provider


class AnthropicProvider:
    """Anthropic LLM provider."""

    def __init__(self):
        api_key = get_api_key("anthropic")
        if not api_key:
            raise ValueError("Anthropic API key not configured")
        self.client = anthropic.AsyncAnthropic(api_key=api_key)

    async def complete(self, request: CompletionRequest, model: str) -> CompletionResponse:
        """Complete a request using Anthropic."""
        start = time.monotonic()

        messages = [{"role": m["role"], "content": m["content"]} for m in request.messages]

        response = await self.client.messages.create(
            model=model,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            system=request.system,
            messages=messages,  # type: ignore[arg-type]
        )

        latency_ms = int((time.monotonic() - start) * 1000)
        content = response.content[0].text  # type: ignore[union-attr]
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens

        return CompletionResponse(
            content=content,
            provider_used=Provider.ANTHROPIC,
            model_used=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=_calc_cost(Provider.ANTHROPIC, model, input_tokens, output_tokens),
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
        """Complete a multimodal request with text and images using Anthropic.

        Args:
            system: System prompt.
            content_parts: List of content blocks. Each block is either
                ``{"type": "text", "text": "..."}`` or
                ``{"type": "image", "source": {"type": "base64",
                "media_type": "image/png", "data": "..."}}``.
            model: Model name to use.
            max_tokens: Maximum output tokens.
            temperature: Sampling temperature.

        Returns:
            CompletionResponse with the LLM's text output.
        """
        start = time.monotonic()

        response = await self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": content_parts}],  # type: ignore[arg-type,typeddict-item]
        )

        latency_ms = int((time.monotonic() - start) * 1000)
        content = response.content[0].text  # type: ignore[union-attr]
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens

        return CompletionResponse(
            content=content,
            provider_used=Provider.ANTHROPIC,
            model_used=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=_calc_cost(Provider.ANTHROPIC, model, input_tokens, output_tokens),
            latency_ms=latency_ms,
        )

    async def stream(self, request: CompletionRequest, model: str) -> StreamSession:
        """Stream a completion request using Anthropic."""
        messages = [{"role": m["role"], "content": m["content"]} for m in request.messages]
        start = time.monotonic()

        async def _generate() -> AsyncIterator[str]:
            async with self.client.messages.stream(
                model=model,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                system=request.system,
                messages=messages,  # type: ignore[arg-type]
            ) as stream_ctx:
                async for text in stream_ctx.text_stream:
                    yield text

                final = await stream_ctx.get_final_message()
                latency_ms = int((time.monotonic() - start) * 1000)
                input_tokens = final.usage.input_tokens
                output_tokens = final.usage.output_tokens
                full_text = "".join(getattr(block, "text", "") for block in final.content)
                session.result = CompletionResponse(
                    content=full_text,
                    provider_used=Provider.ANTHROPIC,
                    model_used=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=_calc_cost(Provider.ANTHROPIC, model, input_tokens, output_tokens),
                    latency_ms=latency_ms,
                )

        session = StreamSession(_chunks=_generate())
        return session
