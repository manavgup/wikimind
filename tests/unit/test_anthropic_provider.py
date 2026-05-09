"""Tests for engine/providers/anthropic.py."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wikimind.engine.providers import anthropic as anthropic_mod
from wikimind.engine.providers.anthropic import AnthropicProvider
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


def test_missing_key():
    with patch.object(anthropic_mod, "get_api_key", return_value=None), pytest.raises(ValueError):
        AnthropicProvider()


async def test_complete():
    usage = SimpleNamespace(input_tokens=15, output_tokens=25)
    response = SimpleNamespace(content=[SimpleNamespace(text="hello")], usage=usage)
    provider = AnthropicProvider(api_key_override="test-key")
    provider.client = MagicMock()
    provider.client.messages.create = AsyncMock(return_value=response)
    resp = await provider.complete(_req(), "claude-sonnet-4-5")
    assert resp.content == "hello"
    assert resp.provider_used == Provider.ANTHROPIC


async def test_complete_multimodal():
    usage = SimpleNamespace(input_tokens=100, output_tokens=50)
    response = SimpleNamespace(content=[SimpleNamespace(text="I see")], usage=usage)
    provider = AnthropicProvider(api_key_override="test-key")
    provider.client = MagicMock()
    provider.client.messages.create = AsyncMock(return_value=response)
    parts = [
        {"type": "text", "text": "Desc"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "b64"}},
    ]
    resp = await provider.complete_multimodal(system="sys", content_parts=parts, model="claude-sonnet-4-5")
    assert resp.content == "I see"


async def test_stream():
    final_msg = SimpleNamespace(
        content=[SimpleNamespace(text="hello world")], usage=SimpleNamespace(input_tokens=10, output_tokens=5)
    )

    class FakeCtx:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        @property
        def text_stream(self):
            return self._gen()

        async def _gen(self):
            yield "hello "
            yield "world"

        async def get_final_message(self):
            return final_msg

    provider = AnthropicProvider(api_key_override="test-key")
    provider.client = MagicMock()
    provider.client.messages.stream = MagicMock(return_value=FakeCtx())
    session = await provider.stream(_req(), "claude-sonnet-4-5")
    chunks = [c async for c in session]
    assert chunks == ["hello ", "world"]
    assert session.result.content == "hello world"
