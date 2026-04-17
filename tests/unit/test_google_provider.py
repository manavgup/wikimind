"""Tests for the GoogleProvider implementation (google.genai SDK)."""

from __future__ import annotations

import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.genai import types as genai_types

from wikimind.engine.llm_router import StreamSession, _calc_cost
from wikimind.engine.providers import google as google_provider_mod
from wikimind.engine.providers.google import GoogleProvider
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


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


def test_google_provider_missing_key() -> None:
    with (
        patch.object(google_provider_mod, "get_api_key", return_value=None),
        pytest.raises(ValueError, match="Google API key"),
    ):
        GoogleProvider()


def test_google_provider_init_creates_client() -> None:
    with (
        patch.object(google_provider_mod, "get_api_key", return_value="test-key"),
        patch.object(google_provider_mod.genai, "Client") as mock_client_cls,
    ):
        provider = GoogleProvider()
        mock_client_cls.assert_called_once_with(api_key="test-key")  # pragma: allowlist secret
        assert provider.client is mock_client_cls.return_value


# ---------------------------------------------------------------------------
# complete()
# ---------------------------------------------------------------------------


async def test_google_provider_complete() -> None:
    """GoogleProvider.complete() returns a CompletionResponse with token counts."""
    fake_usage = SimpleNamespace(prompt_token_count=15, candidates_token_count=25)
    fake_response = SimpleNamespace(text="hello from gemini", usage_metadata=fake_usage)

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=fake_response)

    with (
        patch.object(google_provider_mod, "get_api_key", return_value="key"),
        patch.object(google_provider_mod.genai, "Client", return_value=mock_client),
    ):
        provider = GoogleProvider()
        resp = await provider.complete(_req(), "gemini-2.0-flash")

    assert isinstance(resp, CompletionResponse)
    assert resp.content == "hello from gemini"
    assert resp.input_tokens == 15
    assert resp.output_tokens == 25
    assert resp.provider_used == Provider.GOOGLE
    assert resp.model_used == "gemini-2.0-flash"
    assert resp.latency_ms >= 0

    # Verify generate_content was called with correct model and config
    call_kwargs = mock_client.aio.models.generate_content.call_args
    assert call_kwargs.kwargs["model"] == "gemini-2.0-flash"
    config = call_kwargs.kwargs["config"]
    assert config.system_instruction == "sys"


async def test_google_provider_complete_json_format() -> None:
    """GoogleProvider.complete() passes response_mime_type for JSON format."""
    fake_usage = SimpleNamespace(prompt_token_count=5, candidates_token_count=10)
    fake_response = SimpleNamespace(text='{"answer": "ok"}', usage_metadata=fake_usage)

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=fake_response)

    with (
        patch.object(google_provider_mod, "get_api_key", return_value="key"),
        patch.object(google_provider_mod.genai, "Client", return_value=mock_client),
    ):
        provider = GoogleProvider()
        resp = await provider.complete(_req(response_format="json"), "gemini-2.0-flash")

    assert resp.content == '{"answer": "ok"}'

    # Check that config included response_mime_type
    call_kwargs = mock_client.aio.models.generate_content.call_args
    config = call_kwargs.kwargs["config"]
    assert config.response_mime_type == "application/json"


async def test_google_provider_complete_no_usage_metadata() -> None:
    """GoogleProvider.complete() handles missing usage_metadata gracefully."""
    fake_response = SimpleNamespace(text="no usage", usage_metadata=None)

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=fake_response)

    with (
        patch.object(google_provider_mod, "get_api_key", return_value="key"),
        patch.object(google_provider_mod.genai, "Client", return_value=mock_client),
    ):
        provider = GoogleProvider()
        resp = await provider.complete(_req(), "gemini-2.0-flash")

    assert resp.input_tokens == 0
    assert resp.output_tokens == 0


# ---------------------------------------------------------------------------
# complete_multimodal()
# ---------------------------------------------------------------------------


async def test_google_provider_complete_multimodal() -> None:
    """GoogleProvider.complete_multimodal() translates Anthropic content blocks."""
    fake_usage = SimpleNamespace(prompt_token_count=100, candidates_token_count=50)
    fake_response = SimpleNamespace(text="I see a diagram", usage_metadata=fake_usage)

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=fake_response)

    sample_b64 = base64.b64encode(b"fake-image-data").decode()

    content_parts = [
        {"type": "text", "text": "Describe this image."},
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": sample_b64,
            },
        },
    ]

    with (
        patch.object(google_provider_mod, "get_api_key", return_value="key"),
        patch.object(google_provider_mod.genai, "Client", return_value=mock_client),
        patch.object(google_provider_mod.types.Part, "from_bytes") as mock_from_bytes,
    ):
        mock_from_bytes.return_value = SimpleNamespace(mime_type="image/png")
        provider = GoogleProvider()
        resp = await provider.complete_multimodal(
            system="You are a vision assistant.",
            content_parts=content_parts,
            model="gemini-2.0-flash",
        )

    assert isinstance(resp, CompletionResponse)
    assert resp.content == "I see a diagram"
    assert resp.provider_used == Provider.GOOGLE
    assert resp.input_tokens == 100
    assert resp.output_tokens == 50

    # Verify types.Part.from_bytes was called for the image
    mock_from_bytes.assert_called_once_with(
        data=base64.b64decode(sample_b64),
        mime_type="image/png",
    )

    # Verify content format: first is text string, second is the Part
    call_kwargs = mock_client.aio.models.generate_content.call_args.kwargs
    google_parts = call_kwargs["contents"]
    assert google_parts[0] == "Describe this image."


