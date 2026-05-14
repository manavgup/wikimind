"""Tests for compiler integration with user-defined compilation schemas (#420)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

from tests.conftest import TEST_USER_ID
from wikimind.engine import compiler as compiler_mod
from wikimind.engine.compiler import Compiler, _build_schema_directives
from wikimind.models import (
    CompilationSchema,
    CompletionResponse,
    NormalizedDocument,
    Provider,
)

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession


def _doc() -> NormalizedDocument:
    return NormalizedDocument(
        raw_source_id="src-1",
        clean_text="Hello world",
        title="Doc Title",
        author="Author",
        published_date=None,
        estimated_tokens=100,
    )


def _fake_settings(data_dir: str = "/tmp/wm-test") -> SimpleNamespace:
    return SimpleNamespace(
        data_dir=data_dir,
        compiler=SimpleNamespace(
            max_tokens=8192,
            source_text_max_chars=60000,
            guidance_max_length=2000,
            slug_max_attempts=1000,
        ),
    )


def _make_compiler() -> Compiler:
    with (
        patch.object(compiler_mod, "get_llm_router"),
        patch.object(
            compiler_mod,
            "get_settings",
            return_value=_fake_settings(),
        ),
    ):
        return Compiler(user_id=TEST_USER_ID)


def _fake_response() -> CompletionResponse:
    return CompletionResponse(
        content=json.dumps(
            {
                "title": "Test",
                "summary": "a. b.",
                "key_claims": [],
                "concepts": [],
                "backlink_suggestions": [],
                "open_questions": [],
                "article_body": "body text " * 50,
            }
        ),
        provider_used=Provider.ANTHROPIC,
        model_used="m",
        input_tokens=1,
        output_tokens=1,
        cost_usd=0.0,
        latency_ms=1,
    )


def test_build_schema_directives_empty():
    """Schema with no fields produces empty string."""
    schema = CompilationSchema(
        user_id=TEST_USER_ID,
        name="empty",
    )
    assert _build_schema_directives(schema) == ""


def test_build_schema_directives_style():
    schema = CompilationSchema(
        user_id=TEST_USER_ID,
        name="styled",
        style="concise, technical, no hedging",
    )
    result = _build_schema_directives(schema)
    assert "concise, technical, no hedging" in result
    assert "Writing style:" in result


def test_build_schema_directives_all_fields():
    schema = CompilationSchema(
        user_id=TEST_USER_ID,
        name="full",
        article_max_length=2000,
        required_sections=json.dumps(["summary", "key_claims"]),
        style="formal",
        focus="practical applications",
        concept_max_depth=3,
        concept_naming="lowercase, hyphenated",
        extraction_always_note=json.dumps(["methodology", "sample size"]),
        extraction_ignore=json.dumps(["author bios"]),
        custom_directives="Always cite page numbers",
    )
    result = _build_schema_directives(schema)
    assert "2000 words" in result
    assert "summary, key_claims" in result
    assert "formal" in result
    assert "practical applications" in result
    assert "3 levels" in result
    assert "lowercase, hyphenated" in result
    assert "methodology, sample size" in result
    assert "author bios" in result
    assert "Always cite page numbers" in result


def test_build_schema_directives_invalid_json():
    """Invalid JSON in list fields is gracefully skipped."""
    schema = CompilationSchema(
        user_id=TEST_USER_ID,
        name="bad-json",
        required_sections="not-valid-json",
        style="formal",
    )
    result = _build_schema_directives(schema)
    assert "formal" in result
    # Should not crash, just skip the invalid field
    assert "MUST include these sections" not in result


async def test_compile_injects_active_schema(db_session: AsyncSession):
    """When an active schema exists, its directives are injected into the prompt."""
    # Insert an active schema
    schema = CompilationSchema(
        user_id=TEST_USER_ID,
        name="active-schema",
        is_active=True,
        style="concise, technical",
        focus="practical implications",
    )
    db_session.add(schema)
    await db_session.flush()

    c = _make_compiler()
    resp = _fake_response()
    c.router.complete = AsyncMock(return_value=resp)
    c.router.parse_json_response = lambda r: json.loads(r.content)

    with patch.object(compiler_mod, "get_settings") as mock_settings:
        mock_settings.return_value = SimpleNamespace(
            compiler=SimpleNamespace(max_tokens=8192, source_text_max_chars=60000),
        )
        result = await c.compile(_doc(), db_session)

    assert result is not None
    # Verify the system prompt passed to the LLM includes schema directives
    call_args = c.router.complete.call_args
    request = call_args[0][0]
    assert "concise, technical" in request.system
    assert "practical implications" in request.system


async def test_compile_no_active_schema(db_session: AsyncSession):
    """When no active schema exists, compilation uses the default prompt."""
    c = _make_compiler()
    resp = _fake_response()
    c.router.complete = AsyncMock(return_value=resp)
    c.router.parse_json_response = lambda r: json.loads(r.content)

    with patch.object(compiler_mod, "get_settings") as mock_settings:
        mock_settings.return_value = SimpleNamespace(
            compiler=SimpleNamespace(max_tokens=8192, source_text_max_chars=60000),
        )
        result = await c.compile(_doc(), db_session)

    assert result is not None
    call_args = c.router.complete.call_args
    request = call_args[0][0]
    assert "User-defined compilation rules" not in request.system
