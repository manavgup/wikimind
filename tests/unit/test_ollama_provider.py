"""Tests for engine/providers/ollama.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from wikimind.engine.providers import ollama as ollama_mod
from wikimind.engine.providers.ollama import OllamaProvider
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


async def test_ollama_complete() -> None:
    mock_client = MagicMock()
    mock_client.chat = AsyncMock(return_value={"message": {"content": "Hello!"}})
    with patch.object(ollama_mod.ollama, "AsyncClient", return_value=mock_client):
        provider = OllamaProvider(base_url="http://localhost:11434")
        resp = await provider.complete(_req(), "llama3.2")
    assert resp.content == "Hello!"
    assert resp.provider_used == Provider.OLLAMA


async def test_ollama_complete_json_format() -> None:
    mock_client = MagicMock()
    mock_client.chat = AsyncMock(return_value={"message": {"content": '{"ok": true}'}})
    with patch.object(ollama_mod.ollama, "AsyncClient", return_value=mock_client):
        provider = OllamaProvider(base_url="http://localhost:11434")
        await provider.complete(_req(response_format="json"), "llama3.2")
    assert mock_client.chat.call_args[1]["format"] == "json"


async def test_ollama_complete_multimodal() -> None:
    mock_client = MagicMock()
    mock_client.chat = AsyncMock(return_value={"message": {"content": "I see a cat"}})
    parts = [{"type": "text", "text": "Describe"}, {"type": "image", "source": {"data": "b64data"}}]
    with patch.object(ollama_mod.ollama, "AsyncClient", return_value=mock_client):
        provider = OllamaProvider(base_url="http://localhost:11434")
        resp = await provider.complete_multimodal(system="sys", content_parts=parts, model="llava")
    assert resp.content == "I see a cat"


async def test_ollama_complete_multimodal_no_text() -> None:
    mock_client = MagicMock()
    mock_client.chat = AsyncMock(return_value={"message": {"content": "desc"}})
    parts = [{"type": "image", "source": {"data": "data"}}]
    with patch.object(ollama_mod.ollama, "AsyncClient", return_value=mock_client):
        provider = OllamaProvider(base_url="http://localhost:11434")
        await provider.complete_multimodal(system="sys", content_parts=parts, model="llava")
    assert mock_client.chat.call_args[1]["messages"][1]["content"] == "Describe these images."


async def test_ollama_stream() -> None:
    async def _fake():
        yield {"message": {"content": "hello "}}
        yield {"message": {"content": "world"}}

    mock_client = MagicMock()
    mock_client.chat = AsyncMock(return_value=_fake())
    with patch.object(ollama_mod.ollama, "AsyncClient", return_value=mock_client):
        provider = OllamaProvider(base_url="http://localhost:11434")
        session = await provider.stream(_req(), "llama3.2")
    chunks = [c async for c in session]
    assert chunks == ["hello ", "world"]
    assert session.result.content == "hello world"


async def test_ollama_stream_json() -> None:
    async def _fake():
        yield {"message": {"content": "{}"}}

    mock_client = MagicMock()
    mock_client.chat = AsyncMock(return_value=_fake())
    with patch.object(ollama_mod.ollama, "AsyncClient", return_value=mock_client):
        provider = OllamaProvider(base_url="http://localhost:11434")
        session = await provider.stream(_req(response_format="json"), "llama3.2")
    [c async for c in session]
    assert mock_client.chat.call_args[1]["format"] == "json"