async def test_google_provider_multimodal_text_only() -> None:
    """GoogleProvider.complete_multimodal() works with text-only content."""
    fake_usage = SimpleNamespace(prompt_token_count=10, candidates_token_count=20)
    fake_response = SimpleNamespace(text="text only response", usage_metadata=fake_usage)

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=fake_response)

    content_parts = [
        {"type": "text", "text": "First part."},
        {"type": "text", "text": "Second part."},
    ]

    with (
        patch.object(google_provider_mod, "get_api_key", return_value="key"),
        patch.object(google_provider_mod.genai, "Client", return_value=mock_client),
    ):
        provider = GoogleProvider()
        resp = await provider.complete_multimodal(
            system="sys",
            content_parts=content_parts,
            model="gemini-2.0-flash",
        )

    assert resp.content == "text only response"

    # All parts should be plain strings
    call_kwargs = mock_client.aio.models.generate_content.call_args.kwargs
    google_parts = call_kwargs["contents"]
    assert google_parts == ["First part.", "Second part."]


# ---------------------------------------------------------------------------
# stream()
# ---------------------------------------------------------------------------


async def test_google_provider_stream() -> None:
    """GoogleProvider.stream() yields chunks and populates result."""
    chunk1 = SimpleNamespace(
        text="hello ",
        usage_metadata=SimpleNamespace(prompt_token_count=10, candidates_token_count=3),
    )
    chunk2 = SimpleNamespace(
        text="world",
        usage_metadata=SimpleNamespace(prompt_token_count=10, candidates_token_count=8),
    )

    async def _fake_stream():
        yield chunk1
        yield chunk2

    mock_client = MagicMock()
    mock_client.aio.models.generate_content_stream = AsyncMock(return_value=_fake_stream())

    with (
        patch.object(google_provider_mod, "get_api_key", return_value="key"),
        patch.object(google_provider_mod.genai, "Client", return_value=mock_client),
    ):
        provider = GoogleProvider()
        session = await provider.stream(_req(), "gemini-2.0-flash")

    assert isinstance(session, StreamSession)
    chunks = [chunk async for chunk in session]
    assert chunks == ["hello ", "world"]
    assert session.result is not None
    assert session.result.content == "hello world"
    assert session.result.provider_used == Provider.GOOGLE
    assert session.result.input_tokens == 10
    assert session.result.output_tokens == 8
    assert session.result.latency_ms >= 0


async def test_google_provider_stream_empty_chunks_skipped() -> None:
    """GoogleProvider.stream() skips chunks with empty/None text."""
    chunk1 = SimpleNamespace(text="data", usage_metadata=None)
    chunk2 = SimpleNamespace(text="", usage_metadata=None)
    chunk3 = SimpleNamespace(text=None, usage_metadata=None)

    async def _fake_stream():
        yield chunk1
        yield chunk2
        yield chunk3

    mock_client = MagicMock()
    mock_client.aio.models.generate_content_stream = AsyncMock(return_value=_fake_stream())

    with (
        patch.object(google_provider_mod, "get_api_key", return_value="key"),
        patch.object(google_provider_mod.genai, "Client", return_value=mock_client),
    ):
        provider = GoogleProvider()
        session = await provider.stream(_req(), "gemini-2.0-flash")

    chunks = [chunk async for chunk in session]
    assert chunks == ["data"]
    assert session.result.content == "data"


# ---------------------------------------------------------------------------
# Content format translation
# ---------------------------------------------------------------------------


def test_anthropic_to_google_content_translation() -> None:
    """Verify Anthropic-style content blocks translate to Google format using types.Part.from_bytes."""
    sample_data = base64.b64encode(b"\x89PNG\r\n").decode()

    anthropic_parts = [
        {"type": "text", "text": "Describe the image"},
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": sample_data,
            },
        },
        {"type": "text", "text": "Also this"},
    ]

    # Replicate the translation logic from GoogleProvider.complete_multimodal
    # using the new google.genai types
    google_parts: list = []
    for part in anthropic_parts:
        if part["type"] == "text":
            google_parts.append(part["text"])
        elif part["type"] == "image":
            media_type = part["source"]["media_type"]
            data_b64 = part["source"]["data"]
            google_parts.append(
                genai_types.Part.from_bytes(
                    data=base64.b64decode(data_b64),
                    mime_type=media_type,
                )
            )

    assert len(google_parts) == 3
    assert google_parts[0] == "Describe the image"
    assert hasattr(google_parts[1], "inline_data")
    assert google_parts[2] == "Also this"


# ---------------------------------------------------------------------------
# Cost calculation
# ---------------------------------------------------------------------------


def test_google_cost_calculation() -> None:
    """Verify cost calculation for Google Gemini pricing."""
    # gemini-2.0-flash: input=$0.10/M, output=$0.40/M
    cost = _calc_cost(Provider.GOOGLE, "gemini-2.0-flash", 1_000_000, 1_000_000)
    assert cost == pytest.approx(0.50)

    # Smaller usage
    cost = _calc_cost(Provider.GOOGLE, "gemini-2.0-flash", 1000, 500)
    expected = (1000 * 0.10 + 500 * 0.40) / 1_000_000
    assert cost == pytest.approx(expected)
