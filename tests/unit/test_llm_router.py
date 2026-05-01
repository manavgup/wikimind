"""Tests for the LLM router and provider implementations."""

from __future__ import annotations

import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from tests.conftest import TEST_USER_ID
from wikimind.engine import llm_router as llm_router_mod
from wikimind.engine.llm_router import (
    _MOCK_COMPILE_RESPONSE,
    _MOCK_LINT_RESPONSE,
    _MOCK_QA_RESPONSE,
    AnthropicProvider,
    LLMRouter,
    MockProvider,
    OllamaProvider,
    OpenAIProvider,
    _sanitize_json_control_chars,
    get_llm_router,
)
from wikimind.engine.provider_base import StreamSession, _calc_cost
from wikimind.engine.providers import anthropic as anthropic_provider_mod
from wikimind.engine.providers import ollama as ollama_provider_mod
from wikimind.engine.providers import openai_compatible as openai_compatible_provider_mod
from wikimind.engine.providers.openai_compatible import OpenAICompatibleProvider
from wikimind.models import (
    CompilationResult,
    CompletionRequest,
    CompletionResponse,
    Provider,
    QueryResult,
    TaskType,
)


def _req(**kw) -> CompletionRequest:
    base = {
        "system": "sys",
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 64,
        "task_type": TaskType.QA,
    }
    base.update(kw)
    return CompletionRequest(**base)


def test_sanitize_json_control_chars_newlines() -> None:
    """Bare newlines inside JSON strings are escaped so json.loads succeeds."""
    raw = '{"text": "line1\nline2"}'
    result = _sanitize_json_control_chars(raw)
    parsed = json.loads(result)
    assert parsed["text"] == "line1\nline2"


def test_sanitize_json_control_chars_tabs() -> None:
    """Bare tabs inside JSON strings are escaped so json.loads succeeds."""
    raw = '{"text": "col1\tcol2"}'
    result = _sanitize_json_control_chars(raw)
    parsed = json.loads(result)
    assert parsed["text"] == "col1\tcol2"


def test_sanitize_json_control_chars_preserves_structural_whitespace() -> None:
    """Newlines between JSON keys/values (structural whitespace) are preserved."""
    raw = '{\n  "a": "1",\n  "b": "2"\n}'
    result = _sanitize_json_control_chars(raw)
    assert json.loads(result) == {"a": "1", "b": "2"}


def test_sanitize_json_control_chars_mixed() -> None:
    """Mix of structural whitespace and control chars inside strings."""
    raw = '{\n  "title": "Hello\nWorld",\n  "body": "Tab\there"\n}'
    result = _sanitize_json_control_chars(raw)
    parsed = json.loads(result)
    assert parsed["title"] == "Hello\nWorld"
    assert parsed["body"] == "Tab\there"


def test_calc_cost_known_model() -> None:
    cost = _calc_cost(Provider.ANTHROPIC, "claude-sonnet-4-5", 1_000_000, 1_000_000)
    assert cost == pytest.approx(18.0)


def test_calc_cost_unknown_model_falls_back_to_zero() -> None:
    assert _calc_cost(Provider.ANTHROPIC, "no-such", 100, 100) == 0


def test_calc_cost_ollama_wildcard() -> None:
    assert _calc_cost(Provider.OLLAMA, "llama3", 1000, 1000) == 0


def test_providers_package_imports_without_router_cycle() -> None:
    """Provider modules should be importable without re-entering the router."""
    providers = importlib.import_module("wikimind.engine.providers")
    compatible = importlib.import_module("wikimind.engine.providers.openai_compatible")

    assert providers.OpenAICompatibleProvider is compatible.OpenAICompatibleProvider


def test_anthropic_provider_missing_key() -> None:
    with patch.object(anthropic_provider_mod, "get_api_key", return_value=None), pytest.raises(ValueError):
        AnthropicProvider()


