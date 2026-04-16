"""Tests for concept page recompilation change-detection (issue #162).

Verifies that:
1. Concept pages are NOT recompiled when the source set is unchanged.
2. Concept pages ARE recompiled when a new source article is added.
3. ``_replace_article_in_place`` triggers concept page compilation.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wikimind.engine.compiler import Compiler
from wikimind.engine.concept_compiler import ConceptCompiler
from wikimind.models import (
    Article,
    CompilationResult,
    CompletionResponse,
    Concept,
    ConceptKindDef,
    IngestStatus,
    PageType,
    Provider,
    Source,
)
from wikimind.services.taxonomy import _concept_source_set_changed, maybe_trigger_concept_pages


def _fake_concept_resp(name: str = "Test") -> str:
    return json.dumps(
        {
            "title": name,
            "overview": "Overview.",
            "key_themes": ["t1", "t2"],
            "consensus_conflicts": "Agreement.",
            "open_questions": ["Q?"],
            "timeline": "Evolved.",
            "sources_summary": "S1 did X. S2 did Y.",
            "article_body": "## Analysis\n\nBody. " * 20,
            "related_concepts": [],
        }
    )


async def _seed_kind(session, name: str = "topic") -> ConceptKindDef:
    k = ConceptKindDef(
        name=name,
        prompt_template_key=f"concept_synthesis_{name}",
        required_sections=json.dumps(["overview"]),
        linter_rules=json.dumps(["has_summary"]),
    )
    session.add(k)
    await session.commit()
    return k


async def _mk_source_article(session, tmp_path: Path, slug: str, title: str, concepts: list[str]) -> Article:
    d = tmp_path / "wiki" / "test"
    d.mkdir(parents=True, exist_ok=True)
    fp = d / f"{slug}.md"
    fp.write_text(f"# {title}\nSummary text.", encoding="utf-8")
    a = Article(
        slug=slug,
        title=title,
        file_path=str(fp),
        summary="Sum.",
        concept_ids=json.dumps(concepts),
        page_type=PageType.SOURCE,
    )
    session.add(a)
    await session.commit()
    await session.refresh(a)
    return a


def _mock_router(name: str = "ML") -> MagicMock:
    """Return a mock LLM router that produces a valid concept compilation response."""
    fr = CompletionResponse(
        content=_fake_concept_resp(name),
        provider_used=Provider.MOCK,
        model_used="m",
        input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
        latency_ms=0,
    )
    mr = MagicMock()
    mr.complete = AsyncMock(return_value=fr)
    mr.parse_json_response = lambda r: json.loads(r.content)
    return mr


def _settings(tmp_path: Path, min_sources: int = 2) -> SimpleNamespace:
    return SimpleNamespace(
        data_dir=str(tmp_path),
        taxonomy=SimpleNamespace(concept_page_min_sources=min_sources),
    )


@pytest.mark.asyncio
class TestSourceSetUnchangedSkipsRecompilation:
    """Concept pages must NOT be recompiled when the source set is unchanged."""

    async def test_skips_when_source_ids_match(self, db_session, tmp_path):
        """After compiling a concept page, _concept_source_set_changed returns False."""
        await _seed_kind(db_session)
        await _mk_source_article(db_session, tmp_path, "s1", "S1", ["ml"])
        await _mk_source_article(db_session, tmp_path, "s2", "S2", ["ml"])
        concept = Concept(name="ml", description="ML", concept_kind="topic", article_count=2)
        db_session.add(concept)
        await db_session.commit()

        mr = _mock_router()
        settings = _settings(tmp_path)

        # First: compile the concept page so source_ids are stored.
        with (
            patch("wikimind.engine.concept_compiler.get_llm_router", return_value=mr),
            patch("wikimind.engine.concept_compiler.get_settings", return_value=settings),
        ):
            first = await ConceptCompiler().compile_concept_page(concept, db_session)
            assert first is not None
            assert mr.complete.call_count == 1

        # Now the source set is unchanged — change detection should return False.
        assert not await _concept_source_set_changed(concept, db_session)

    async def test_maybe_trigger_skips_unchanged(self, db_session, tmp_path):
        """maybe_trigger_concept_pages does NOT call compile when source set is unchanged."""
        await _seed_kind(db_session)
        await _mk_source_article(db_session, tmp_path, "s1", "S1", ["ml"])
        await _mk_source_article(db_session, tmp_path, "s2", "S2", ["ml"])
        concept = Concept(name="ml", description="ML", concept_kind="topic", article_count=2)
        db_session.add(concept)
        await db_session.commit()

        mr = _mock_router()
        settings = _settings(tmp_path)

        # First: compile the concept page.
        with (
            patch("wikimind.engine.concept_compiler.get_llm_router", return_value=mr),
            patch("wikimind.engine.concept_compiler.get_settings", return_value=settings),
        ):
            first = await ConceptCompiler().compile_concept_page(concept, db_session)
            assert first is not None
            assert mr.complete.call_count == 1

        # Call maybe_trigger_concept_pages — should skip compilation.
        with (
            patch("wikimind.services.taxonomy.get_settings", return_value=settings),
            patch("wikimind.engine.concept_compiler.get_llm_router", return_value=mr),
            patch("wikimind.engine.concept_compiler.get_settings", return_value=settings),
        ):
            compiled = await maybe_trigger_concept_pages(db_session)
            assert compiled == []
            # LLM was not called again.
            assert mr.complete.call_count == 1

    async def test_changed_returns_true_on_first_run(self, db_session, tmp_path):
        """When no concept page exists yet, _concept_source_set_changed returns True."""
        await _mk_source_article(db_session, tmp_path, "s1", "S1", ["ml"])
        await _mk_source_article(db_session, tmp_path, "s2", "S2", ["ml"])
        concept = Concept(name="ml", description="ML", concept_kind="topic", article_count=2)
        db_session.add(concept)
        await db_session.commit()

        assert await _concept_source_set_changed(concept, db_session)


@pytest.mark.asyncio
class TestSourceSetChangedTriggersRecompilation:
    """Concept pages MUST be recompiled when a new source article is added."""

    async def test_changed_returns_true_when_new_source_added(self, db_session, tmp_path):
        await _seed_kind(db_session)
        await _mk_source_article(db_session, tmp_path, "s1", "S1", ["ml"])
        await _mk_source_article(db_session, tmp_path, "s2", "S2", ["ml"])
        concept = Concept(name="ml", description="ML", concept_kind="topic", article_count=2)
        db_session.add(concept)
        await db_session.commit()

        mr = _mock_router()
        settings = _settings(tmp_path)

        # Compile the concept page.
        with (
            patch("wikimind.engine.concept_compiler.get_llm_router", return_value=mr),
            patch("wikimind.engine.concept_compiler.get_settings", return_value=settings),
        ):
            first = await ConceptCompiler().compile_concept_page(concept, db_session)
            assert first is not None

        # Source set is unchanged.
        assert not await _concept_source_set_changed(concept, db_session)

        # Add a new source article.
        await _mk_source_article(db_session, tmp_path, "s3", "S3", ["ml"])

        # Source set has now changed.
        assert await _concept_source_set_changed(concept, db_session)


@pytest.mark.asyncio
class TestReplaceArticleTriggersConceptPages:
    """``_replace_article_in_place`` must trigger concept page compilation."""

    async def test_replace_calls_maybe_trigger(self, db_session, tmp_path):
        """Verify that _replace_article_in_place invokes maybe_trigger_concept_pages."""
        # Create a source.
        source = Source(
            title="Test Source",
            source_type="text",
            source_url="https://example.com",
            status=IngestStatus.PROCESSING,
        )
        db_session.add(source)
        await db_session.commit()
        await db_session.refresh(source)

        # Create an existing article for this source.
        d = tmp_path / "wiki" / "test"
        d.mkdir(parents=True, exist_ok=True)
        fp = d / "test-article.md"
        fp.write_text("# Test\nOld content.", encoding="utf-8")
        existing = Article(
            slug="test-article",
            title="Test Article",
            file_path=str(fp),
            summary="Old summary.",
            source_ids=json.dumps([source.id]),
            concept_ids=json.dumps(["ml"]),
            provider=Provider.MOCK,
            page_type=PageType.SOURCE,
        )
        db_session.add(existing)
        await db_session.commit()
        await db_session.refresh(existing)

        # Build a compilation result.
        result = CompilationResult(
            title="Updated Article",
            summary="New summary.",
            key_claims=[],
            concepts=["ml", "ai"],
            backlink_suggestions=[],
            open_questions=[],
            article_body="## Analysis\n\nBody text. " * 20,
        )

        mock_trigger = AsyncMock(return_value=[])

        # Create a mock session factory that returns a mock context manager.
        mock_concept_session = AsyncMock()
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_concept_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session_cm)

        compiler = Compiler.__new__(Compiler)
        compiler.router = MagicMock()
        compiler.settings = _settings(tmp_path)
        compiler._last_provider_used = Provider.MOCK
        compiler._last_typed_suggestions = {}

        with (
            patch(
                "wikimind.engine.compiler.resolve_backlink_candidates", new_callable=AsyncMock, return_value=([], [])
            ),
            patch("wikimind.engine.compiler.upsert_concepts", new_callable=AsyncMock),
            patch("wikimind.engine.compiler.update_article_counts", new_callable=AsyncMock),
            patch("wikimind.engine.compiler.maybe_trigger_taxonomy_rebuild", new_callable=AsyncMock),
            patch("wikimind.engine.compiler.maybe_trigger_concept_pages", mock_trigger),
            patch("wikimind.engine.compiler.get_session_factory", return_value=mock_factory),
            patch("wikimind.engine.compiler.regenerate_index_md", new_callable=AsyncMock),
            patch("wikimind.engine.compiler.append_log_entry"),
            patch("wikimind.engine.compiler.validate_frontmatter"),
        ):
            await compiler._replace_article_in_place(existing, result, source, db_session)

        # The key assertion: maybe_trigger_concept_pages was called.
        mock_trigger.assert_called_once_with(mock_concept_session)
