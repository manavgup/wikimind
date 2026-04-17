"""Tests for Phase 2 compiler: typed pages, typed links, concept ID injection."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlmodel import select

from wikimind._datetime import utcnow_naive
from wikimind.engine import compiler as compiler_mod
from wikimind.engine.compiler import Compiler, _extract_typed_suggestions, _normalize_backlink_suggestions
from wikimind.engine.frontmatter_validator import parse_frontmatter, validate_frontmatter
from wikimind.engine.wikilink_resolver import resolve_backlink_candidates
from wikimind.models import (
    Article,
    Backlink,
    CompilationResult,
    CompiledClaim,
    CompletionResponse,
    Concept,
    ConfidenceLevel,
    IngestStatus,
    NormalizedDocument,
    PageType,
    Provider,
    RelationType,
    Source,
    SourceType,
)


def _result(**overrides):
    defaults = dict(
        title="Test Article",
        summary="A two sentence summary. It explains things.",
        key_claims=[CompiledClaim(claim="X", confidence=ConfidenceLevel.SOURCED)],
        concepts=["test-concept"],
        backlink_suggestions=["Related"],
        open_questions=["Q?"],
        article_body="Body of article. " * 50,
    )
    defaults.update(overrides)
    return CompilationResult(**defaults)


def _doc(tokens=100):
    return NormalizedDocument(
        raw_source_id="src-1", clean_text="Hello world", title="Doc Title", author="Author", estimated_tokens=tokens
    )


def _compiler_for(tmp_path):
    with (
        patch.object(compiler_mod, "get_llm_router"),
        patch.object(compiler_mod, "get_settings", return_value=SimpleNamespace(data_dir=str(tmp_path))),
    ):
        return Compiler()


async def _make_source(session):
    source = Source(
        id=str(uuid.uuid4()),
        source_type=SourceType.TEXT,
        title="Test Source",
        status=IngestStatus.PROCESSING,
        ingested_at=utcnow_naive(),
    )
    session.add(source)
    await session.commit()
    await session.refresh(source)
    return source


def test_normalize_typed_suggestions():
    raw = [
        {"target": "Machine Learning", "relation_type": "references"},
        {"target": "Deep Learning", "relation_type": "extends"},
    ]
    assert _normalize_backlink_suggestions(raw) == ["Machine Learning", "Deep Learning"]


def test_normalize_legacy_string_suggestions():
    assert _normalize_backlink_suggestions(["ML", "DL"]) == ["ML", "DL"]


def test_normalize_mixed_suggestions():
    raw = [{"target": "ML", "relation_type": "references"}, "DL"]
    assert _normalize_backlink_suggestions(raw) == ["ML", "DL"]


def test_extract_typed_from_dicts():
    raw = [{"target": "A", "relation_type": "extends"}, {"target": "B", "relation_type": "supersedes"}]
    result = _extract_typed_suggestions(raw)
    assert len(result) == 2
    assert result[0].relation_type == RelationType.EXTENDS
    assert result[1].relation_type == RelationType.SUPERSEDES


def test_extract_typed_from_strings():
    result = _extract_typed_suggestions(["Some Article", "Another"])
    assert all(s.relation_type == RelationType.REFERENCES for s in result)


def test_extract_typed_invalid_relation_defaults():
    result = _extract_typed_suggestions([{"target": "X", "relation_type": "invalid"}])
    assert result[0].relation_type == RelationType.REFERENCES


async def test_concept_id_injection(db_session):
    c1 = Concept(name="machine-learning")
    c2 = Concept(name="deep-learning")
    db_session.add(c1)
    db_session.add(c2)
    await db_session.commit()

    c = _compiler_for(Path("/tmp/wm-test"))
    fake_resp = CompletionResponse(
        content=json.dumps(
            {
                "title": "X",
                "summary": "a. b.",
                "key_claims": [],
                "concepts": [],
                "backlink_suggestions": [],
                "open_questions": [],
                "article_body": "body",
            }
        ),
        provider_used=Provider.ANTHROPIC,
        model_used="m",
        input_tokens=1,
        output_tokens=1,
        cost_usd=0.0,
        latency_ms=1,
    )
    c.router.complete = AsyncMock(return_value=fake_resp)
    c.router.parse_json_response = lambda r: json.loads(r.content)
    await c.compile(_doc(), db_session)
    user_msg = c.router.complete.call_args[0][0].messages[0]["content"]
    assert "Existing concepts in this wiki" in user_msg
    assert "deep-learning" in user_msg
    assert "machine-learning" in user_msg


async def test_no_concept_injection_when_empty(db_session):
    c = _compiler_for(Path("/tmp/wm-test"))
    fake_resp = CompletionResponse(
        content=json.dumps(
            {
                "title": "X",
                "summary": "a. b.",
                "key_claims": [],
                "concepts": [],
                "backlink_suggestions": [],
                "open_questions": [],
                "article_body": "body",
            }
        ),
        provider_used=Provider.ANTHROPIC,
        model_used="m",
        input_tokens=1,
        output_tokens=1,
        cost_usd=0.0,
        latency_ms=1,
    )
    c.router.complete = AsyncMock(return_value=fake_resp)
    c.router.parse_json_response = lambda r: json.loads(r.content)
    await c.compile(_doc(), db_session)
    user_msg = c.router.complete.call_args[0][0].messages[0]["content"]
    assert "Existing concepts" not in user_msg


async def test_system_controlled_fields(db_session):
    c = _compiler_for(Path("/tmp/wm-test"))
    fake_resp = CompletionResponse(
        content=json.dumps(
            {
                "title": "X",
                "summary": "a. b.",
                "key_claims": [],
                "concepts": [],
                "backlink_suggestions": [],
                "open_questions": [],
                "article_body": "body",
                "page_type": "concept",
                "compiled": "2020-01-01T00:00:00",
                "provider": "openai",
            }
        ),
        provider_used=Provider.ANTHROPIC,
        model_used="m",
        input_tokens=1,
        output_tokens=1,
        cost_usd=0.0,
        latency_ms=1,
    )
    c.router.complete = AsyncMock(return_value=fake_resp)
    c.router.parse_json_response = lambda r: json.loads(r.content)
    result = await c.compile(_doc(), db_session)
    assert result is not None
    assert result.page_type == PageType.SOURCE
    assert result.provider == Provider.ANTHROPIC
    assert result.compiled is not None and result.compiled.year >= 2026


async def test_relation_type_persisted(db_session, tmp_path):
    target = Article(
        id=str(uuid.uuid4()),
        slug="existing",
        title="Existing Article",
        file_path=str(tmp_path / "existing.md"),
        confidence=ConfidenceLevel.SOURCED,
    )
    db_session.add(target)
    await db_session.commit()
    compiler = _compiler_for(tmp_path)
    compiler._last_typed_suggestions = {"existing article": "extends"}
    source = await _make_source(db_session)
    article = await compiler.save_article(_result(backlink_suggestions=["Existing Article"]), source, db_session)
    bl_result = await db_session.execute(select(Backlink).where(Backlink.source_article_id == article.id))
    backlinks = list(bl_result.scalars().all())
    assert len(backlinks) == 1
    assert backlinks[0].relation_type == RelationType.EXTENDS


async def test_default_relation_type_references(db_session, tmp_path):
    target = Article(
        id=str(uuid.uuid4()),
        slug="target",
        title="Target Article",
        file_path=str(tmp_path / "target.md"),
        confidence=ConfidenceLevel.SOURCED,
    )
    db_session.add(target)
    await db_session.commit()
    compiler = _compiler_for(tmp_path)
    compiler._last_typed_suggestions = {}
    source = await _make_source(db_session)
    article = await compiler.save_article(_result(backlink_suggestions=["Target Article"]), source, db_session)
    bl_result = await db_session.execute(select(Backlink).where(Backlink.source_article_id == article.id))
    backlinks = list(bl_result.scalars().all())
    assert len(backlinks) == 1
    assert backlinks[0].relation_type == RelationType.REFERENCES


async def test_article_page_type_source(db_session, tmp_path):
    compiler = _compiler_for(tmp_path)
    source = await _make_source(db_session)
    article = await compiler.save_article(_result(), source, db_session)
    assert article.page_type == PageType.SOURCE


def test_validate_source_frontmatter():
    content = '---\ntitle: "Test"\nslug: test\npage_type: source\nsource_id: abc-123\nsource_type: url\nsource_url: http://example.com\ncompiled: 2026-04-13T12:00:00\nconcepts: []\nconfidence: sourced\nprovider: anthropic\n---\n\n## Summary\n\nTest.\n'
    assert validate_frontmatter(content) is True


def test_validate_missing_page_type():
    content = "---\ntitle: Test\nslug: test\n---\nContent.\n"
    assert validate_frontmatter(content) is False


def test_validate_no_frontmatter():
    content = "No frontmatter here."
    assert validate_frontmatter(content) is False


def test_parse_frontmatter_extracts_yaml():
    content = "---\ntitle: Hello\nslug: hello\npage_type: source\n---\nBody.\n"
    data = parse_frontmatter(content)
    assert data is not None
    assert data["title"] == "Hello"
    assert data["page_type"] == "source"


def test_write_article_file_includes_page_type(tmp_path):
    with (
        patch.object(compiler_mod, "get_llm_router"),
        patch.object(compiler_mod, "get_settings", return_value=SimpleNamespace(data_dir=str(tmp_path))),
    ):
        c = Compiler()
    src = Source(source_type=SourceType.URL, source_url="http://x", title="X")
    rel_path = c._write_article_file(_result(), src, "test-slug", [], [])
    full_path = Path(tmp_path) / "wiki" / rel_path
    assert full_path.exists()
    text = full_path.read_text()
    assert "page_type: source" in text
    assert "source_id:" in text


async def test_resolver_passes_relation_types(db_session):
    article = Article(
        id=str(uuid.uuid4()),
        slug="ml",
        title="Machine Learning",
        file_path="/tmp/ml.md",
        confidence=ConfidenceLevel.SOURCED,
    )
    db_session.add(article)
    await db_session.commit()
    resolved, _ = await resolve_backlink_candidates(
        ["Machine Learning"], db_session, relation_types={"machine learning": "extends"}
    )
    assert len(resolved) == 1
    assert resolved[0].relation_type == "extends"


async def test_resolver_defaults_to_references(db_session):
    article = Article(
        id=str(uuid.uuid4()),
        slug="dl",
        title="Deep Learning",
        file_path="/tmp/dl.md",
        confidence=ConfidenceLevel.SOURCED,
    )
    db_session.add(article)
    await db_session.commit()
    resolved, _ = await resolve_backlink_candidates(["Deep Learning"], db_session)
    assert len(resolved) == 1
    assert resolved[0].relation_type == "references"