async def test_anthropic_provider_complete() -> None:
    fake_response = SimpleNamespace(
        content=[SimpleNamespace(text="hello")],
        usage=SimpleNamespace(input_tokens=10, output_tokens=20),
    )
    fake_client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=fake_response)))
    with (
        patch.object(anthropic_provider_mod, "get_api_key", return_value="key"),
        patch.object(anthropic_provider_mod.anthropic, "AsyncAnthropic", return_value=fake_client),
    ):
        provider = AnthropicProvider()
        resp = await provider.complete(_req(), "claude-sonnet-4-5")
    assert isinstance(resp, CompletionResponse)
    assert resp.content == "hello"
    assert resp.input_tokens == 10
    assert resp.output_tokens == 20
    assert resp.provider_used == Provider.ANTHROPIC


def test_openai_provider_missing_key() -> None:
    with patch.object(openai_compatible_provider_mod, "get_api_key", return_value=None), pytest.raises(ValueError):
        OpenAIProvider()


async def test_openai_provider_complete_json() -> None:
    fake_choice = SimpleNamespace(message=SimpleNamespace(content="ok"))
    fake_response = SimpleNamespace(
        choices=[fake_choice],
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=7),
    )
    create = AsyncMock(return_value=fake_response)
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with (
        patch.object(openai_compatible_provider_mod, "get_api_key", return_value="key"),
        patch.object(openai_compatible_provider_mod.openai, "AsyncOpenAI", return_value=fake_client),
    ):
        provider = OpenAIProvider()
        resp = await provider.complete(_req(response_format="json"), "gpt-4o-mini")
    assert resp.content == "ok"
    assert resp.input_tokens == 5
    assert resp.provider_used == Provider.OPENAI
    kwargs = create.call_args.kwargs
    assert kwargs["response_format"] == {"type": "json_object"}


async def test_openai_compatible_provider_uses_custom_endpoint_and_flags() -> None:
    fake_choice = SimpleNamespace(message=SimpleNamespace(content="ok"))
    fake_response = SimpleNamespace(
        choices=[fake_choice],
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=7),
    )
    create = AsyncMock(return_value=fake_response)
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    headers = {"X-Title": "WikiMind"}
    with (
        patch.object(openai_compatible_provider_mod, "get_api_key", return_value="key"),
        patch.object(openai_compatible_provider_mod.openai, "AsyncOpenAI", return_value=fake_client) as client_cls,
    ):
        provider = OpenAICompatibleProvider(
            provider=Provider.OPENAI_COMPATIBLE,
            api_key_name="openai_compatible",
            base_url="https://openrouter.ai/api/v1",
            default_headers=headers,
            supports_json_response_format=False,
            supports_stream_usage=False,
            max_tokens_field="max_completion_tokens",
        )
        resp = await provider.complete(_req(response_format="json"), "openai/gpt-4o-mini")

    assert resp.content == "ok"
    assert resp.provider_used == Provider.OPENAI_COMPATIBLE
    client_cls.assert_called_once_with(
        api_key="key",
        base_url="https://openrouter.ai/api/v1",
        default_headers=headers,
    )
    kwargs = create.call_args.kwargs
    assert kwargs["max_completion_tokens"] == 64
    assert "max_tokens" not in kwargs
    assert "response_format" not in kwargs


def test_openai_compatible_default_headers_use_openrouter_title() -> None:
    headers = openai_compatible_provider_mod.ConfiguredOpenAICompatibleProvider._default_headers(
        site_url="https://wikimind.example",
        app_name="WikiMind",
    )

    assert headers == {
        "HTTP-Referer": "https://wikimind.example",
        "X-Title": "WikiMind",
    }
    assert "X-OpenRouter-Title" not in headers


async def test_openai_compatible_provider_sends_openrouter_reasoning() -> None:
    fake_choice = SimpleNamespace(message=SimpleNamespace(content="ok"))
    fake_response = SimpleNamespace(
        choices=[fake_choice],
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=7),
    )
    create = AsyncMock(return_value=fake_response)
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with (
        patch.object(openai_compatible_provider_mod, "get_api_key", return_value="key"),
        patch.object(openai_compatible_provider_mod.openai, "AsyncOpenAI", return_value=fake_client),
    ):
        provider = OpenAICompatibleProvider(
            provider=Provider.OPENAI_COMPATIBLE,
            api_key_name="openai_compatible",
            base_url="https://openrouter.ai/api/v1",
            reasoning_format="openrouter",
        )
        await provider.complete(_req(reasoning_effort="high"), "anthropic/claude-3.7-sonnet:thinking")

    kwargs = create.call_args.kwargs
    assert kwargs["extra_body"] == {"reasoning": {"effort": "high"}}
    assert "reasoning" not in kwargs
    assert "reasoning_effort" not in kwargs


