"""E2E test fixtures — shared helpers for full-pipeline tests."""

from __future__ import annotations

import json

from wikimind.models import CompletionResponse, Provider

# ---------------------------------------------------------------------------
# Canned LLM response — returned by the mocked router for every compile call
# ---------------------------------------------------------------------------

CANNED_COMPILATION = {
    "title": "Test Compiled Article",
    "summary": "A comprehensive test article. It covers the key points.",
    "key_claims": [
        {"claim": "This is a verified claim from the source.", "confidence": "sourced"},
    ],
    "concepts": ["test-concept"],
    "backlink_suggestions": [],
    "open_questions": ["What else could be explored?"],
    "article_body": (
        "## Overview\n\n"
        "This article was compiled from the ingested source material. "
        "It summarises the key points and provides a structured overview.\n\n"
        "## Details\n\n"
        "The source material covers important topics that are relevant "
        "to the knowledge base. Multiple aspects are discussed in depth."
    ),
}


def make_fake_completion(data: dict | None = None) -> CompletionResponse:
    """Build a CompletionResponse wrapping the given dict as JSON content."""
    payload = data or CANNED_COMPILATION
    return CompletionResponse(
        content=json.dumps(payload),
        provider_used=Provider.ANTHROPIC,
        model_used="test-model",
        input_tokens=100,
        output_tokens=200,
        cost_usd=0.001,
        latency_ms=50,
    )
