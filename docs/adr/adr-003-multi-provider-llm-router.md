# ADR-003: Multi-provider LLM router with fallback

## Status

Accepted

## Context

WikiMind depends heavily on LLM API calls for compilation, Q&A, linting, and
indexing. No single provider is always the best choice: providers have outages,
pricing changes, rate limits, and different quality/cost trade-offs. Users also
have strong preferences -- some want to use only Anthropic, others want local
models via Ollama for privacy.

We need a unified interface that lets the rest of the codebase call "the LLM"
without knowing which provider is behind it, while supporting automatic failover,
cost tracking per call, and budget enforcement.

## Decision

We built an **LLMRouter** class (`src/wikimind/engine/llm_router.py`) that
provides a single `complete()` method. The router:

1. **Selects a provider** using a priority order: preferred provider (per-request)
   then default provider (from settings), then any remaining enabled provider.
2. **Falls back automatically** when a provider fails and `fallback_enabled=True`.
3. **Tracks cost per call** by computing USD cost from a pricing table
   (per-model input/output token rates) and writing a `CostLog` entry to SQLite.
4. **Exposes provider-specific classes** (`AnthropicProvider`, `OpenAIProvider`,
   `OllamaProvider`) that implement a common `complete(request, model)` interface.

Each `CompletionResponse` includes `provider_used`, `model_used`, `input_tokens`,
`output_tokens`, `cost_usd`, and `latency_ms` so callers always know what happened.

Supported providers: Anthropic (Claude), OpenAI (GPT-4o), Google (Gemini), and
Ollama (local models, zero cost).

## Alternatives Considered

**LiteLLM** -- Popular multi-provider proxy that supports 100+ models. However,
it adds a significant dependency, runs its own proxy process, and we need tighter
control over cost tracking and fallback logic. LiteLLM also abstracts away token
counts in ways that make per-call cost logging harder.

**LangChain** -- Provides LLM abstractions but brings a large dependency tree,
frequent breaking changes, and abstractions that do not align with our simple
request/response model. We only need completion calls, not chains or agents.

**Direct SDK calls everywhere** -- Simplest approach but scatters provider logic
across the codebase, makes fallback impossible, and requires duplicating cost
tracking in every call site.

## Consequences

**Enables:**
- Users can switch providers via a single config change (`llm.default_provider`)
- Automatic failover when a provider has an outage
- Per-call cost tracking in the `costlog` table for budget monitoring
- Ollama support gives users a fully offline, zero-API-cost option
- Monthly budget enforcement (`monthly_budget_usd`) prevents runaway costs

**Constrains:**
- New providers require a new class implementing the `complete()` interface and
  an entry in the `PRICING` dictionary
- Pricing must be manually updated when providers change rates

**Risks:**
- Fallback to a cheaper/weaker model may produce lower-quality compilation;
  mitigated by letting users disable fallback or pin a specific provider
