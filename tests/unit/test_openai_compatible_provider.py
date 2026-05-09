"""Tests for engine/providers/openai_compatible.py."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wikimind.engine.providers import openai_compatible as oai_mod
from wikimind.engine.providers.openai_compatible import ConfiguredOpenAICompatibleProvider, OpenAICompatibleProvider
from wikimind.models import CompletionRequest, Provider, TaskType


def _req(**kw):
    base = {
        "system": "sys",
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 64,
        "task_type": TaskType.QA,
    }
    base.update(kw)
    return CompletionRequest(**base)


def test_init_missing_key():
    with patch.object(oai_mod, "get_api_key", return_value=None), pytest.raises(ValueError):
        OpenAICompatibleProvider(base_url="http://example.com/v1")


def test_init_missing_base_url():
    with patch.object(oai_mod, "get_api_key", return_value="key"), pytest.raises(ValueError, match="base URL"):
        OpenAICompatibleProvider()


def test_init_invalid_max_tokens_field():
    with patch.object(oai_mod, "get_api_key", return_value="key"), pytest.raises(ValueError):
        OpenAICompatibleProvider(base_url="http://ex.com/v1", max_tokens_field="bad")


def test_init_invalid_reasoning_format():
    with patch.object(oai_mod, "get_api_key", return_value="key"), pytest.raises(ValueError):
        OpenAICompatibleProvider(base_url="http://ex.com/v1", reasoning_format="bad")


def test_init_with_override():
    provider = OpenAICompatibleProvider(api_key_override="key", base_url="http://ex.com/v1")
    assert provider.provider == Provider.OPENAI_COMPATIBLE


async def test_complete():
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=20)
    choice = SimpleNamespace(message=SimpleNamespace(content="result"))
    response = SimpleNamespace(choices=[choice], usage=usage)
    with patch.object(oai_mod, "get_api_key", return_value="key"):
        provider = OpenAICompatibleProvider(base_url="http://ex.com/v1")
    provider.client = MagicMock()
    provider.client.chat.completions.create = AsyncMock(return_value=response)
    resp = await provider.complete(_req(), "gpt-4o")
    assert resp.content == "result"
    assert resp.input_tokens == 10


async def test_complete_no_usage():
    choice = SimpleNamespace(message=SimpleNamespace(content="no usage"))
    response = SimpleNamespace(choices=[choice], usage=None)
    with patch.object(oai_mod, "get_api_key", return_value="key"):
        provider = OpenAICompatibleProvider(base_url="http://ex.com/v1")
    provider.client = MagicMock()
    provider.client.chat.completions.create = AsyncMock(return_value=response)
    resp = await provider.complete(_req(), "gpt-4o")
    assert resp.input_tokens == 0


async def test_complete_multimodal():
    usage = SimpleNamespace(prompt_tokens=50, completion_tokens=30)
    choice = SimpleNamespace(message=SimpleNamespace(content="I see"))
    response = SimpleNamespace(choices=[choice], usage=usage)
    with patch.object(oai_mod, "get_api_key", return_value="key"):
        provider = OpenAICompatibleProvider(base_url="http://ex.com/v1")
    provider.client = MagicMock()
    provider.client.chat.completions.create = AsyncMock(return_value=response)
    parts = [{"type": "text", "text": "Desc"}, {"type": "image", "source": {"media_type": "image/png", "data": "b64"}}]
    resp = await provider.complete_multimodal(system="sys", content_parts=parts, model="gpt-4o")
    assert resp.content == "I see"


async def test_stream():
    chunk1 = SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="hi "))], usage=None)
    chunk2 = SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content="world"))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
    )

    async def _fake():
        yield chunk1
        yield chunk2

    with patch.object(oai_mod, "get_api_key", return_value="key"):
        provider = OpenAICompatibleProvider(base_url="http://ex.com/v1")
    provider.client = MagicMock()
    provider.client.chat.completions.create = AsyncMock(return_value=_fake())
    session = await provider.stream(_req(), "gpt-4o")
    chunks = [c async for c in session]
    assert chunks == ["hi ", "world"]
    assert session.result.content == "hi world"


def test_reasoning_kwargs_openai():
    with patch.object(oai_mod, "get_api_key", return_value="key"):
        provider = OpenAICompatibleProvider(base_url="http://ex.com/v1", reasoning_format="openai")
    kwargs = {}
    provider._add_reasoning_kwargs(kwargs, _req(reasoning_effort="high"))
    assert kwargs["reasoning_effort"] == "high"


def test_reasoning_kwargs_openrouter():
    with patch.object(oai_mod, "get_api_key", return_value="key"):
        provider = OpenAICompatibleProvider(base_url="http://ex.com/v1", reasoning_format="openrouter")
    kwargs = {}
    provider._add_reasoning_kwargs(kwargs, _req(reasoning_effort="medium"))
    assert kwargs["extra_body"] == {"reasoning": {"effort": "medium"}}


def test_reasoning_kwargs_disabled():
    with patch.object(oai_mod, "get_api_key", return_value="key"):
        provider = OpenAICompatibleProvider(base_url="http://ex.com/v1", supports_reasoning_effort=False)
    kwargs = {}
    provider._add_reasoning_kwargs(kwargs, _req(reasoning_effort="high"))
    assert "reasoning_effort" not in kwargs


def test_calc_response_cost_from_attr():
    with patch.object(oai_mod, "get_api_key", return_value="key"):
        provider = OpenAICompatibleProvider(base_url="http://ex.com/v1")
    assert provider._calc_response_cost("m", 0, 0, SimpleNamespace(cost=0.005)) == 0.005


def test_calc_response_cost_string():
    with patch.object(oai_mod, "get_api_key", return_value="key"):
        provider = OpenAICompatibleProvider(base_url="http://ex.com/v1")
    assert provider._calc_response_cost("m", 0, 0, SimpleNamespace(cost="0.01")) == 0.01


def test_calc_response_cost_invalid():
    with patch.object(oai_mod, "get_api_key", return_value="key"):
        provider = OpenAICompatibleProvider(base_url="http://ex.com/v1")
    assert provider._calc_response_cost("m", 0, 0, SimpleNamespace(cost="bad", total_cost="bad")) == 0.0


def test_configured_default_headers():
    assert ConfiguredOpenAICompatibleProvider._default_headers("https://ex.com", "App") == {
        "HTTP-Referer": "https://ex.com",
        "X-Title": "App",
    }
    assert ConfiguredOpenAICompatibleProvider._default_headers("", "") == {}