async def test_openai_compatible_provider_sends_openai_reasoning_effort() -> None:
    fake_choice = SimpleNamespace(message=SimpleNamespace(content="ok"))
    fake_response = SimpleNamespace(
        choices=[fake_choice],
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=7),
    )
    create = AsyncMock(return_value=fake_response)
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with (
        patch.object(openai_compatible_provider_mod, "get_api_key", return_value="key"),
        patch.object(openai_compatible_provider_mod.openai, "AsyncOpenAI", return_value=fake_client),
    ):
        provider = OpenAICompatibleProvider(
            provider=Provider.OPENAI_COMPATIBLE,
            api_key_name="openai_compatible",
            base_url="https://example.com/v1",
            reasoning_format="openai",
        )
        await provider.complete(_req(reasoning_effort="medium"), "gpt-5")

    kwargs = create.call_args.kwargs
    assert kwargs["reasoning_effort"] == "medium"
    assert "reasoning" not in kwargs
    assert "extra_body" not in kwargs


async def test_openai_compatible_provider_omits_reasoning_when_disabled_or_unset() -> None:
    fake_choice = SimpleNamespace(message=SimpleNamespace(content="ok"))
    fake_response = SimpleNamespace(
        choices=[fake_choice],
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=7),
    )
    create = AsyncMock(return_value=fake_response)
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with (
        patch.object(openai_compatible_provider_mod, "get_api_key", return_value="key"),
        patch.object(openai_compatible_provider_mod.openai, "AsyncOpenAI", return_value=fake_client),
    ):
        provider = OpenAICompatibleProvider(
            provider=Provider.OPENAI_COMPATIBLE,
            api_key_name="openai_compatible",
            base_url="https://example.com/v1",
            supports_reasoning_effort=False,
            reasoning_format="openrouter",
        )
        await provider.complete(_req(reasoning_effort="high"), "non-reasoning-model")
        await provider.complete(_req(), "non-reasoning-model")

    for call in create.call_args_list:
        kwargs = call.kwargs
        assert "reasoning" not in kwargs
        assert "reasoning_effort" not in kwargs
        assert "extra_body" not in kwargs


async def test_ollama_provider_complete() -> None:
    fake_client = SimpleNamespace(chat=AsyncMock(return_value={"message": {"content": "hi"}}))
    with patch.object(ollama_provider_mod.ollama, "AsyncClient", return_value=fake_client):
        provider = OllamaProvider("http://localhost")
        resp = await provider.complete(_req(), "llama3")
    assert resp.content == "hi"
    assert resp.cost_usd == 0.0
    assert resp.provider_used == Provider.OLLAMA


async def test_ollama_provider_passes_json_format() -> None:
    """Ollama provider should pass format='json' when response_format is json."""
    fake_client = SimpleNamespace(chat=AsyncMock(return_value={"message": {"content": '{"a":1}'}}))
    with patch.object(ollama_provider_mod.ollama, "AsyncClient", return_value=fake_client):
        provider = OllamaProvider("http://localhost")
        req = _req(response_format="json")
        await provider.complete(req, "llama3")
    call_kwargs = fake_client.chat.call_args.kwargs
    assert call_kwargs["format"] == "json"


async def test_ollama_provider_no_format_for_text() -> None:
    """Ollama provider should not pass format when response_format is text."""
    fake_client = SimpleNamespace(chat=AsyncMock(return_value={"message": {"content": "hello"}}))
    with patch.object(ollama_provider_mod.ollama, "AsyncClient", return_value=fake_client):
        provider = OllamaProvider("http://localhost")
        req = _req(response_format="text")
        await provider.complete(req, "llama3")
    call_kwargs = fake_client.chat.call_args.kwargs
    assert "format" not in call_kwargs


