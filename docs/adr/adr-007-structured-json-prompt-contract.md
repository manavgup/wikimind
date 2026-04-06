# ADR-007: Structured JSON prompt contract

## Status

Accepted

## Context

The WikiMind compiler transforms raw sources into wiki articles via LLM calls.
The LLM output must be programmatically parsed to extract structured data:
title, summary, key claims with confidence tags, concepts, backlink suggestions,
open questions, and the full article body. The output format directly determines
whether downstream code can reliably process the result.

Free-form markdown output would require fragile regex parsing, would vary between
LLM providers, and would make it impossible to enforce schema requirements like
the confidence classification on every claim.

## Decision

All LLM compilation output follows a **strict JSON schema** defined in the system
prompt (`COMPILER_SYSTEM_PROMPT` in `engine/compiler.py`). The schema matches
the `CompilationResult` Pydantic model exactly:

```json
{
  "title": "string",
  "summary": "string",
  "key_claims": [{"claim": "string", "confidence": "sourced|inferred|opinion", "quote": "string|null"}],
  "concepts": ["string"],
  "backlink_suggestions": ["string"],
  "open_questions": ["string"],
  "article_body": "string (markdown)"
}
```

The system prompt explicitly instructs: "You MUST respond with valid JSON only.
No preamble, no markdown fences." The `response_format="json"` field in
`CompletionRequest` enables provider-native JSON mode where available (OpenAI's
`response_format: {type: json_object}`). The router's `parse_json_response`
method handles edge cases like markdown fences wrapping the JSON.

The response is parsed via `CompilationResult(**data)`, which validates the
schema using Pydantic. Invalid responses are caught and logged.

## Alternatives Considered

**Free-form markdown with parsing** -- Let the LLM output a markdown article
and parse structure from headings and conventions. Brittle, provider-dependent,
and cannot enforce claim-level confidence tags. Would require maintaining
complex parsing logic that breaks when the LLM varies its output format.

**XML output** -- More verbose than JSON, no native provider support for XML
mode, and adds parsing complexity without benefit. JSON is the lingua franca
of structured LLM output.

**Function calling / tool use** -- Anthropic and OpenAI support structured
output via tool definitions. More reliable than raw JSON prompting but locks
us into provider-specific APIs, complicating the multi-provider router
(ADR-003). JSON prompting works across all providers including Ollama.

**Multiple sequential calls** -- First call extracts claims, second generates
article body, third suggests backlinks. More reliable per-step but multiplies
cost and latency by 3x. A single call with a clear schema works well enough.

## Consequences

**Enables:**
- Deterministic parsing: `CompilationResult(**json.loads(response))` always works
  or fails cleanly
- Schema validation via Pydantic catches malformed output before it reaches the
  database
- Consistent output across providers (Anthropic, OpenAI, Ollama)
- The confidence classification (ADR-005) is enforced structurally, not by
  convention

**Constrains:**
- The `article_body` field contains markdown as a JSON string, which means
  newlines and quotes must be escaped. This occasionally causes parse failures
  with less capable models.
- Schema changes require updating both the prompt and the Pydantic model

**Risks:**
- Smaller/local models (Ollama) may struggle to produce valid JSON consistently.
  Mitigated by the `parse_json_response` fallback that strips markdown fences,
  and by the fallback mechanism in ADR-003 which can retry with a more capable
  provider.
