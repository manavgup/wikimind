"""Deterministic mock LLM provider for CI e2e testing."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

from wikimind.engine.llm_router import StreamSession
from wikimind.models import CompletionRequest, CompletionResponse, Provider, TaskType


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