def _router_with_settings(default="anthropic", **provider_overrides):
    cfgs = {
        "anthropic": SimpleNamespace(enabled=True, model="claude-sonnet-4-5"),
        "openai": SimpleNamespace(enabled=True, model="gpt-4o-mini"),
        "openai_compatible": SimpleNamespace(enabled=False, model="gpt-4o-mini", base_url=""),
        "google": SimpleNamespace(enabled=False, model="gemini-2.0-flash"),
        "ollama": SimpleNamespace(enabled=True, model="llama3"),
    }
    cfgs.update(provider_overrides)
    llm_settings = SimpleNamespace(
        default_provider=default,
        fallback_enabled=True,
        ollama_base_url="http://localhost:11434",
        **cfgs,
    )
    settings = SimpleNamespace(llm=llm_settings)
    with patch.object(llm_router_mod, "get_settings", return_value=settings):
        return LLMRouter()


def test_get_provider_order_includes_preferred_default_and_fallbacks() -> None:
    router = _router_with_settings()
    order = router._get_provider_order(Provider.OPENAI)
    assert order[0] == Provider.OPENAI
    assert Provider.ANTHROPIC in order
    assert Provider.OLLAMA in order
    # google disabled — not present
    assert Provider.GOOGLE not in order


def test_get_provider_order_no_preferred() -> None:
    router = _router_with_settings(default="openai")
    order = router._get_provider_order(None)
    assert order[0] == Provider.OPENAI


def test_is_provider_available_true_when_key_present() -> None:
    router = _router_with_settings()
    with patch.object(llm_router_mod, "get_api_key", return_value="key"):
        assert router._is_provider_available(Provider.ANTHROPIC) is True


def test_is_provider_available_false_when_disabled() -> None:
    router = _router_with_settings(anthropic=SimpleNamespace(enabled=False, model="x"))
    assert router._is_provider_available(Provider.ANTHROPIC) is False


def test_is_provider_available_ollama_no_key_needed() -> None:
    router = _router_with_settings()
    assert router._is_provider_available(Provider.OLLAMA) is True


def test_is_provider_available_openai_compatible_requires_key_and_base_url() -> None:
    router = _router_with_settings(
        openai_compatible=SimpleNamespace(
            enabled=True,
            model="openai/gpt-4o-mini",
            base_url="https://openrouter.ai/api/v1",
        ),
    )
    with patch.object(llm_router_mod, "get_api_key", return_value="key"):
        assert router._is_provider_available(Provider.OPENAI_COMPATIBLE) is True

    router = _router_with_settings(
        openai_compatible=SimpleNamespace(enabled=True, model="openai/gpt-4o-mini", base_url="")
    )
    with patch.object(llm_router_mod, "get_api_key", return_value="key"):
        assert router._is_provider_available(Provider.OPENAI_COMPATIBLE) is False


def test_get_model_returns_unknown_for_missing_cfg() -> None:
    router = _router_with_settings()
    # Force an unknown attribute by removing a provider attribute
    router.settings.llm.openai = None
    assert router._get_model(Provider.OPENAI) == "unknown"


async def test_get_provider_instance_dispatch() -> None:
    router = _router_with_settings()
    with (
        patch.object(llm_router_mod, "get_api_key", return_value="k"),
        patch.object(llm_router_mod, "AnthropicProvider") as ant,
        patch.object(llm_router_mod, "OpenAIProvider") as opn,
        patch.object(llm_router_mod, "ConfiguredOpenAICompatibleProvider") as opc,
        patch.object(llm_router_mod, "GoogleProvider") as ggl,
        patch.object(llm_router_mod, "OllamaProvider") as oll,
    ):
        ant.return_value = "a"
        opn.return_value = "o"
        opc.return_value = "oc"
        ggl.return_value = "g"
        oll.return_value = "l"
        assert await router._get_provider_instance(Provider.ANTHROPIC) == "a"
        assert await router._get_provider_instance(Provider.OPENAI) == "o"
        assert await router._get_provider_instance(Provider.OPENAI_COMPATIBLE) == "oc"
        assert await router._get_provider_instance(Provider.GOOGLE) == "g"
        assert await router._get_provider_instance(Provider.OLLAMA) == "l"


async def test_router_complete_success(db_session) -> None:
    router = _router_with_settings()
    fake_resp = CompletionResponse(
        content="ok",
        provider_used=Provider.ANTHROPIC,
        model_used="claude-sonnet-4-5",
        input_tokens=1,
        output_tokens=2,
        cost_usd=0.01,
        latency_ms=10,
    )
    instance = SimpleNamespace(complete=AsyncMock(return_value=fake_resp))
    with (
        patch.object(router, "_is_provider_available", return_value=True),
        patch.object(router, "_get_provider_instance", AsyncMock(return_value=instance)),
    ):
        resp = await router.complete(_req(), user_id=TEST_USER_ID)
    assert resp.content == "ok"


