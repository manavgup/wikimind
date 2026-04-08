"""WikiMind LLM Router.

Single interface for all LLM providers.
Handles selection, fallback, cost tracking, and token budgeting.
"""

from __future__ import annotations

import json
import time

import anthropic
import ollama
import openai
import structlog

from wikimind.config import get_api_key, get_settings
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
        elif provider == Provider.OLLAMA:
            return OllamaProvider(self.settings.llm.ollama_base_url)
        elif provider == Provider.MOCK:
            return MockProvider()
        else:
            raise ValueError(f"Provider {provider} not implemented yet")

    def _get_model(self, provider: Provider) -> str:
        cfg = getattr(self.settings.llm, provider.value, None)
        return cfg.model if cfg else "unknown"

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
                return response

            except Exception as e:
                log.warning("LLM provider failed", provider=provider, error=str(e))
                last_error = e
                if not self.settings.llm.fallback_enabled:
                    raise

        raise RuntimeError(f"All LLM providers failed. Last error: {last_error}")

    def parse_json_response(self, response: CompletionResponse) -> dict:
        """Parse JSON from LLM response, stripping markdown fences if present."""
        content = response.content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])
        return json.loads(content)


# Singleton
_router: LLMRouter | None = None


def get_llm_router() -> LLMRouter:
    """Return the singleton LLM router."""
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router
