"""Tests for the registry-driven concept page compiler."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import select

from wikimind.engine.concept_compiler import (
    PROMPT_TEMPLATES,
    ConceptCompiler,
    _collect_contradictions,
    _collect_source_articles,
    get_prompt_template,
)
from wikimind.models import (
    Article,
    Backlink,
    CompletionResponse,
    Concept,
    ConceptCompilationResult,
    ConceptKindDef,
    PageType,
    Provider,
    RelationType,
)


def _fake_resp(name="Test"):
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
            "related_concepts": ["rel"],
        }
    )


async def _seed_kind(s, name="topic"):
    k = ConceptKindDef(
        name=name,
        prompt_template_key=f"concept_synthesis_{name}",
        required_sections=json.dumps(["overview"]),
        linter_rules=json.dumps(["has_summary"]),
    )
    s.add(k)
    await s.commit()
    return k


async def _mk_art(s, tp, slug, title, concepts, summary="Sum."):
    d = tp / "wiki" / "test"
    d.mkdir(parents=True, exist_ok=True)
    fp = d / f"{slug}.md"
    fp.write_text(f"# {title}\n{summary}", encoding="utf-8")
    a = Article(
        slug=slug,
        title=title,
        file_path=str(fp),
        summary=summary,
        concept_ids=json.dumps(concepts),
        page_type=PageType.SOURCE,
    )
    s.add(a)
    await s.commit()
    await s.refresh(a)
    return a


class TestPromptTemplates:
    def test_all_exist(self):
        for k in ["topic", "person", "org", "product", "paper"]:
            assert get_prompt_template(f"concept_synthesis_{k}") is not None

    def test_unknown_none(self):
        assert get_prompt_template("nope") is None

    def test_placeholders(self):
        for _k, t in PROMPT_TEMPLATES.items():
            assert "{concept_name}" in t and "{source_material}" in t


@pytest.mark.asyncio
class TestCollectSourceArticles:
    async def test_collects_matching(self, db_session, tmp_path):
        a1 = await _mk_art(db_session, tmp_path, "a1", "A1", ["ml", "ai"])
        a2 = await _mk_art(db_session, tmp_path, "a2", "A2", ["ml"])
        await _mk_art(db_session, tmp_path, "a3", "A3", ["bio"])
        r = await _collect_source_articles("ml", db_session)
        assert {x.id for x in r} == {a1.id, a2.id}

    async def test_excludes_concept(self, db_session, tmp_path):
        await _mk_art(db_session, tmp_path, "s1", "S1", ["ml"])
        d = tmp_path / "wiki" / "ml"
        d.mkdir(parents=True, exist_ok=True)
        fp = d / "c.md"
        fp.write_text("# C", encoding="utf-8")
        ca = Article(
            slug="concept-ml", title="ML", file_path=str(fp), concept_ids=json.dumps(["ml"]), page_type=PageType.CONCEPT
        )
        db_session.add(ca)
        await db_session.commit()
        r = await _collect_source_articles("ml", db_session)
        assert len(r) == 1 and r[0].page_type == PageType.SOURCE

    async def test_normalized(self, db_session, tmp_path):
        await _mk_art(db_session, tmp_path, "a1", "A1", ["Machine Learning"])
        assert len(await _collect_source_articles("machine-learning", db_session)) == 1


@pytest.mark.asyncio
class TestSynthesizesLinks:
    async def test_creates(self, db_session, tmp_path):
        await _seed_kind(db_session)
        a1 = await _mk_art(db_session, tmp_path, "s1", "S1", ["ml"])
        a2 = await _mk_art(db_session, tmp_path, "s2", "S2", ["ml"])
        c = Concept(name="ml", description="ML", concept_kind="topic")
        db_session.add(c)
        await db_session.commit()
        fr = CompletionResponse(
            content=_fake_resp("ML"),
            provider_used=Provider.MOCK,
            model_used="m",
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            latency_ms=0,
        )
        mr = AsyncMock()
        mr.complete = AsyncMock(return_value=fr)
        mr.parse_json_response = lambda r: json.loads(r.content)
        with (
            patch("wikimind.engine.concept_compiler.get_llm_router", return_value=mr),
            patch(
                "wikimind.engine.concept_compiler.get_settings",
                return_value=SimpleNamespace(
                    data_dir=str(tmp_path), taxonomy=SimpleNamespace(concept_page_min_sources=2)
                ),
            ),
        ):
            art = await ConceptCompiler().compile_concept_page(c, db_session)
        assert art is not None and art.page_type == PageType.CONCEPT
        res = await db_session.execute(
            select(Backlink).where(
                Backlink.source_article_id == art.id, Backlink.relation_type == RelationType.SYNTHESIZES
            )
        )
        links = list(res.scalars().all())
        assert len(links) == 2
        assert {bl.target_article_id for bl in links} == {a1.id, a2.id}


@pytest.mark.asyncio
class TestConceptPageOutput:
    async def test_writes_md(self, db_session, tmp_path):
        await _seed_kind(db_session)
        await _mk_art(db_session, tmp_path, "s1", "S1", ["ml"])
        await _mk_art(db_session, tmp_path, "s2", "S2", ["ml"])
        c = Concept(name="ml", description="ML", concept_kind="topic")
        db_session.add(c)
        await db_session.commit()
        fr = CompletionResponse(
            content=_fake_resp("ML"),
            provider_used=Provider.MOCK,
            model_used="m",
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            latency_ms=0,
        )
        mr = AsyncMock()
        mr.complete = AsyncMock(return_value=fr)
        mr.parse_json_response = lambda r: json.loads(r.content)
        with (
            patch("wikimind.engine.concept_compiler.get_llm_router", return_value=mr),
            patch(
                "wikimind.engine.concept_compiler.get_settings",
                return_value=SimpleNamespace(
                    data_dir=str(tmp_path), taxonomy=SimpleNamespace(concept_page_min_sources=2)
                ),
            ),
        ):
            art = await ConceptCompiler().compile_concept_page(c, db_session)
        assert art is not None
        content = (Path(tmp_path) / "wiki" / art.file_path).read_text(encoding="utf-8")
        assert "page_type: concept" in content
        for s in [
            "## Overview",
            "## Key Themes",
            "## Consensus & Conflicts",
            "## Open Questions",
            "## Timeline",
            "## Sources",
        ]:
            assert s in content


@pytest.mark.asyncio
class TestTriggerThreshold:
    async def test_below_min(self, db_session, tmp_path):
        await _seed_kind(db_session)
        await _mk_art(db_session, tmp_path, "s1", "S1", ["ml"])
        c = Concept(name="ml", description="ML", concept_kind="topic")
        db_session.add(c)
        await db_session.commit()
        mr = AsyncMock()
        with (
            patch("wikimind.engine.concept_compiler.get_llm_router", return_value=mr),
            patch(
                "wikimind.engine.concept_compiler.get_settings",
                return_value=SimpleNamespace(
                    data_dir=str(tmp_path), taxonomy=SimpleNamespace(concept_page_min_sources=2)
                ),
            ),
        ):
            assert await ConceptCompiler().compile_concept_page(c, db_session) is None
        mr.complete.assert_not_called()

    async def test_at_min(self, db_session, tmp_path):
        await _seed_kind(db_session)
        await _mk_art(db_session, tmp_path, "s1", "S1", ["ml"])
        await _mk_art(db_session, tmp_path, "s2", "S2", ["ml"])
        c = Concept(name="ml", description="ML", concept_kind="topic")
        db_session.add(c)
        await db_session.commit()
        fr = CompletionResponse(
            content=_fake_resp("ML"),
            provider_used=Provider.MOCK,
            model_used="m",
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            latency_ms=0,
        )
        mr = AsyncMock()
        mr.complete = AsyncMock(return_value=fr)
        mr.parse_json_response = lambda r: json.loads(r.content)
        with (
            patch("wikimind.engine.concept_compiler.get_llm_router", return_value=mr),
            patch(
                "wikimind.engine.concept_compiler.get_settings",
                return_value=SimpleNamespace(
                    data_dir=str(tmp_path), taxonomy=SimpleNamespace(concept_page_min_sources=2)
                ),
            ),
        ):
            assert await ConceptCompiler().compile_concept_page(c, db_session) is not None
        mr.complete.assert_called_once()

    async def test_high_threshold(self, db_session, tmp_path):
        await _seed_kind(db_session)
        await _mk_art(db_session, tmp_path, "s1", "S1", ["ml"])
        await _mk_art(db_session, tmp_path, "s2", "S2", ["ml"])
        c = Concept(name="ml", description="ML", concept_kind="topic")
        db_session.add(c)
        await db_session.commit()
        mr = AsyncMock()
        with (
            patch("wikimind.engine.concept_compiler.get_llm_router", return_value=mr),
            patch(
                "wikimind.engine.concept_compiler.get_settings",
                return_value=SimpleNamespace(
                    data_dir=str(tmp_path), taxonomy=SimpleNamespace(concept_page_min_sources=5)
                ),
            ),
        ):
            assert await ConceptCompiler().compile_concept_page(c, db_session) is None


@pytest.mark.asyncio
class TestWithMockedLLM:
    async def test_kind_selects_template(self, db_session, tmp_path):
        await _seed_kind(db_session, name="person")
        await _mk_art(db_session, tmp_path, "s1", "S1", ["k"])
        await _mk_art(db_session, tmp_path, "s2", "S2", ["k"])
        c = Concept(name="k", description="K", concept_kind="person")
        db_session.add(c)
        await db_session.commit()
        fr = CompletionResponse(
            content=_fake_resp("K"),
            provider_used=Provider.MOCK,
            model_used="m",
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            latency_ms=0,
        )
        mr = AsyncMock()
        mr.complete = AsyncMock(return_value=fr)
        mr.parse_json_response = lambda r: json.loads(r.content)
        with (
            patch("wikimind.engine.concept_compiler.get_llm_router", return_value=mr),
            patch(
                "wikimind.engine.concept_compiler.get_settings",
                return_value=SimpleNamespace(
                    data_dir=str(tmp_path), taxonomy=SimpleNamespace(concept_page_min_sources=2)
                ),
            ),
        ):
            art = await ConceptCompiler().compile_concept_page(c, db_session)
        assert art is not None
        assert "person" in mr.complete.call_args[0][0].system.lower()

    async def test_fallback_to_topic(self, db_session, tmp_path):
        await _seed_kind(db_session, name="topic")
        await _mk_art(db_session, tmp_path, "s1", "S1", ["x"])
        await _mk_art(db_session, tmp_path, "s2", "S2", ["x"])
        c = Concept(name="x", description="X", concept_kind="custom")
        db_session.add(c)
        await db_session.commit()
        fr = CompletionResponse(
            content=_fake_resp("X"),
            provider_used=Provider.MOCK,
            model_used="m",
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            latency_ms=0,
        )
        mr = AsyncMock()
        mr.complete = AsyncMock(return_value=fr)
        mr.parse_json_response = lambda r: json.loads(r.content)
        with (
            patch("wikimind.engine.concept_compiler.get_llm_router", return_value=mr),
            patch(
                "wikimind.engine.concept_compiler.get_settings",
                return_value=SimpleNamespace(
                    data_dir=str(tmp_path), taxonomy=SimpleNamespace(concept_page_min_sources=2)
                ),
            ),
        ):
            assert await ConceptCompiler().compile_concept_page(c, db_session) is not None

    async def test_replaces_existing(self, db_session, tmp_path):
        await _seed_kind(db_session)
        await _mk_art(db_session, tmp_path, "s1", "S1", ["ml"])
        await _mk_art(db_session, tmp_path, "s2", "S2", ["ml"])
        c = Concept(name="ml", description="ML", concept_kind="topic")
        db_session.add(c)
        await db_session.commit()
        fr = CompletionResponse(
            content=_fake_resp("ML"),
            provider_used=Provider.MOCK,
            model_used="m",
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            latency_ms=0,
        )
        mr = AsyncMock()
        mr.complete = AsyncMock(return_value=fr)
        mr.parse_json_response = lambda r: json.loads(r.content)
        s = SimpleNamespace(data_dir=str(tmp_path), taxonomy=SimpleNamespace(concept_page_min_sources=2))
        with (
            patch("wikimind.engine.concept_compiler.get_llm_router", return_value=mr),
            patch("wikimind.engine.concept_compiler.get_settings", return_value=s),
        ):
            cc = ConceptCompiler()
            first = await cc.compile_concept_page(c, db_session)
            second = await cc.compile_concept_page(c, db_session)
        assert second.id == first.id


@pytest.mark.asyncio
class TestContradictionSurfacing:
    async def test_empty(self, db_session):
        assert await _collect_contradictions(["a", "b"], db_session) == ""

    async def test_unresolved(self, db_session, tmp_path):
        a1 = await _mk_art(db_session, tmp_path, "s1", "S1", ["ml"])
        a2 = await _mk_art(db_session, tmp_path, "s2", "S2", ["ml"])
        db_session.add(
            Backlink(
                source_article_id=a1.id,
                target_article_id=a2.id,
                relation_type=RelationType.CONTRADICTS,
                context="A vs B",
            )
        )
        await db_session.commit()
        assert "UNRESOLVED" in await _collect_contradictions([a1.id, a2.id], db_session)

    async def test_resolved(self, db_session, tmp_path):
        a1 = await _mk_art(db_session, tmp_path, "s1", "S1", ["ml"])
        a2 = await _mk_art(db_session, tmp_path, "s2", "S2", ["ml"])
        db_session.add(
            Backlink(
                source_article_id=a1.id,
                target_article_id=a2.id,
                relation_type=RelationType.CONTRADICTS,
                context="A vs B",
                resolution="source_a_wins",
                resolution_note="Stronger",
            )
        )
        await db_session.commit()
        r = await _collect_contradictions([a1.id, a2.id], db_session)
        assert "RESOLVED" in r and "source_a_wins" in r


class TestConceptCompilationResult:
    def test_valid(self):
        r = ConceptCompilationResult(**json.loads(_fake_resp("T")))
        assert r.title == "T" and r.page_type == PageType.CONCEPT

    def test_related_default(self):
        d = json.loads(_fake_resp("T"))
        del d["related_concepts"]
        assert ConceptCompilationResult(**d).related_concepts == []