async def test_router_complete_falls_through_to_next_provider() -> None:
    router = _router_with_settings()
    fake_resp = CompletionResponse(
        content="ok",
        provider_used=Provider.OPENAI,
        model_used="gpt-4o-mini",
        input_tokens=1,
        output_tokens=2,
        cost_usd=0.0,
        latency_ms=5,
    )
    bad = SimpleNamespace(complete=AsyncMock(side_effect=RuntimeError("boom")))
    good = SimpleNamespace(complete=AsyncMock(return_value=fake_resp))

    instances = [bad, good]

    async def get_instance(_p, **_kw):
        return instances.pop(0)

    with (
        patch.object(router, "_is_provider_available", return_value=True),
        patch.object(router, "_get_provider_instance", side_effect=get_instance),
    ):
        resp = await router.complete(_req(), user_id=TEST_USER_ID)
    assert resp.content == "ok"


async def test_router_complete_no_fallback_raises() -> None:
    router = _router_with_settings()
    router.settings.llm.fallback_enabled = False
    bad = SimpleNamespace(complete=AsyncMock(side_effect=RuntimeError("boom")))
    with (
        patch.object(router, "_is_provider_available", return_value=True),
        patch.object(router, "_get_provider_instance", AsyncMock(return_value=bad)),
        pytest.raises(RuntimeError),
    ):
        await router.complete(_req(), user_id=TEST_USER_ID)


async def test_router_complete_skips_unavailable_providers() -> None:
    router = _router_with_settings()
    with patch.object(router, "_is_provider_available", return_value=False), pytest.raises(RuntimeError):
        await router.complete(_req(), user_id=TEST_USER_ID)


def test_parse_json_response_strips_fences() -> None:
    router = _router_with_settings()
    resp = CompletionResponse(
        content='```json\n{"a": 1}\n```',
        provider_used=Provider.OPENAI,
        model_used="x",
        input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
        latency_ms=0,
    )
    assert router.parse_json_response(resp) == {"a": 1}


def test_parse_json_response_plain() -> None:
    router = _router_with_settings()
    resp = CompletionResponse(
        content='{"b": 2}',
        provider_used=Provider.OPENAI,
        model_used="x",
        input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
        latency_ms=0,
    )
    assert router.parse_json_response(resp) == {"b": 2}


def test_parse_json_response_surrounding_text() -> None:
    """Ollama models sometimes emit text before/after the JSON object."""
    router = _router_with_settings()
    resp = CompletionResponse(
        content='Here is the JSON:\n{"title": "Test"}\nDone!',
        provider_used=Provider.OLLAMA,
        model_used="llama3",
        input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
        latency_ms=0,
    )
    assert router.parse_json_response(resp) == {"title": "Test"}


def test_parse_json_response_control_chars_in_strings() -> None:
    """Ollama models may emit raw control characters inside JSON string values."""
    router = _router_with_settings()
    # Simulate a JSON string with a literal newline inside a value
    raw = '{"title": "Test\nDocument", "summary": "Line1\tLine2"}'
    resp = CompletionResponse(
        content=raw,
        provider_used=Provider.OLLAMA,
        model_used="llama3",
        input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
        latency_ms=0,
    )
    result = router.parse_json_response(resp)
    assert result["title"] == "Test\nDocument"
    assert result["summary"] == "Line1\tLine2"


def test_parse_json_response_control_chars_with_surrounding_text() -> None:
    """Combined: surrounding text AND control characters inside strings."""
    router = _router_with_settings()
    raw = 'Sure, here is the JSON:\n{"claim": "value\nwith newline"}\nEnd.'
    resp = CompletionResponse(
        content=raw,
        provider_used=Provider.OLLAMA,
        model_used="llama3",
        input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
        latency_ms=0,
    )
    result = router.parse_json_response(resp)
    assert result["claim"] == "value\nwith newline"


