"""WikiMind LLM Router.

Single interface for all LLM providers.
Handles selection, fallback, cost tracking, and token budgeting.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import anthropic
import google.generativeai as genai
import ollama
import openai
import structlog
from sqlalchemy import func
from sqlmodel import select

from wikimind._datetime import utcnow_naive
from wikimind.api.routes.ws import emit_budget_exceeded, emit_budget_warning
from wikimind.config import get_api_key, get_settings
from wikimind.database import get_session_factory
from wikimind.models import CompletionRequest, CompletionResponse, CostLog, Provider, TaskType

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Pricing (USD per 1M tokens) — update as providers change pricing
# ---------------------------------------------------------------------------

PRICING = {
    Provider.ANTHROPIC: {
        "claude-sonnet-4-5": {"input": 3.00, "output": 15.00},
        "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    },
    Provider.OPENAI: {
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    },
    Provider.GOOGLE: {
        "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    },
    Provider.OLLAMA: {
        "*": {"input": 0.0, "output": 0.0},  # Free — local
    },
    Provider.MOCK: {
        "*": {"input": 0.0, "output": 0.0},  # Free — deterministic
    },
}


def _calc_cost(provider: Provider, model: str, input_tokens: int, output_tokens: int) -> float:
    provider_pricing = PRICING.get(provider, {})
    model_pricing = provider_pricing.get(model) or provider_pricing.get("*", {"input": 0, "output": 0})
    return (input_tokens * model_pricing["input"] + output_tokens * model_pricing["output"]) / 1_000_000


# ---------------------------------------------------------------------------
# StreamSession — wraps a streaming LLM response
# ---------------------------------------------------------------------------


@dataclass
class StreamSession:
    """Wraps a streaming LLM response. Async-iterate for text chunks.

    After iteration completes, ``result`` is populated with token counts
    and cost information from the provider.
    """

    _chunks: AsyncIterator[str]
    result: CompletionResponse | None = field(default=None, init=True)

    def __aiter__(self) -> AsyncIterator[str]:  # noqa: D105
        return self._chunks


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------


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
        content = response.choices[0].message.content
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


class GoogleProvider:
    """Google Gemini LLM provider."""

    def __init__(self) -> None:
        api_key = get_api_key("google")
        if not api_key:
            raise ValueError("Google API key not configured")
        genai.configure(api_key=api_key)

    async def complete(self, request: CompletionRequest, model: str) -> CompletionResponse:
        """Complete a request using Google Gemini."""
        start = time.monotonic()

        gen_model = genai.GenerativeModel(model, system_instruction=request.system)

        contents = [{"role": m["role"], "parts": [m["content"]]} for m in request.messages]

        generation_config: dict[str, Any] = {
            "max_output_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if request.response_format == "json":
            generation_config["response_mime_type"] = "application/json"

        response = await gen_model.generate_content_async(
            contents,
            generation_config=generation_config,
        )

        latency_ms = int((time.monotonic() - start) * 1000)
        content = response.text
        usage = response.usage_metadata
        input_tokens = usage.prompt_token_count if usage else 0
        output_tokens = usage.candidates_token_count if usage else 0

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

        Translates the Anthropic-style content blocks to Google's inline
        data format before calling the API.

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

        gen_model = genai.GenerativeModel(model, system_instruction=system)

        # Translate Anthropic content blocks to Google format
        google_parts: list[str | dict[str, str | bytes]] = []
        for part in content_parts:
            if part["type"] == "text":
                google_parts.append(part["text"])
            elif part["type"] == "image":
                media_type = part["source"]["media_type"]
                data_b64 = part["source"]["data"]
                google_parts.append(
                    {
                        "mime_type": media_type,
                        "data": base64.b64decode(data_b64),
                    }
                )

        response = await gen_model.generate_content_async(
            google_parts,
            generation_config={
                "max_output_tokens": max_tokens,
                "temperature": temperature,
            },
        )

        latency_ms = int((time.monotonic() - start) * 1000)
        content = response.text
        usage = response.usage_metadata
        input_tokens = usage.prompt_token_count if usage else 0
        output_tokens = usage.candidates_token_count if usage else 0

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

        gen_model = genai.GenerativeModel(model, system_instruction=request.system)

        contents = [{"role": m["role"], "parts": [m["content"]]} for m in request.messages]

        generation_config: dict[str, Any] = {
            "max_output_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if request.response_format == "json":
            generation_config["response_mime_type"] = "application/json"

        async def _generate() -> AsyncIterator[str]:
            full_text_parts: list[str] = []
            input_tokens = 0
            output_tokens = 0

            response = await gen_model.generate_content_async(
                contents,
                generation_config=generation_config,
                stream=True,
            )
            async for chunk in response:
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


class MockProvider:
    """Deterministic mock provider for CI e2e testing.

    Returns canned JSON keyed off the TaskType so callers that expect
    CompilationResult / QueryResult shapes can parse the response
    without a real LLM. Zero cost, zero network, fully deterministic.

    Must be explicitly enabled via ``WIKIMIND_LLM__MOCK__ENABLED=true``
    AND set as the default provider via ``WIKIMIND_LLM__DEFAULT_PROVIDER=mock``
    to be selected — disabled by default so it cannot silently
    intercept real traffic.
    """

    def __init__(self) -> None:
        # No config needed; all responses are canned
        pass

    async def complete(self, request: CompletionRequest, model: str) -> CompletionResponse:
        """Return a deterministic canned response matching the request's task type."""
        start = time.monotonic()
        content = self._response_for(request)
        latency_ms = int((time.monotonic() - start) * 1000)
        return CompletionResponse(
            content=content,
            provider_used=Provider.MOCK,
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
        """Return a deterministic description for each image in the request."""
        start = time.monotonic()
        # Count images and return one description per image
        image_count = sum(1 for p in content_parts if p.get("type") == "image")
        descriptions = [
            f"[Page {i + 1} description: A visual slide with diagrams and minimal text.]" for i in range(image_count)
        ]
        content = "\n\n".join(descriptions) if descriptions else "No images provided."
        latency_ms = int((time.monotonic() - start) * 1000)
        return CompletionResponse(
            content=content,
            provider_used=Provider.MOCK,
            model_used=model,
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            latency_ms=latency_ms,
        )

    async def stream(self, request: CompletionRequest, model: str) -> StreamSession:
        """Stream a deterministic canned response in small chunks."""
        content = self._response_for(request)
        start = time.monotonic()
        chunk_size = 20

        async def _generate() -> AsyncIterator[str]:
            for i in range(0, len(content), chunk_size):
                yield content[i : i + chunk_size]

            latency_ms = int((time.monotonic() - start) * 1000)
            session.result = CompletionResponse(
                content=content,
                provider_used=Provider.MOCK,
                model_used=model,
                input_tokens=0,
                output_tokens=0,
                cost_usd=0.0,
                latency_ms=latency_ms,
            )

        session = StreamSession(_chunks=_generate())
        return session

    @staticmethod
    def _response_for(request: CompletionRequest) -> str:
        """Return a canned response body matching the task's expected shape."""
        if request.task_type == TaskType.COMPILE:
            return json.dumps(_MOCK_COMPILE_RESPONSE)
        if request.task_type == TaskType.QA:
            return json.dumps(_MOCK_QA_RESPONSE)
        if request.task_type == TaskType.LINT:
            return json.dumps(_MOCK_LINT_RESPONSE)
        # Unknown task type: return an empty JSON object so parse_json_response
        # doesn't crash. Tests that need specific shapes should add a mock
        # for their task type.
        return "{}"


# Canned responses used by MockProvider. Defined at module level so tests
# can import and assert against them directly.
_MOCK_COMPILE_RESPONSE: dict = {
    "title": "Mock Article",
    "summary": "A deterministic summary produced by the mock LLM provider for testing.",
    "key_claims": [
        {
            "claim": "This article was produced by the mock LLM provider.",
            "confidence": "sourced",
            "quote": "mock provider",
        }
    ],
    "concepts": ["testing", "mock"],
    "backlink_suggestions": [],
    "open_questions": ["What is real?"],
    "article_body": (
        "## Mock Article\n\n"
        "This article was produced by the mock LLM provider for deterministic "
        "e2e testing.\n\n"
        "## Details\n\n"
        "The mock provider returns canned responses regardless of input, "
        "enabling CI to run the full Ask loop without a real LLM API."
    ),
}

_MOCK_QA_RESPONSE: dict = {
    "answer": (
        "This is a mock answer from the WikiMind mock LLM provider. "
        "Your question was received and processed deterministically "
        "for testing purposes."
    ),
    "confidence": "high",
    "sources": ["Mock Article"],
    "related_articles": [],
    "new_article_suggested": None,
    "follow_up_questions": [],
}

_MOCK_LINT_RESPONSE: dict = {
    "contradictions": [],
    "stale_claims": [],
    "orphan_articles": [],
    "missing_pages": [],
    "data_gaps": [],
}


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class LLMRouter:
    """Route LLM calls to the appropriate provider with fallback and cost tracking."""

    def __init__(self):
        self.settings = get_settings()
        self._budget_warning_sent = False
        self._budget_exceeded_sent = False
        self._cached_spend: float | None = None
        self._cache_expires_at: float = 0.0

    def _get_provider_order(self, preferred: Provider | None) -> list[Provider]:
        """Return ordered list of providers to try."""
        default = Provider(self.settings.llm.default_provider)
        order = []

        if preferred:
            order.append(preferred)
        if default not in order:
            order.append(default)

        # Add remaining enabled providers as fallbacks
        for p in Provider:
            if p not in order:
                cfg = getattr(self.settings.llm, p.value, None)
                if cfg and cfg.enabled:
                    order.append(p)

        return order

    def _is_provider_available(self, provider: Provider) -> bool:
        cfg = getattr(self.settings.llm, provider.value, None)
        if not cfg or not cfg.enabled:
            return False
        if provider in (Provider.OLLAMA, Provider.MOCK):
            return True  # No API key needed
        return bool(get_api_key(provider.value))

    async def _get_provider_instance(self, provider: Provider):
        if provider == Provider.ANTHROPIC:
            return AnthropicProvider()
        elif provider == Provider.OPENAI:
            return OpenAIProvider()
        elif provider == Provider.GOOGLE:
            return GoogleProvider()
        elif provider == Provider.OLLAMA:
            return OllamaProvider(self.settings.llm.ollama_base_url)
        elif provider == Provider.MOCK:
            return MockProvider()
        else:
            raise ValueError(f"Provider {provider} not implemented yet")

    def _get_model(self, provider: Provider) -> str:
        cfg = getattr(self.settings.llm, provider.value, None)
        return cfg.model if cfg else "unknown"

    async def _check_budget(self) -> None:
        if self._budget_warning_sent and self._budget_exceeded_sent:
            return

        now = time.time()
        if self._cached_spend is not None and now < self._cache_expires_at:
            spend = self._cached_spend
        else:
            start_of_month = utcnow_naive().replace(day=1, hour=0, minute=0, second=0)
            async with get_session_factory()() as session:
                result = await session.execute(
                    select(func.sum(CostLog.cost_usd)).where(CostLog.created_at >= start_of_month)
                )
                spend = result.scalar() or 0.0
            self._cached_spend = spend
            self._cache_expires_at = now + self.settings.llm.budget_check_cache_seconds

        budget = self.settings.llm.monthly_budget_usd
        if budget <= 0:
            return
        pct = spend / budget * 100

        if pct >= self.settings.llm.budget_warning_pct * 100 and not self._budget_warning_sent:
            log.warning("Budget warning threshold reached", spend_usd=spend, budget_usd=budget, pct=round(pct, 1))
            await emit_budget_warning(spend, budget, pct)
            self._budget_warning_sent = True

        if pct >= 100.0 and not self._budget_exceeded_sent:
            log.error("Budget exceeded", spend_usd=spend, budget_usd=budget)
            await emit_budget_exceeded(spend, budget)
            self._budget_exceeded_sent = True

    async def complete(
        self,
        request: CompletionRequest,
        session=None,  # AsyncSession for cost logging
    ) -> CompletionResponse:
        """Execute LLM completion with provider selection and fallback."""
        provider_order = self._get_provider_order(request.preferred_provider)

        last_error = None
        for provider in provider_order:
            if not self._is_provider_available(provider):
                continue

            model = self._get_model(provider)
            try:
                log.info("LLM call", provider=provider, model=model, task=request.task_type)
                instance = await self._get_provider_instance(provider)
                response = await instance.complete(request, model)

                # Log cost
                if session:
                    cost_entry = CostLog(
                        provider=provider,
                        model=model,
                        task_type=request.task_type,
                        input_tokens=response.input_tokens,
                        output_tokens=response.output_tokens,
                        cost_usd=response.cost_usd,
                        latency_ms=response.latency_ms,
                    )
                    session.add(cost_entry)
                    await session.commit()

                log.info(
                    "LLM call complete",
                    provider=provider,
                    cost_usd=response.cost_usd,
                    latency_ms=response.latency_ms,
                )
                task = asyncio.create_task(self._check_budget())
                task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
                return response

            except Exception as e:
                log.warning("LLM provider failed", provider=provider, error=str(e))
                last_error = e
                if not self.settings.llm.fallback_enabled:
                    raise

        raise RuntimeError(f"All LLM providers failed. Last error: {last_error}")

    async def complete_multimodal(
        self,
        system: str,
        content_parts: list[dict[str, Any]],
        task_type: TaskType = TaskType.INGEST,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        preferred_provider: Provider | None = None,
        session=None,
    ) -> CompletionResponse:
        """Execute a multimodal LLM completion with images and text.

        Routes to the appropriate provider and translates content blocks
        as needed. Supports fallback across providers just like
        :meth:`complete`.

        Args:
            system: System prompt.
            content_parts: List of content blocks (text and image).
            task_type: Task type for cost tracking.
            max_tokens: Maximum output tokens.
            temperature: Sampling temperature.
            preferred_provider: Optional provider preference.
            session: Optional AsyncSession for cost logging.

        Returns:
            CompletionResponse with the LLM's text output.

        Raises:
            RuntimeError: When all providers fail.
        """
        provider_order = self._get_provider_order(preferred_provider)

        last_error = None
        for provider in provider_order:
            if not self._is_provider_available(provider):
                continue

            model = self._get_model(provider)
            try:
                log.info(
                    "LLM multimodal call",
                    provider=provider,
                    model=model,
                    task=task_type,
                )
                instance = await self._get_provider_instance(provider)
                response = await instance.complete_multimodal(
                    system=system,
                    content_parts=content_parts,
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )

                # Log cost
                if session:
                    cost_entry = CostLog(
                        provider=provider,
                        model=model,
                        task_type=task_type,
                        input_tokens=response.input_tokens,
                        output_tokens=response.output_tokens,
                        cost_usd=response.cost_usd,
                        latency_ms=response.latency_ms,
                    )
                    session.add(cost_entry)
                    await session.commit()

                log.info(
                    "LLM multimodal call complete",
                    provider=provider,
                    cost_usd=response.cost_usd,
                    latency_ms=response.latency_ms,
                )
                return response

            except Exception as e:
                log.warning("LLM multimodal provider failed", provider=provider, error=str(e))
                last_error = e
                if not self.settings.llm.fallback_enabled:
                    raise

        raise RuntimeError(f"All LLM providers failed. Last error: {last_error}")

    async def stream_complete(
        self,
        request: CompletionRequest,
    ) -> StreamSession:
        """Create a streaming LLM completion with provider fallback.

        Fallback happens during stream creation only. Once tokens begin
        flowing, no mid-stream provider switch occurs -- errors surface
        as exceptions from the async iterator.

        Args:
            request: The completion request.

        Returns:
            A :class:`StreamSession` that yields text chunks.

        Raises:
            RuntimeError: When all providers fail during stream creation.
        """
        provider_order = self._get_provider_order(request.preferred_provider)

        last_error = None
        for provider in provider_order:
            if not self._is_provider_available(provider):
                continue

            model = self._get_model(provider)
            try:
                log.info(
                    "LLM stream call",
                    provider=provider,
                    model=model,
                    task=request.task_type,
                )
                instance = await self._get_provider_instance(provider)
                return await instance.stream(request, model)
            except Exception as e:
                log.warning(
                    "LLM stream provider failed",
                    provider=provider,
                    error=str(e),
                )
                last_error = e
                if not self.settings.llm.fallback_enabled:
                    raise

        raise RuntimeError(f"All LLM providers failed. Last error: {last_error}")

    def parse_json_response(self, response: CompletionResponse) -> dict:
        """Parse JSON from LLM response, stripping markdown fences if present."""
        content = response.content.strip()
        if content.startswith("```"):
            # Find the closing ``` fence (not just the last line)
            lines = content.split("\n")
            # Skip the opening ```json line
            body_lines = lines[1:]
            # Find the closing ``` and take everything before it
            for i, line in enumerate(body_lines):
                if line.strip() == "```":
                    content = "\n".join(body_lines[:i])
                    break
        return json.loads(content)


# Singleton
_router: LLMRouter | None = None


def get_llm_router() -> LLMRouter:
    """Return the singleton LLM router."""
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router
