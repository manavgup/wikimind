"""Tests for the wiki Compiler engine."""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlmodel import select

from wikimind._datetime import utcnow_naive
from wikimind.engine import compiler as compiler_mod
from wikimind.engine.compiler import Compiler
from wikimind.models import (
    Article,
    Backlink,
    CompilationResult,
    CompiledClaim,
    CompletionResponse,
    ConfidenceLevel,
    DocumentChunk,
    IngestStatus,
    NormalizedDocument,
    Provider,
    Source,
    SourceType,
)


def _result(claims: list[CompiledClaim] | None = None, concepts: list[str] | None = None) -> CompilationResult:
    return CompilationResult(
        title="Test Article",
        summary="A two sentence summary. It explains things.",
        key_claims=claims or [CompiledClaim(claim="X", confidence=ConfidenceLevel.SOURCED)],
        concepts=concepts or ["test-concept"],
        backlink_suggestions=["Related"],
        open_questions=["Q?"],
        article_body="Body of article. " * 50,
    )


def _doc(tokens: int = 100, chunks: list[DocumentChunk] | None = None) -> NormalizedDocument:
    return NormalizedDocument(
        raw_source_id="src-1",
        clean_text="Hello world",
        title="Doc Title",
        author="Author",
        published_date=None,
        estimated_tokens=tokens,
        chunks=chunks or [],
    )


def _make_compiler() -> Compiler:
    with (
        patch.object(compiler_mod, "get_llm_router"),
        patch.object(compiler_mod, "get_settings", return_value=SimpleNamespace(data_dir="/tmp/wm-test")),
    ):
        return Compiler()


async def test_compile_success(db_session, tmp_path) -> None:
    c = _make_compiler()
    fake_resp = CompletionResponse(
        content='{"title":"X","summary":"a. b.","key_claims":[],"concepts":[],"backlink_suggestions":[],"open_questions":[],"article_body":"body"}',
        provider_used=Provider.ANTHROPIC,
        model_used="m",
        input_tokens=1,
        output_tokens=1,
        cost_usd=0.0,
        latency_ms=1,
    )
    c.router.complete = AsyncMock(return_value=fake_resp)
    c.router.parse_json_response = lambda r: {
        "title": "X",
        "summary": "a. b.",
        "key_claims": [],
        "concepts": [],
        "backlink_suggestions": [],
        "open_questions": [],
        "article_body": "body",
    }
    result = await c.compile(_doc(), db_session)
    assert result is not None
    assert result.title == "X"


async def test_compile_returns_none_on_parse_error(db_session) -> None:
    c = _make_compiler()
    fake_resp = CompletionResponse(
        content="not json",
        provider_used=Provider.ANTHROPIC,
        model_used="m",
        input_tokens=0,
        output_tokens=0,
        cost_usd=0,
        latency_ms=0,
    )
    c.router.complete = AsyncMock(return_value=fake_resp)
    c.router.parse_json_response = lambda r: (_ for _ in ()).throw(ValueError("bad"))
    result = await c.compile(_doc(), db_session)
    assert result is None


async def test_compile_chunked_path(db_session) -> None:
    c = _make_compiler()
    chunks = [
        DocumentChunk(document_id="d", content=f"chunk{i}", heading_path=[], token_count=10, chunk_index=i)
        for i in range(2)
    ]
    doc = _doc(tokens=100_000, chunks=chunks)
    chunk_result = _result()

    async def fake_compile(d, sess):
        # Avoid infinite recursion: only return for sub-chunks
        if d.estimated_tokens < 80_000:
            return chunk_result
        # call original
        return await Compiler.compile(c, d, sess)

    with patch.object(c, "compile", side_effect=fake_compile):
        merged = await c._compile_chunked(doc, db_session)
    assert merged is not None
    assert merged.title == doc.title


async def test_compile_chunked_returns_none_when_no_results(db_session) -> None:
    c = _make_compiler()
    chunks = [DocumentChunk(document_id="d", content="x", heading_path=[], token_count=10, chunk_index=0)]
    doc = _doc(tokens=100_000, chunks=chunks)
    with patch.object(c, "compile", AsyncMock(return_value=None)):
        merged = await c._compile_chunked(doc, db_session)
    assert merged is None


