"""WikiMind LLM Router.

Single interface for all LLM providers.
Handles selection, fallback, cost tracking, and token budgeting.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

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
# Pricing (USD per 1M tokens) -- update as providers change pricing
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
        "*": {"input": 0.0, "output": 0.0},  # Free -- local
    },
    Provider.MOCK: {
        "*": {"input": 0.0, "output": 0.0},  # Free -- deterministic
    },
}


def _calc_cost(provider: Provider, model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate the USD cost of an LLM call based on token counts."""
    provider_pricing = PRICING.get(provider, {})
    model_pricing = provider_pricing.get(model) or provider_pricing.get("*", {"input": 0, "output": 0})
    return (input_tokens * model_pricing["input"] + output_tokens * model_pricing["output"]) / 1_000_000


# ---------------------------------------------------------------------------
# StreamSession -- wraps a streaming LLM response
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
# Provider imports -- each provider lives in its own file under providers/
# ---------------------------------------------------------------------------

from wikimind.engine.providers import (  # noqa: E402
    AnthropicProvider,
    GoogleProvider,
    MockProvider,
    OllamaProvider,
    OpenAIProvider,
)
from wikimind.engine.providers.mock import (  # noqa: E402, F401 -- backward compat re-exports
    _MOCK_COMPILE_RESPONSE,
    _MOCK_LINT_RESPONSE,
    _MOCK_QA_RESPONSE,
)

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
        """Check if a provider is enabled and has credentials."""
        cfg = getattr(self.settings.llm, provider.value, None)
        if not cfg or not cfg.enabled:
            return False
        if provider in (Provider.OLLAMA, Provider.MOCK):
            return True  # No API key needed
        return bool(get_api_key(provider.value))

    async def _get_provider_instance(self, provider: Provider):
        """Create and return a provider instance."""
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
        """Return the configured model name for a provider."""
        cfg = getattr(self.settings.llm, provider.value, None)
        return cfg.model if cfg else "unknown"

    async def _check_budget(self) -> None:
        """Check monthly budget and emit warnings if thresholds are exceeded."""
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
