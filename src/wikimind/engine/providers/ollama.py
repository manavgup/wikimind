"""Ollama local LLM provider."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

import ollama

from wikimind.engine.llm_router import StreamSession
from wikimind.models import CompletionRequest, CompletionResponse, Provider


class OllamaProvider:
    """Ollama local LLM provider."""

    def __init__(self, base_url: str):
        self.client = ollama.AsyncClient(host=base_url)

    async def complete(self, request: CompletionRequest, model: str) -> CompletionResponse:
        """Complete a request using Ollama."""
        start = time.monotonic()

        messages = [{"role": "system", "content": request.system}]
        messages.extend(request.messages)

        response = await self.client.chat(
            model=model,
            messages=messages,
            options={"temperature": request.temperature},
        )

        latency_ms = int((time.monotonic() - start) * 1000)
        content = response["message"]["content"]

        return CompletionResponse(
            content=content,
            provider_used=Provider.OLLAMA,
            model_used=model,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
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
        """Complete a multimodal request using Ollama.

        Ollama accepts images as base64 strings in the ``images`` field
        of a message.

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

        # Extract text and images from content parts
        text_parts: list[str] = []
        images: list[str] = []
        for part in content_parts:
            if part["type"] == "text":
                text_parts.append(part["text"])
            elif part["type"] == "image":
                images.append(part["source"]["data"])

        user_content = "\n".join(text_parts) if text_parts else "Describe these images."
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content, "images": images},
        ]

        response = await self.client.chat(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            options={"temperature": temperature},
        )

        latency_ms = int((time.monotonic() - start) * 1000)
        content = response["message"]["content"]

        return CompletionResponse(
            content=content,
            provider_used=Provider.OLLAMA,
            model_used=model,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            latency_ms=latency_ms,
        )

    async def stream(self, request: CompletionRequest, model: str) -> StreamSession:
        """Stream a completion request using Ollama."""
        messages: list[dict[str, str]] = [{"role": "system", "content": request.system}]
        messages.extend(request.messages)
        start = time.monotonic()

        async def _generate() -> AsyncIterator[str]:
            full_text_parts: list[str] = []
            response_stream = await self.client.chat(
                model=model,
                messages=messages,
                options={"temperature": request.temperature},
                stream=True,
            )
            async for chunk in response_stream:  # type: ignore[union-attr]
                text = chunk["message"]["content"]
                if text:
                    full_text_parts.append(text)
                    yield text

            latency_ms = int((time.monotonic() - start) * 1000)
            session.result = CompletionResponse(
                content="".join(full_text_parts),
                provider_used=Provider.OLLAMA,
                model_used=model,
                input_tokens=0,
                output_tokens=0,
                cost_usd=0.0,
                latency_ms=latency_ms,
            )

        session = StreamSession(_chunks=_generate())
        return session