def test_build_user_prompt_includes_metadata() -> None:
    c = _make_compiler()
    doc = _doc()
    doc.published_date = None
    p = c._build_user_prompt(doc)
    assert "Doc Title" in p
    assert "Author" in p


def test_merge_chunk_results() -> None:
    c = _make_compiler()
    r1 = _result(concepts=["a", "b"])
    r2 = _result(concepts=["b", "c"])
    merged = c._merge_chunk_results("Big Title", [r1, r2])
    assert merged.title == "Big Title"
    assert len(merged.key_claims) <= 20
    assert set(merged.concepts).issubset({"a", "b", "c"})


def test_overall_confidence_no_claims() -> None:
    c = _make_compiler()
    r = CompilationResult(
        title="t",
        summary="s. s.",
        key_claims=[],
        concepts=[],
        backlink_suggestions=[],
        open_questions=[],
        article_body="x",
    )
    assert c._overall_confidence(r) == ConfidenceLevel.INFERRED


def test_overall_confidence_sourced() -> None:
    c = _make_compiler()
    r = _result(claims=[CompiledClaim(claim=f"c{i}", confidence=ConfidenceLevel.SOURCED) for i in range(5)])
    assert c._overall_confidence(r) == ConfidenceLevel.SOURCED


def test_overall_confidence_mixed() -> None:
    c = _make_compiler()
    claims = [
        CompiledClaim(claim="a", confidence=ConfidenceLevel.SOURCED),
        CompiledClaim(claim="b", confidence=ConfidenceLevel.INFERRED),
    ]
    assert c._overall_confidence(_result(claims=claims)) == ConfidenceLevel.MIXED


def test_overall_confidence_inferred() -> None:
    c = _make_compiler()
    claims = [
        CompiledClaim(claim="a", confidence=ConfidenceLevel.INFERRED),
        CompiledClaim(claim="b", confidence=ConfidenceLevel.INFERRED),
        CompiledClaim(claim="c", confidence=ConfidenceLevel.SOURCED),
    ]
    # 1/3 sourced -> inferred
    assert c._overall_confidence(_result(claims=claims)) == ConfidenceLevel.INFERRED


def test_generate_unique_slug() -> None:
    c = _make_compiler()
    assert c._generate_unique_slug("Hello World!") == "hello-world"


def test_write_article_file(tmp_path) -> None:
    with (
        patch.object(compiler_mod, "get_llm_router"),
        patch.object(compiler_mod, "get_settings", return_value=SimpleNamespace(data_dir=str(tmp_path))),
    ):
        c = Compiler()
    src = Source(source_type=SourceType.URL, source_url="http://x", title="X")
    path = c._write_article_file(_result(), src, "test-slug", [], [])
    assert path.exists()
    text = path.read_text()
    assert "Test Article" in text
    assert "test-slug" in text


def test_write_article_file_no_concepts(tmp_path) -> None:
    with (
        patch.object(compiler_mod, "get_llm_router"),
        patch.object(compiler_mod, "get_settings", return_value=SimpleNamespace(data_dir=str(tmp_path))),
    ):
        c = Compiler()
    r = CompilationResult(
        title="t",
        summary="s. s.",
        key_claims=[CompiledClaim(claim="x", confidence=ConfidenceLevel.SOURCED)],
        concepts=[],
        backlink_suggestions=[],
        open_questions=[],
        article_body="x",
    )
    src = Source(source_type=SourceType.TEXT, title=None)
    path = c._write_article_file(r, src, "no-concept", [], [])
    assert path.exists()
    assert "general" in str(path)


async def test_save_article(db_session, tmp_path) -> None:
    with (
        patch.object(compiler_mod, "get_llm_router"),
        patch.object(compiler_mod, "get_settings", return_value=SimpleNamespace(data_dir=str(tmp_path))),
    ):
        c = Compiler()
    src = Source(source_type=SourceType.URL, source_url="http://x", title="X", status=IngestStatus.PROCESSING)
    db_session.add(src)
    await db_session.commit()
    await db_session.refresh(src)
    article = await c.save_article(_result(), src, db_session)
    assert article.slug
    assert Path(article.file_path).exists()
    assert src.status == IngestStatus.COMPILED


# ---------------------------------------------------------------------------
# Resolution-aware save path (Task 4)
# ---------------------------------------------------------------------------