def test_parse_json_response_fences_with_language_tag() -> None:
    """Markdown fences with ```json tag should be handled."""
    router = _router_with_settings()
    resp = CompletionResponse(
        content='```json\n{"key": "value"}\n```\n',
        provider_used=Provider.OLLAMA,
        model_used="llama3",
        input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
        latency_ms=0,
    )
    assert router.parse_json_response(resp) == {"key": "value"}


def test_parse_json_response_nested_objects() -> None:
    """Ensure nested JSON objects parse correctly even with surrounding text."""
    router = _router_with_settings()
    nested = '{"title": "Test", "claims": [{"claim": "A", "confidence": "sourced"}]}'
    resp = CompletionResponse(
        content=f"Output:\n{nested}\n",
        provider_used=Provider.OLLAMA,
        model_used="llama3",
        input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
        latency_ms=0,
    )
    result = router.parse_json_response(resp)
    assert result["title"] == "Test"
    assert len(result["claims"]) == 1


def test_parse_json_response_invalid_json_raises() -> None:
    """Totally invalid content should still raise JSONDecodeError."""
    router = _router_with_settings()
    resp = CompletionResponse(
        content="This is not JSON at all",
        provider_used=Provider.OLLAMA,
        model_used="llama3",
        input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
        latency_ms=0,
    )
    with pytest.raises(json.JSONDecodeError):
        router.parse_json_response(resp)


def test_get_llm_router_singleton() -> None:
    llm_router_mod._router = None
    with patch.object(
        llm_router_mod, "get_settings", return_value=SimpleNamespace(llm=SimpleNamespace(default_provider="anthropic"))
    ):
        r1 = get_llm_router()
        r2 = get_llm_router()
    assert r1 is r2
    llm_router_mod._router = None


class TestMockProvider:
    """MockProvider returns canned JSON matching each task's Pydantic contract."""

    @pytest.mark.asyncio
    async def test_compile_response_parses_into_compilation_result(self) -> None:
        provider = MockProvider()
        request = CompletionRequest(
            system="system",
            messages=[{"role": "user", "content": "compile this source"}],
            max_tokens=2048,
            temperature=0.3,
            response_format="json",
            task_type=TaskType.COMPILE,
        )

        response = await provider.complete(request, model="mock-1")

        assert response.provider_used == Provider.MOCK
        assert response.cost_usd == 0.0
        assert response.input_tokens == 0
        assert response.output_tokens == 0

        data = json.loads(response.content)
        assert data == _MOCK_COMPILE_RESPONSE
        result = CompilationResult(**data)
        assert result.title == "Mock Article"
        assert len(result.key_claims) >= 1

    @pytest.mark.asyncio
    async def test_qa_response_parses_into_query_result(self) -> None:
        provider = MockProvider()
        request = CompletionRequest(
            system="system",
            messages=[{"role": "user", "content": "what is mocking?"}],
            max_tokens=2048,
            temperature=0.3,
            response_format="json",
            task_type=TaskType.QA,
        )

        response = await provider.complete(request, model="mock-1")

        assert response.provider_used == Provider.MOCK
        data = json.loads(response.content)
        assert data == _MOCK_QA_RESPONSE
        result = QueryResult(**data)
        assert result.confidence == "high"
        assert "mock" in result.answer.lower()

    @pytest.mark.asyncio
    async def test_lint_response_is_valid_json(self) -> None:
        provider = MockProvider()
        request = CompletionRequest(
            system="system",
            messages=[{"role": "user", "content": "lint the wiki"}],
            max_tokens=2048,
            temperature=0.3,
            response_format="json",
            task_type=TaskType.LINT,
        )

        response = await provider.complete(request, model="mock-1")

        data = json.loads(response.content)
        assert data == _MOCK_LINT_RESPONSE
        assert "contradictions" in data
        assert data["contradictions"] == []


# ---------------------------------------------------------------------------
# StreamSession tests
# ---------------------------------------------------------------------------


async def test_stream_session_aiter_yields_chunks() -> None:
    """StreamSession yields chunks from the underlying async iterator."""

    async def _gen():
        yield "hello "
        yield "world"

    session = StreamSession(_chunks=_gen())
    chunks = [chunk async for chunk in session]
    assert chunks == ["hello ", "world"]


