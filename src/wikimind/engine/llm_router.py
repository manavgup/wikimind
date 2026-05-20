"""WikiMind LLM Router.

Single interface for all LLM providers.
Handles selection, fallback, cost tracking, and token budgeting.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import TYPE_CHECKING, Any, TypeVar

import structlog
from redis.asyncio import Redis
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select

try:
    from redis.exceptions import RedisError
except ImportError:  # redis package not installed
    RedisError = OSError  # type: ignore[assignment,misc]

from wikimind._datetime import utcnow_naive
from wikimind.config import get_api_key, get_runtime_config, get_settings
from wikimind.database import get_session_factory
from wikimind.engine.events import BudgetEventEmitter, NullBudgetEventEmitter
from wikimind.errors import UpstreamError
from wikimind.models import (
    CompletionRequest,
    CompletionResponse,
    CostLog,
    LLMTrace,
    Provider,
    TaskType,
)
from wikimind.services.api_keys import get_user_api_key

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from wikimind.engine.provider_base import StreamSession

log = structlog.get_logger()

_T = TypeVar("_T")


# ---------------------------------------------------------------------------
# Redis helper for cross-replica budget flag dedup
# ---------------------------------------------------------------------------

_budget_redis_pool = None


async def _get_budget_redis():
    """Return a shared Redis connection for budget flag dedup.

    Returns ``None`` when Redis is not configured or unavailable.
    """
    global _budget_redis_pool
    if _budget_redis_pool is not None:
        return _budget_redis_pool

    redis_url = get_settings().redis_url
    if not redis_url:
        return None

    try:
        _budget_redis_pool = Redis.from_url(redis_url, decode_responses=True)
        return _budget_redis_pool
    except (RedisError, OSError):
        log.debug("Redis unavailable for budget dedup — per-process flags only")
        return None


# ---------------------------------------------------------------------------
# Provider imports -- each provider lives in its own file under providers/
# ---------------------------------------------------------------------------

import anthropic  # noqa: E402
import httpx  # noqa: E402
import openai  # noqa: E402
from google.genai import errors as google_errors  # noqa: E402

from wikimind.engine.providers import (  # noqa: E402
    AnthropicProvider,
    ConfiguredOpenAICompatibleProvider,
    GoogleProvider,
    MockProvider,
    OllamaProvider,
    OpenAIProvider,
    ProviderProtocol,
)
from wikimind.engine.providers.mock import (  # noqa: E402, F401 -- backward compat re-exports
    _MOCK_COMPILE_RESPONSE,
    _MOCK_LINT_RESPONSE,
    _MOCK_QA_RESPONSE,
)

_LLM_PROVIDER_ERRORS = (
    openai.OpenAIError,
    anthropic.AnthropicError,
    google_errors.APIError,
    httpx.HTTPError,
    UpstreamError,
    ValueError,
    KeyError,
    OSError,
)

# ---------------------------------------------------------------------------
# JSON sanitization helper
# ---------------------------------------------------------------------------

# Matches C0 control characters (U+0000..U+001F) that are illegal inside
# JSON strings per RFC 8259.  \n, \r, and \t are replaced with their
# standard escape sequences; all others are replaced with a space.
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _replace_control_chars_in_json_string(match: re.Match) -> str:
    """Escape bare control characters inside a single JSON string literal."""
    s = match.group(0)
    s = s.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    s = _CONTROL_CHAR_RE.sub(" ", s)
    return s


def _sanitize_json_control_chars(text: str) -> str:
    """Replace illegal JSON control characters inside string values.

    Only operates inside quoted strings so that structural JSON whitespace
    (the newlines and spaces between keys/values) is left intact.
    """
    return re.sub(r'"(?:[^"\\]|\\.)*"', _replace_control_chars_in_json_string, text)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class LLMRouter:
    """Route LLM calls to the appropriate provider with fallback and cost tracking."""

    def __init__(self, *, event_emitter: BudgetEventEmitter | None = None):
        self.settings = get_settings()
        self._rc = get_runtime_config()
        self._event_emitter: BudgetEventEmitter = event_emitter or NullBudgetEventEmitter()
        self._budget_warning_sent: dict[str, tuple[int, int]] = {}
        self._budget_exceeded_sent: dict[str, tuple[int, int]] = {}
        self._cached_spend: dict[str, float] = {}
        self._cache_expires_at: dict[str, float] = {}
        self._provider_cache: dict[Provider, ProviderProtocol] = {}

    def _get_provider_order(self, preferred: Provider | None) -> list[Provider]:
        """Return ordered list of providers to try."""
        default = Provider(self._rc.get_default_provider())
        order = []

        if preferred:
            order.append(preferred)
        if default not in order:
            order.append(default)

        # Add remaining enabled providers as fallbacks
        for p in Provider:
            if p not in order:
                if p == Provider.OPENAI_COMPATIBLE:
                    if self._rc.get_openai_compatible_enabled():
                        order.append(p)
                else:
                    cfg = getattr(self.settings.llm, p.value, None)
                    if cfg and cfg.enabled:
                        order.append(p)

        return order

    def _is_provider_available(self, provider: Provider) -> bool:
        """Check if a provider is enabled and has credentials."""
        if provider == Provider.OPENAI_COMPATIBLE:
            return bool(
                get_api_key(provider.value)
                and self._rc.get_openai_compatible_model()
                and self._rc.get_openai_compatible_base_url()
            )
        cfg = getattr(self.settings.llm, provider.value, None)
        if not cfg or not cfg.enabled:
            return False
        if provider in (Provider.OLLAMA, Provider.MOCK):
            return True  # No API key needed
        return bool(get_api_key(provider.value))

    async def _get_provider_instance(
        self,
        provider: Provider,
        api_key_override: str | None = None,
    ) -> ProviderProtocol:
        """Return a provider instance.

        When *api_key_override* is supplied (BYOK), a fresh instance is
        created with that key and is NOT cached -- the user's key must
        not leak into the shared singleton cache.  Without an override,
        the system-wide cached instance is returned.
        """
        if api_key_override is None and provider in self._provider_cache:
            return self._provider_cache[provider]

        instance: ProviderProtocol
        if provider == Provider.ANTHROPIC:
            instance = AnthropicProvider(api_key_override=api_key_override)
        elif provider == Provider.OPENAI:
            instance = OpenAIProvider(api_key_override=api_key_override)
        elif provider == Provider.OPENAI_COMPATIBLE:
            instance = ConfiguredOpenAICompatibleProvider(api_key_override=api_key_override)
        elif provider == Provider.GOOGLE:
            instance = GoogleProvider(api_key_override=api_key_override)
        elif provider == Provider.OLLAMA:
            instance = OllamaProvider(self.settings.llm.ollama_base_url)
        elif provider == Provider.MOCK:
            instance = MockProvider()
        else:
            msg = f"Provider {provider} not implemented yet"
            raise ValueError(msg)

        # Only cache system-key instances
        if api_key_override is None:
            self._provider_cache[provider] = instance
        return instance

    async def _resolve_user_key(self, provider: Provider, user_id: str) -> str | None:
        """Look up a user's BYOK key for the given provider, if any."""
        if provider in (Provider.OLLAMA, Provider.MOCK):
            return None
        try:
            async with get_session_factory()() as session:
                return await get_user_api_key(session, user_id, provider)
        except (SQLAlchemyError, OSError):
            log.debug("BYOK key lookup failed", provider=provider, exc_info=True)
            return None

    async def has_user_key(self, provider: Provider, user_id: str) -> bool:
        """Check if user has a stored BYOK key for the given provider."""
        key = await self._resolve_user_key(provider, user_id)
        return key is not None

    def _get_model(self, provider: Provider, model_override: str | None = None) -> str:
        """Return the configured model name for a provider, or the override if set."""
        if model_override:
            return model_override
        if provider == Provider.OPENAI_COMPATIBLE:
            return self._rc.get_openai_compatible_model() or "unknown"
        cfg = getattr(self.settings.llm, provider.value, None)
        return cfg.model if cfg else "unknown"

    async def _budget_flag_is_set(self, flag_name: str, month_key: tuple[int, int], user_id: str) -> bool:
        """Check whether a budget notification flag is already set.

        Uses Redis when available for cross-replica dedup, falling back
        to the per-process in-memory flag otherwise.
        """
        # Check local cache first (fast path)
        local_flags: dict[str, tuple[int, int]] = getattr(self, flag_name)
        if local_flags.get(user_id) == month_key:
            return True

        redis = await _get_budget_redis()
        if redis is None:
            return False

        redis_key = f"wikimind:budget:{flag_name}:{user_id}:{month_key[0]}:{month_key[1]}"
        try:
            return bool(await redis.exists(redis_key))
        except (RedisError, OSError):
            return False

    async def _set_budget_flag(self, flag_name: str, month_key: tuple[int, int], user_id: str) -> None:
        """Set a budget notification flag in both local memory and Redis.

        The Redis key is set with a TTL of 35 days so it auto-expires
        shortly after the month rolls over.
        """
        local_flags: dict[str, tuple[int, int]] = getattr(self, flag_name)
        local_flags[user_id] = month_key

        redis = await _get_budget_redis()
        if redis is None:
            return

        redis_key = f"wikimind:budget:{flag_name}:{user_id}:{month_key[0]}:{month_key[1]}"
        try:
            await redis.set(redis_key, "1", ex=35 * 86400)  # 35-day TTL
        except (RedisError, OSError):
            log.debug("Failed to set budget flag in Redis", flag=flag_name)

    async def _check_budget(self, user_id: str) -> None:
        """Check monthly budget and emit warnings if thresholds are exceeded."""
        current_month = utcnow_naive()
        month_key = (current_month.year, current_month.month)

        # Reset flags for this user when the calendar month rolls over
        if user_id in self._budget_warning_sent and self._budget_warning_sent[user_id] != month_key:
            del self._budget_warning_sent[user_id]
        if user_id in self._budget_exceeded_sent and self._budget_exceeded_sent[user_id] != month_key:
            del self._budget_exceeded_sent[user_id]

        warning_sent = await self._budget_flag_is_set("_budget_warning_sent", month_key, user_id)
        exceeded_sent = await self._budget_flag_is_set("_budget_exceeded_sent", month_key, user_id)

        if warning_sent and exceeded_sent:
            return

        now = time.time()
        if user_id in self._cached_spend and now < self._cache_expires_at.get(user_id, 0.0):
            spend = self._cached_spend[user_id]
        else:
            start_of_month = current_month.replace(day=1, hour=0, minute=0, second=0)
            async with get_session_factory()() as session:
                stmt = select(func.sum(CostLog.cost_usd)).where(
                    CostLog.created_at >= start_of_month,
                    CostLog.user_id == user_id,
                )
                result = await session.execute(stmt)
                spend = result.scalar() or 0.0
            self._cached_spend[user_id] = spend
            self._cache_expires_at[user_id] = now + self.settings.llm.budget_check_cache_seconds

        budget = self._rc.get_monthly_budget_usd()
        if budget <= 0:
            return
        pct = spend / budget * 100

        if pct >= self.settings.llm.budget_warning_pct * 100 and not warning_sent:
            log.warning(
                "Budget warning threshold reached",
                spend_usd=spend,
                budget_usd=budget,
                pct=round(pct, 1),
            )
            await self._event_emitter.emit_budget_warning(spend, budget, pct, user_id=user_id)
            await self._set_budget_flag("_budget_warning_sent", month_key, user_id)

        if pct >= 100.0 and not exceeded_sent:
            log.error("Budget exceeded", spend_usd=spend, budget_usd=budget)
            await self._event_emitter.emit_budget_exceeded(spend, budget, user_id=user_id)
            await self._set_budget_flag("_budget_exceeded_sent", month_key, user_id)

    async def _log_cost(
        self,
        provider: Provider,
        model: str,
        task_type: TaskType,
        response: CompletionResponse,
        user_id: str,
    ) -> None:
        """Write a CostLog entry in an independent session."""
        cost_entry = CostLog(
            provider=provider,
            model=model,
            task_type=task_type,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=response.cost_usd,
            latency_ms=response.latency_ms,
            user_id=user_id,
        )
        try:
            async with get_session_factory()() as cost_session:
                cost_session.add(cost_entry)
                await cost_session.commit()
        except SQLAlchemyError:
            log.debug("cost log write failed (table may not exist)", exc_info=True)

    async def _log_trace(
        self,
        *,
        model: str,
        task_type: TaskType,
        response: CompletionResponse,
        user_id: str,
        prompt_text: str | None = None,
    ) -> None:
        """Write an LLMTrace entry when tracing is enabled."""
        if not self.settings.llm.trace_enabled:
            return

        store_content = self.settings.llm.trace_store_content
        trace = LLMTrace(
            user_id=user_id,
            model=model,
            prompt_tokens=response.input_tokens,
            completion_tokens=response.output_tokens,
            total_tokens=response.input_tokens + response.output_tokens,
            latency_ms=response.latency_ms,
            prompt_text=prompt_text if store_content else None,
            completion_text=response.content if store_content else None,
            operation=task_type.value,
        )
        try:
            async with get_session_factory()() as trace_session:
                trace_session.add(trace)
                await trace_session.commit()
        except SQLAlchemyError:
            log.debug("trace log write failed (table may not exist)", exc_info=True)

    async def _execute_with_fallback(
        self,
        *,
        preferred_provider: Provider | None,
        user_id: str,
        operation: Callable[[ProviderProtocol, Provider, str], Awaitable[_T]],
        log_label: str,
        disable_fallback: bool = False,
        model_override: str | None = None,
    ) -> _T:
        """Execute an LLM operation with provider selection and fallback.

        This is the shared retry/fallback loop used by :meth:`complete`,
        :meth:`complete_multimodal`, and :meth:`stream_complete`.

        Args:
            preferred_provider: Optional provider preference.
            user_id: User ID for BYOK key lookup.
            operation: An async callable ``(instance, provider, model) -> result``
                that performs the actual provider-specific work.
            log_label: Human-readable label used in log messages
                (e.g. ``"LLM call"``, ``"LLM stream call"``).
            disable_fallback: When True, raise immediately on provider error
                instead of trying the next provider.
            model_override: When set, overrides the configured model name for
                every provider attempted.

        Returns:
            The value returned by *operation* on the first successful provider.

        Raises:
            UpstreamError: When all providers fail.
        """
        provider_order = self._get_provider_order(preferred_provider)

        # Also consider BYOK-capable providers that aren't config-enabled
        # — the user may have stored a key.
        for p in (Provider.ANTHROPIC, Provider.OPENAI, Provider.GOOGLE):
            if p not in provider_order:
                provider_order.append(p)

        last_error = None
        for provider in provider_order:
            user_key = await self._resolve_user_key(provider, user_id)
            if not user_key and not self._is_provider_available(provider):
                continue

            model = self._get_model(provider, model_override)
            try:
                log.info(
                    log_label,
                    provider=provider,
                    model=model,
                    byok=bool(user_key),
                )
                instance = await self._get_provider_instance(provider, api_key_override=user_key)
                return await operation(instance, provider, model)

            except _LLM_PROVIDER_ERRORS as e:
                log.warning(
                    "%s provider failed",
                    log_label,
                    provider=provider,
                    error=str(e),
                )
                last_error = e
                if disable_fallback:
                    msg = f"Provider {provider.value} failed: {e}"
                    raise UpstreamError(msg) from e
                if not self._rc.get_fallback_enabled():
                    raise

        msg = f"All LLM providers failed. Last error: {last_error}"
        raise UpstreamError(msg)

    async def complete(
        self,
        request: CompletionRequest,
        user_id: str,
    ) -> CompletionResponse:
        """Execute LLM completion with provider selection and fallback.

        The router checks for a BYOK key for each candidate provider
        and uses it instead of the system key.
        """

        async def _op(instance: ProviderProtocol, provider: Provider, model: str) -> CompletionResponse:
            response = await instance.complete(request, model)
            await self._log_cost(provider, model, request.task_type, response, user_id=user_id)
            # Build prompt text from messages for trace storage (only when tracing)
            prompt_text: str | None = None
            if self.settings.llm.trace_enabled:
                prompt_text = "\n".join(f"[{m.get('role', 'user')}]: {m.get('content', '')}" for m in request.messages)
                if request.system:
                    prompt_text = f"[system]: {request.system}\n{prompt_text}"
            await self._log_trace(
                model=model,
                task_type=request.task_type,
                response=response,
                user_id=user_id,
                prompt_text=prompt_text,
            )
            log.info(
                "LLM call complete",
                provider=provider,
                cost_usd=response.cost_usd,
                latency_ms=response.latency_ms,
            )

            def _log_budget_error(t: asyncio.Task) -> None:
                if not t.cancelled():
                    exc = t.exception()
                    if exc:
                        log.warning("budget check failed", error=str(exc))

            task = asyncio.create_task(self._check_budget(user_id=user_id))
            task.add_done_callback(_log_budget_error)
            return response

        return await self._execute_with_fallback(
            preferred_provider=request.preferred_provider,
            user_id=user_id,
            operation=_op,
            log_label="LLM call",
            disable_fallback=request.disable_fallback,
            model_override=request.model_override,
        )

    async def complete_multimodal(
        self,
        system: str,
        content_parts: list[dict[str, Any]],
        user_id: str,
        task_type: TaskType = TaskType.INGEST,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        preferred_provider: Provider | None = None,
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
            user_id: User ID for BYOK key lookup.

        Returns:
            CompletionResponse with the LLM's text output.

        Raises:
            UpstreamError: When all providers fail.
        """

        async def _op(instance: ProviderProtocol, provider: Provider, model: str) -> CompletionResponse:
            response = await instance.complete_multimodal(
                system=system,
                content_parts=content_parts,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            await self._log_cost(provider, model, task_type, response, user_id=user_id)
            prompt_text: str | None = None
            if self.settings.llm.trace_enabled:
                prompt_text = f"[system]: {system}\n[multimodal: {len(content_parts)} parts]"
            await self._log_trace(
                model=model,
                task_type=task_type,
                response=response,
                user_id=user_id,
                prompt_text=prompt_text,
            )
            log.info(
                "LLM multimodal call complete",
                provider=provider,
                cost_usd=response.cost_usd,
                latency_ms=response.latency_ms,
            )
            return response

        return await self._execute_with_fallback(
            preferred_provider=preferred_provider,
            user_id=user_id,
            operation=_op,
            log_label="LLM multimodal call",
        )

    async def stream_complete(
        self,
        request: CompletionRequest,
        user_id: str,
    ) -> StreamSession:
        """Create a streaming LLM completion with provider fallback.

        Fallback happens during stream creation only. Once tokens begin
        flowing, no mid-stream provider switch occurs -- errors surface
        as exceptions from the async iterator.

        Args:
            request: The completion request.
            user_id: User ID for BYOK key lookup.

        Returns:
            A :class:`StreamSession` that yields text chunks.

        Raises:
            UpstreamError: When all providers fail during stream creation.
        """

        async def _op(instance: ProviderProtocol, _provider: Provider, model: str) -> StreamSession:
            return await instance.stream(request, model)

        return await self._execute_with_fallback(
            preferred_provider=request.preferred_provider,
            user_id=user_id,
            operation=_op,
            log_label="LLM stream call",
        )

    def parse_json_response(self, response: CompletionResponse) -> Any:
        """Parse JSON from LLM response, handling common formatting issues.

        Handles markdown fences, leading/trailing text around JSON, and
        invalid control characters that local models (e.g. Ollama) may
        emit inside string values.
        """
        content = response.content.strip()

        # Strip markdown code fences (```json ... ```)
        if content.startswith("```"):
            lines = content.split("\n")
            body_lines = lines[1:]
            for i, line in enumerate(body_lines):
                if line.strip() == "```":
                    content = "\n".join(body_lines[:i])
                    break

        # Try strict parse first (fast path for well-behaved providers)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # Extract the outermost JSON object if there is surrounding text
        first_brace = content.find("{")
        last_brace = content.rfind("}")
        if first_brace != -1 and last_brace > first_brace:
            extracted = content[first_brace : last_brace + 1]
            try:
                return json.loads(extracted)
            except json.JSONDecodeError:
                # Sanitize control characters inside string values and retry.
                # Local models sometimes emit raw \n, \t, or other C0 control
                # chars inside JSON strings which are illegal per RFC 8259.
                sanitized = _sanitize_json_control_chars(extracted)
                return json.loads(sanitized)

        # Nothing recoverable — re-raise with the original content
        return json.loads(content)


_llm_router_instance: LLMRouter | None = None


def get_llm_router() -> LLMRouter:
    """Return the singleton LLM router."""
    global _llm_router_instance
    if _llm_router_instance is None:
        _llm_router_instance = LLMRouter()
    return _llm_router_instance


def configure_llm_router(*, event_emitter: BudgetEventEmitter) -> LLMRouter:
    """Create and cache the LLM router with an injected event emitter.

    Called once at app startup to wire the concrete emitter implementation.
    Must be called before the first ``get_llm_router()`` call for the
    emitter to take effect.
    """
    global _llm_router_instance
    _llm_router_instance = LLMRouter(event_emitter=event_emitter)
    return _llm_router_instance
