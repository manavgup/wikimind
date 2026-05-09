"""Tests for the MockProvider deterministic LLM provider."""

from __future__ import annotations

import pytest

from wikimind.engine.providers.mock import MockProvider
from wikimind.models import CompletionRequest, Provider, TaskType


class TestMockProviderMultimodal:
    @pytest.mark.asyncio
    async def test_complete_multimodal_with_images(self):
        """complete_multimodal should return one description per image."""
        provider = MockProvider()
        parts = [
            {"type": "image", "data": "base64data"},
            {"type": "text", "text": "describe this"},
            {"type": "image", "data": "base64data2"},
        ]
        resp = await provider.complete_multimodal(
            system="You are a vision model.",
            content_parts=parts,
            model="mock-vision",
        )
        assert resp.provider_used == Provider.MOCK
        assert "[Page 1 description:" in resp.content
        assert "[Page 2 description:" in resp.content

    @pytest.mark.asyncio
    async def test_complete_multimodal_no_images(self):
        """complete_multimodal with no images should return fallback message."""
        provider = MockProvider()
        parts = [{"type": "text", "text": "no images here"}]
        resp = await provider.complete_multimodal(
            system="You are a vision model.",
            content_parts=parts,
            model="mock-vision",
        )
        assert resp.content == "No images provided."


class TestMockProviderResponseFor:
    @pytest.mark.asyncio
    async def test_unknown_task_type_returns_empty_json(self):
        """Unknown task types should return '{}' without crashing."""
        provider = MockProvider()
        request = CompletionRequest(
            system="test system",
            messages=[{"role": "user", "content": "test"}],
            task_type=TaskType.INDEX,
            max_tokens=100,
        )
        resp = await provider.complete(request, model="mock")
        assert resp.content == "{}"