async def test_stream_session_result_starts_none() -> None:
    """StreamSession.result is None before iteration."""

    async def _gen():
        yield "x"

    session = StreamSession(_chunks=_gen())
    assert session.result is None


# ---------------------------------------------------------------------------
# Provider stream() tests
# ---------------------------------------------------------------------------


class TestMockProviderStream:
    """MockProvider.stream() returns canned responses chunked into ~20-char pieces."""

    @pytest.mark.asyncio
    async def test_stream_qa_yields_full_content(self) -> None:
        provider = MockProvider()
        request = CompletionRequest(
            system="system",
            messages=[{"role": "user", "content": "what is mocking?"}],
            max_tokens=2048,
            temperature=0.3,
            response_format="json",
            task_type=TaskType.QA,
        )

        session = await provider.stream(request, model="mock-1")
        chunks = [chunk async for chunk in session]

        full_text = "".join(chunks)
        assert json.loads(full_text) == _MOCK_QA_RESPONSE
        assert session.result is not None
        assert session.result.provider_used == Provider.MOCK
        assert session.result.content == full_text
        assert session.result.cost_usd == 0.0

    @pytest.mark.asyncio
    async def test_stream_yields_chunks_not_entire_response(self) -> None:
        provider = MockProvider()
        request = CompletionRequest(
            system="system",
            messages=[{"role": "user", "content": "compile this"}],
            max_tokens=2048,
            temperature=0.3,
            response_format="json",
            task_type=TaskType.COMPILE,
        )

        session = await provider.stream(request, model="mock-1")
        chunks = [chunk async for chunk in session]

        # Content is longer than one chunk (20 chars)
        full_content = json.dumps(_MOCK_COMPILE_RESPONSE)
        assert len(full_content) > 20
        assert len(chunks) > 1
        assert all(len(c) <= 20 for c in chunks)


# ---------------------------------------------------------------------------
# Router stream_complete() tests
# ---------------------------------------------------------------------------


async def test_router_stream_complete_success() -> None:
    """Router.stream_complete() returns a StreamSession from the first available provider."""
    router = _router_with_settings()
    fake_session = StreamSession(_chunks=_fake_aiter(["a", "b"]))
    instance = SimpleNamespace(stream=AsyncMock(return_value=fake_session))
    with (
        patch.object(router, "_is_provider_available", return_value=True),
        patch.object(router, "_get_provider_instance", AsyncMock(return_value=instance)),
    ):
        result = await router.stream_complete(_req(), user_id=TEST_USER_ID)
    assert result is fake_session


async def test_router_stream_complete_falls_through_on_error() -> None:
    """stream_complete() tries next provider when first fails."""
    router = _router_with_settings()
    good_session = StreamSession(_chunks=_fake_aiter(["ok"]))
    bad = SimpleNamespace(stream=AsyncMock(side_effect=RuntimeError("boom")))
    good = SimpleNamespace(stream=AsyncMock(return_value=good_session))

    instances = [bad, good]

    async def get_instance(_p, **_kw):
        return instances.pop(0)

    with (
        patch.object(router, "_is_provider_available", return_value=True),
        patch.object(router, "_get_provider_instance", side_effect=get_instance),
    ):
        result = await router.stream_complete(_req(), user_id=TEST_USER_ID)
    assert result is good_session


async def test_router_stream_complete_no_available_providers() -> None:
    """stream_complete() raises RuntimeError when no providers are available."""
    router = _router_with_settings()
    with (
        patch.object(router, "_is_provider_available", return_value=False),
        pytest.raises(RuntimeError),
    ):
        await router.stream_complete(_req(), user_id=TEST_USER_ID)


async def test_router_stream_complete_no_fallback_raises() -> None:
    """stream_complete() raises immediately when fallback_enabled=False."""
    router = _router_with_settings()
    router.settings.llm.fallback_enabled = False
    bad = SimpleNamespace(stream=AsyncMock(side_effect=RuntimeError("boom")))
    with (
        patch.object(router, "_is_provider_available", return_value=True),
        patch.object(router, "_get_provider_instance", AsyncMock(return_value=bad)),
        pytest.raises(RuntimeError),
    ):
        await router.stream_complete(_req(), user_id=TEST_USER_ID)


async def _fake_aiter(items):
    """Helper to create an async iterator from a list."""
    for item in items:
        yield item
