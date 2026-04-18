"""Google Gemini LLM provider using the google.genai SDK."""

from __future__ import annotations

import base64
import time
from collections.abc import AsyncIterator
from typing import Any

from google import genai
from google.genai import types

from wikimind.config import get_api_key
from wikimind.engine.llm_router import StreamSession, _calc_cost
from wikimind.models import CompletionRequest, CompletionResponse, Provider


class GoogleProvider:
    """Google Gemini LLM provider."""

    def __init__(self) -> None:
        api_key = get_api_key("google")
        if not api_key:
            raise ValueError("Google API key not configured")
        self.client = genai.Client(api_key=api_key)

    async def complete(self, request: CompletionRequest, model: str) -> CompletionResponse:
        """Complete a request using Google Gemini."""
        start = time.monotonic()

        # google.genai accepts plain strings or types.Content objects.
        # For single-turn: pass the user message as a string.
        # For multi-turn: build types.Content objects with role mapping.
        if len(request.messages) == 1:
            contents: str | list[types.Content] = request.messages[0]["content"]
        else:
            role_map = {"user": "user", "assistant": "model"}
            contents = [
                types.Content(
                    role=role_map.get(m["role"], m["role"]),
                    parts=[types.Part.from_text(text=m["content"])],
                )
                for m in request.messages
            ]

        config_kwargs: dict[str, Any] = {
            "system_instruction": request.system,
            "max_output_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if request.response_format == "json":
            config_kwargs["response_mime_type"] = "application/json"

        response = await self.client.aio.models.generate_content(
            model=model,
            contents=contents,  # type: ignore[arg-type]
            config=types.GenerateContentConfig(**config_kwargs),
        )

        latency_ms = int((time.monotonic() - start) * 1000)
        content = response.text or ""
        usage = response.usage_metadata
        input_tokens = (usage.prompt_token_count or 0) if usage else 0
        output_tokens = (usage.candidates_token_count or 0) if usage else 0

        return CompletionResponse(
            content=content,
            provider_used=Provider.GOOGLE,
            model_used=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=_calc_cost(Provider.GOOGLE, model, input_tokens, output_tokens),
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
        """Complete a multimodal request with text and images using Google Gemini.

        Translates the Anthropic-style content blocks to Google's
        ``types.Part.from_bytes`` format before calling the API.

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

        # Translate Anthropic content blocks to Google format
        google_parts: list = []
        for part in content_parts:
            if part["type"] == "text":
                google_parts.append(part["text"])
            elif part["type"] == "image":
                media_type = part["source"]["media_type"]
                data_b64 = part["source"]["data"]
                google_parts.append(
                    types.Part.from_bytes(
                        data=base64.b64decode(data_b64),
                        mime_type=media_type,
                    )
                )

        response = await self.client.aio.models.generate_content(
            model=model,
            contents=google_parts,
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=max_tokens,
                temperature=temperature,
            ),
        )

        latency_ms = int((time.monotonic() - start) * 1000)
        content = response.text or ""
        usage = response.usage_metadata
        input_tokens = (usage.prompt_token_count or 0) if usage else 0
        output_tokens = (usage.candidates_token_count or 0) if usage else 0

        return CompletionResponse(
            content=content,
            provider_used=Provider.GOOGLE,
            model_used=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=_calc_cost(Provider.GOOGLE, model, input_tokens, output_tokens),
            latency_ms=latency_ms,
        )

    async def stream(self, request: CompletionRequest, model: str) -> StreamSession:
        """Stream a completion request using Google Gemini."""
        start = time.monotonic()

        if len(request.messages) == 1:
            contents: str | list[types.Content] = request.messages[0]["content"]
        else:
            role_map = {"user": "user", "assistant": "model"}
            contents = [
                types.Content(
                    role=role_map.get(m["role"], m["role"]),
                    parts=[types.Part.from_text(text=m["content"])],
                )
                for m in request.messages
            ]

        config_kwargs: dict[str, Any] = {
            "system_instruction": request.system,
            "max_output_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if request.response_format == "json":
            config_kwargs["response_mime_type"] = "application/json"

        async def _generate() -> AsyncIterator[str]:
            full_text_parts: list[str] = []
            input_tokens = 0
            output_tokens = 0

            async for chunk in await self.client.aio.models.generate_content_stream(
                model=model,
                contents=contents,  # type: ignore[arg-type]
                config=types.GenerateContentConfig(**config_kwargs),
            ):
                text = chunk.text
                if text:
                    full_text_parts.append(text)
                    yield text
                if chunk.usage_metadata:
                    if chunk.usage_metadata.prompt_token_count:
                        input_tokens = chunk.usage_metadata.prompt_token_count
                    if chunk.usage_metadata.candidates_token_count:
                        output_tokens = chunk.usage_metadata.candidates_token_count

            latency_ms = int((time.monotonic() - start) * 1000)
            session.result = CompletionResponse(
                content="".join(full_text_parts),
                provider_used=Provider.GOOGLE,
                model_used=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=_calc_cost(Provider.GOOGLE, model, input_tokens, output_tokens),
                latency_ms=latency_ms,
            )

        session = StreamSession(_chunks=_generate())
        return session
