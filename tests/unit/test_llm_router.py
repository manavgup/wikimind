"""Tests for the LLM router and provider implementations."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from wikimind.engine import llm_router as llm_router_mod
from wikimind.engine.llm_router import (
    AnthropicProvider,
    LLMRouter,
    OllamaProvider,
    OpenAIProvider,
    _calc_cost,
    get_llm_router,
)
from wikimind.models import CompletionRequest, CompletionResponse, Provider, TaskType


def _req(**kw) -> CompletionRequest:
    base = dict(
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=64,
        task_type=TaskType.QA,
    )
    base.update(kw)
    return CompletionRequest(**base)


def test_calc_cost_known_model() -> None:
    cost = _calc_cost(Provider.ANTHROPIC, "claude-sonnet-4-5", 1_000_000, 1_000_000)
    assert cost == pytest.approx(18.0)


def test_calc_cost_unknown_model_falls_back_to_zero() -> None:
    assert _calc_cost(Provider.ANTHROPIC, "no-such", 100, 100) == 0


def test_calc_cost_ollama_wildcard() -> None:
    assert _calc_cost(Provider.OLLAMA, "llama3", 1000, 1000) == 0


def test_anthropic_provider_missing_key() -> None:
    with patch.object(llm_router_mod, "get_api_key", return_value=None), pytest.raises(ValueError):
        AnthropicProvider()


async def test_anthropic_provider_complete() -> None:
    fake_response = SimpleNamespace(
        content=[SimpleNamespace(text="hello")],
        usage=SimpleNamespace(input_tokens=10, output_tokens=20),
    )
    fake_client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(return_value=fake_response)))
    with (
        patch.object(llm_router_mod, "get_api_key", return_value="key"),
        patch.object(llm_router_mod.anthropic, "AsyncAnthropic", return_value=fake_client),
    ):
        provider = AnthropicProvider()
        resp = await provider.complete(_req(), "claude-sonnet-4-5")
    assert isinstance(resp, CompletionResponse)
    assert resp.content == "hello"
    assert resp.input_tokens == 10
    assert resp.output_tokens == 20
    assert resp.provider_used == Provider.ANTHROPIC


def test_openai_provider_missing_key() -> None:
    with patch.object(llm_router_mod, "get_api_key", return_value=None), pytest.raises(ValueError):
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
        patch.object(llm_router_mod, "get_api_key", return_value="key"),
        patch.object(llm_router_mod.openai, "AsyncOpenAI", return_value=fake_client),
    ):
        provider = OpenAIProvider()
        resp = await provider.complete(_req(response_format="json"), "gpt-4o-mini")
    assert resp.content == "ok"
    assert resp.input_tokens == 5
    assert resp.provider_used == Provider.OPENAI
    kwargs = create.call_args.kwargs
    assert kwargs["response_format"] == {"type": "json_object"}


async def test_ollama_provider_complete() -> None:
    fake_client = SimpleNamespace(chat=AsyncMock(return_value={"message": {"content": "hi"}}))
    with patch.object(llm_router_mod.ollama, "AsyncClient", return_value=fake_client):
        provider = OllamaProvider("http://localhost")
        resp = await provider.complete(_req(), "llama3")
    assert resp.content == "hi"
    assert resp.cost_usd == 0.0
    assert resp.provider_used == Provider.OLLAMA


def _router_with_settings(default="anthropic", **provider_overrides):
    cfgs = {
        "anthropic": SimpleNamespace(enabled=True, model="claude-sonnet-4-5"),
        "openai": SimpleNamespace(enabled=True, model="gpt-4o-mini"),
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
        patch.object(llm_router_mod, "OllamaProvider") as oll,
    ):
        ant.return_value = "a"
        opn.return_value = "o"
        oll.return_value = "l"
        assert await router._get_provider_instance(Provider.ANTHROPIC) == "a"
        assert await router._get_provider_instance(Provider.OPENAI) == "o"
        assert await router._get_provider_instance(Provider.OLLAMA) == "l"
        with pytest.raises(ValueError):
            await router._get_provider_instance(Provider.GOOGLE)


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
        resp = await router.complete(_req(), session=db_session)
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

    async def get_instance(_p):
        return instances.pop(0)

    with (
        patch.object(router, "_is_provider_available", return_value=True),
        patch.object(router, "_get_provider_instance", side_effect=get_instance),
    ):
        resp = await router.complete(_req())
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
        await router.complete(_req())


async def test_router_complete_skips_unavailable_providers() -> None:
    router = _router_with_settings()
    with patch.object(router, "_is_provider_available", return_value=False), pytest.raises(RuntimeError):
        await router.complete(_req())


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


def test_get_llm_router_singleton() -> None:
    llm_router_mod._router = None
    with patch.object(
        llm_router_mod, "get_settings", return_value=SimpleNamespace(llm=SimpleNamespace(default_provider="anthropic"))
    ):
        r1 = get_llm_router()
        r2 = get_llm_router()
    assert r1 is r2
    llm_router_mod._router = None