def _result_with_backlinks(
    title: str,
    backlink_suggestions: list[str] | None = None,
) -> CompilationResult:
    return CompilationResult(
        title=title,
        summary="A two-sentence summary. For testing.",
        key_claims=[
            CompiledClaim(claim="test claim", confidence=ConfidenceLevel.SOURCED),
        ],
        concepts=["test-concept"],
        backlink_suggestions=backlink_suggestions or [],
        open_questions=["test question?"],
        article_body="## Body\n\nTest body content sufficient length.",
    )


async def _make_source(session) -> Source:
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


def _compiler_for(tmp_path: Path) -> Compiler:
    with (
        patch.object(compiler_mod, "get_llm_router"),
        patch.object(compiler_mod, "get_settings", return_value=SimpleNamespace(data_dir=str(tmp_path))),
    ):
        return Compiler()


async def test_save_creates_backlink_rows_for_resolved_candidates(db_session, tmp_path) -> None:
    # Seed an existing article that a future candidate will resolve to.
    target = Article(
        id=str(uuid.uuid4()),
        slug="existing-article",
        title="Existing Article",
        file_path=str(tmp_path / "existing.md"),
        confidence=ConfidenceLevel.SOURCED,
    )
    db_session.add(target)
    await db_session.commit()

    compiler = _compiler_for(tmp_path)
    source = await _make_source(db_session)
    result = _result_with_backlinks(
        "New Article",
        backlink_suggestions=["Existing Article", "Nonexistent Topic"],
    )
    article = await compiler.save_article(result, source, db_session)

    bl_result = await db_session.execute(select(Backlink).where(Backlink.source_article_id == article.id))
    backlinks = list(bl_result.scalars().all())
    assert len(backlinks) == 1
    assert backlinks[0].target_article_id == target.id
    assert backlinks[0].context == "Existing Article"


async def test_save_markdown_has_resolved_link_and_unresolved_bracket(db_session, tmp_path) -> None:
    target = Article(
        id=str(uuid.uuid4()),
        slug="existing-article",
        title="Existing Article",
        file_path=str(tmp_path / "existing.md"),
        confidence=ConfidenceLevel.SOURCED,
    )
    db_session.add(target)
    await db_session.commit()

    compiler = _compiler_for(tmp_path)
    source = await _make_source(db_session)
    result = _result_with_backlinks(
        "New Article",
        backlink_suggestions=["Existing Article", "Nonexistent Topic"],
    )
    article = await compiler.save_article(result, source, db_session)

    content = Path(article.file_path).read_text()
    assert f"[Existing Article](/wiki/{target.id})" in content
    assert "[[Nonexistent Topic]]" in content
    assert "- [[Existing Article]]" not in content


async def test_save_dedupes_candidates_resolving_to_same_target(db_session, tmp_path) -> None:
    """Two candidates resolving to the same target → one Backlink row.

    The resolver dedupes by ``target_id`` upstream, so both ``"React"`` and
    ``"react"`` collapse into a single :class:`ResolvedBacklink` before
    ``_persist_resolved_backlinks`` ever runs. This test pins the end-to-end
    behavior: the composite PK + per-row ``IntegrityError`` catch is a
    defensive belt over the resolver's suspenders, and this test verifies
    they work together (not that the catch branch is exercised — it isn't).
    """
    target = Article(
        id=str(uuid.uuid4()),
        slug="react",
        title="React",
        file_path=str(tmp_path / "react.md"),
        confidence=ConfidenceLevel.SOURCED,
    )
    db_session.add(target)
    await db_session.commit()

    compiler = _compiler_for(tmp_path)
    source = await _make_source(db_session)
    result = _result_with_backlinks("New Article", backlink_suggestions=["React", "react"])
    article = await compiler.save_article(result, source, db_session)

    bl_result = await db_session.execute(select(Backlink).where(Backlink.source_article_id == article.id))
    backlinks = list(bl_result.scalars().all())
    assert len(backlinks) == 1


async def test_save_skips_backlinks_when_no_candidates(db_session, tmp_path) -> None:
    compiler = _compiler_for(tmp_path)
    source = await _make_source(db_session)
    result = _result_with_backlinks("Solo Article", backlink_suggestions=[])
    article = await compiler.save_article(result, source, db_session)

    bl_result = await db_session.execute(select(Backlink).where(Backlink.source_article_id == article.id))
    assert list(bl_result.scalars().all()) == []
