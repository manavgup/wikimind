"""Tests for schema overhaul Phase 1 — enums, tables, Pydantic models, and registry."""

import json
from datetime import datetime

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlmodel import select

from wikimind.engine.concept_kind_registry import (
    PROMPT_TEMPLATES,
    RegistryTemplateMismatchError,
    seed_builtin_kinds,
    validate_registry_against_prompts,
)
from wikimind.models import (
    AnswerCompilationResult,
    AnswerFrontmatter,
    Article,
    Backlink,
    Concept,
    ConceptCompilationResult,
    ConceptFrontmatter,
    ConceptKindDef,
    IndexFrontmatter,
    MetaFrontmatter,
    PageType,
    Provider,
    RelationType,
    SourceCompilationResult,
    SourceFrontmatter,
    SourceType,
    TypedBacklinkSuggestion,
)


class TestPageTypeEnum:
    def test_values(self):
        assert PageType.SOURCE == "source"
        assert PageType.CONCEPT == "concept"
        assert PageType.ANSWER == "answer"
        assert PageType.INDEX == "index"
        assert PageType.META == "meta"

    def test_member_count(self):
        assert len(PageType) == 5


class TestRelationTypeEnum:
    def test_values(self):
        assert RelationType.REFERENCES == "references"
        assert RelationType.CONTRADICTS == "contradicts"
        assert RelationType.EXTENDS == "extends"
        assert RelationType.SUPERSEDES == "supersedes"
        assert RelationType.SYNTHESIZES == "synthesizes"
        assert RelationType.RELATED_TO == "related_to"

    def test_member_count(self):
        assert len(RelationType) == 6


class TestConceptKindDef:
    def test_create(self):
        kind = ConceptKindDef(
            name="topic",
            prompt_template_key="concept_synthesis_topic",
            required_sections=json.dumps(["overview", "key_themes"]),
            linter_rules=json.dumps(["has_summary"]),
            description="General topic",
        )
        assert kind.name == "topic"
        assert json.loads(kind.required_sections) == ["overview", "key_themes"]

    async def test_persist_and_read(self, db_session: AsyncSession):
        kind = ConceptKindDef(
            name="test-kind",
            prompt_template_key="test_key",
            required_sections=json.dumps(["a", "b"]),
            linter_rules=json.dumps(["rule1"]),
            description="for testing",
        )
        db_session.add(kind)
        await db_session.commit()
        result = await db_session.execute(select(ConceptKindDef).where(ConceptKindDef.name == "test-kind"))
        assert result.scalar_one().prompt_template_key == "test_key"

    async def test_primary_key_is_name(self, db_session: AsyncSession):
        kind = ConceptKindDef(name="unique-kind", prompt_template_key="k", required_sections="[]", linter_rules="[]")
        db_session.add(kind)
        await db_session.commit()
        result = await db_session.execute(select(ConceptKindDef).where(ConceptKindDef.name == "unique-kind"))
        assert result.scalar_one() is not None


class TestArticlePageType:
    def test_default_page_type(self):
        assert Article(slug="test", title="Test", file_path="/tmp/test.md").page_type == PageType.SOURCE

    def test_explicit_page_type(self):
        assert (
            Article(slug="cp", title="LR", file_path="/tmp/lr.md", page_type=PageType.CONCEPT).page_type
            == PageType.CONCEPT
        )

    async def test_persist_page_type(self, db_session: AsyncSession):
        article = Article(slug="answer-page", title="Filed", file_path="/tmp/a.md", page_type=PageType.ANSWER)
        db_session.add(article)
        await db_session.commit()
        result = await db_session.execute(select(Article).where(Article.slug == "answer-page"))
        assert result.scalar_one().page_type == PageType.ANSWER


class TestBacklinkRelationType:
    def test_default_relation_type(self):
        assert Backlink(source_article_id="a", target_article_id="b").relation_type == RelationType.REFERENCES

    def test_explicit_relation_type(self):
        assert (
            Backlink(source_article_id="a", target_article_id="b", relation_type=RelationType.CONTRADICTS).relation_type
            == RelationType.CONTRADICTS
        )

    def test_resolution_fields_default_none(self):
        bl = Backlink(source_article_id="a", target_article_id="b")
        assert (
            bl.resolution is None and bl.resolution_note is None and bl.resolved_at is None and bl.resolved_by is None
        )

    def test_resolution_fields(self):
        now = datetime(2026, 4, 13, 12, 0, 0)
        bl = Backlink(
            source_article_id="a",
            target_article_id="b",
            relation_type=RelationType.CONTRADICTS,
            resolution="source_a_wins",
            resolution_note="Newer data",
            resolved_at=now,
            resolved_by="admin@example.com",
        )
        assert bl.resolution == "source_a_wins" and bl.resolved_at == now

    async def test_persist_typed_backlink(self, db_session: AsyncSession):
        a1, a2 = (
            Article(slug="src-a", title="A", file_path="/tmp/a.md"),
            Article(slug="src-b", title="B", file_path="/tmp/b.md"),
        )
        db_session.add_all([a1, a2])
        await db_session.flush()
        bl = Backlink(
            source_article_id=a1.id, target_article_id=a2.id, relation_type=RelationType.EXTENDS, context="A extends B"
        )
        db_session.add(bl)
        await db_session.commit()
        result = await db_session.execute(
            select(Backlink).where(Backlink.source_article_id == a1.id, Backlink.target_article_id == a2.id)
        )
        assert result.scalar_one().relation_type == RelationType.EXTENDS


class TestConceptKind:
    def test_default_concept_kind(self):
        assert Concept(name="test-concept").concept_kind == "topic"

    def test_explicit_concept_kind(self):
        assert Concept(name="alan-turing", concept_kind="person").concept_kind == "person"

    async def test_persist_concept_kind(self, db_session: AsyncSession):
        concept = Concept(name="openai", concept_kind="organization")
        db_session.add(concept)
        await db_session.commit()
        result = await db_session.execute(select(Concept).where(Concept.name == "openai"))
        assert result.scalar_one().concept_kind == "organization"


class TestSourceFrontmatter:
    def test_valid(self):
        assert (
            SourceFrontmatter(
                title="T", slug="t", source_id="abc", source_type=SourceType.URL, compiled=datetime(2026, 4, 13)
            ).page_type
            == PageType.SOURCE
        )

    def test_missing_required_field(self):
        with pytest.raises(ValidationError):
            SourceFrontmatter(title="T", slug="t", compiled=datetime(2026, 4, 13))

    def test_optional_fields(self):
        fm = SourceFrontmatter(
            title="T",
            slug="t",
            source_id="abc",
            source_type=SourceType.PDF,
            compiled=datetime(2026, 4, 13),
            concepts=["ml", "ai"],
            provider=Provider.ANTHROPIC,
        )
        assert fm.concepts == ["ml", "ai"]


class TestConceptFrontmatter:
    def test_valid(self):
        assert ConceptFrontmatter(title="LLM", slug="llm", concept_id="uuid-123").page_type == PageType.CONCEPT

    def test_missing_concept_id(self):
        with pytest.raises(ValidationError):
            ConceptFrontmatter(title="Bad", slug="bad")

    def test_with_synthesis_data(self):
        assert (
            ConceptFrontmatter(
                title="L", slug="l", concept_id="u", synthesized_from=["a1", "a2"], source_count=2
            ).source_count
            == 2
        )


class TestAnswerFrontmatter:
    def test_valid(self):
        assert (
            AnswerFrontmatter(title="Q?", slug="q", conversation_id="conv-123", turn_indices=[0, 1]).page_type
            == PageType.ANSWER
        )

    def test_missing_conversation_id(self):
        with pytest.raises(ValidationError):
            AnswerFrontmatter(title="Bad", slug="bad")


class TestIndexFrontmatter:
    def test_valid_global(self):
        assert IndexFrontmatter(title="Index", slug="index", scope="global").page_type == PageType.INDEX

    def test_valid_concept_scope(self):
        assert IndexFrontmatter(title="LLM", slug="llm-idx", scope="concept", concept_id="uuid").concept_id == "uuid"

    def test_missing_scope(self):
        with pytest.raises(ValidationError):
            IndexFrontmatter(title="Bad", slug="bad")


class TestMetaFrontmatter:
    def test_valid(self):
        assert MetaFrontmatter(title="Health", slug="health").page_type == PageType.META

    def test_with_generated(self):
        assert MetaFrontmatter(title="H", slug="h", generated=datetime(2026, 4, 13)).generated == datetime(2026, 4, 13)


class TestTypedBacklinkSuggestion:
    def test_valid(self):
        assert (
            TypedBacklinkSuggestion(target="x", relation_type=RelationType.EXTENDS).relation_type
            == RelationType.EXTENDS
        )

    def test_default_relation_type(self):
        assert TypedBacklinkSuggestion(target="x").relation_type == RelationType.REFERENCES

    def test_missing_target(self):
        with pytest.raises(ValidationError):
            TypedBacklinkSuggestion()

    def test_invalid_relation_type(self):
        with pytest.raises(ValidationError):
            TypedBacklinkSuggestion(target="x", relation_type="not_a_type")


class TestSourceCompilationResult:
    def test_inherits(self):
        r = SourceCompilationResult(
            title="T",
            summary="S",
            key_claims=[],
            concepts=["ml"],
            backlink_suggestions=["o"],
            open_questions=["?"],
            article_body="# T",
        )
        assert r.page_type == PageType.SOURCE


class TestConceptCompilationResult:
    def test_valid(self):
        r = ConceptCompilationResult(
            title="L",
            overview="O",
            key_themes=["cot", "tot"],
            consensus_conflicts="C",
            open_questions=["?"],
            timeline="T",
            sources_summary="S",
            article_body="# L",
        )
        assert r.page_type == PageType.CONCEPT and len(r.key_themes) == 2


class TestAnswerCompilationResult:
    def test_valid(self):
        r = AnswerCompilationResult(
            title="Q", question="Q?", answer="A", sources_cited=["nn"], concepts=["dl"], article_body="# Q"
        )
        assert r.page_type == PageType.ANSWER


class TestSeedBuiltinKinds:
    async def test_creates_five_kinds(self, async_engine):
        factory = async_sessionmaker(async_engine, expire_on_commit=False)
        async with factory() as session:
            await seed_builtin_kinds(session)
        async with factory() as session:
            result = await session.execute(select(ConceptKindDef))
            assert {k.name for k in result.scalars().all()} == {"topic", "person", "organization", "product", "paper"}

    async def test_idempotent(self, async_engine):
        factory = async_sessionmaker(async_engine, expire_on_commit=False)
        async with factory() as session:
            await seed_builtin_kinds(session)
        async with factory() as session:
            await seed_builtin_kinds(session)
        async with factory() as session:
            assert len((await session.execute(select(ConceptKindDef))).scalars().all()) == 5

    async def test_topic_has_correct_sections(self, async_engine):
        factory = async_sessionmaker(async_engine, expire_on_commit=False)
        async with factory() as session:
            await seed_builtin_kinds(session)
        async with factory() as session:
            topic = (await session.execute(select(ConceptKindDef).where(ConceptKindDef.name == "topic"))).scalar_one()
            assert "overview" in json.loads(topic.required_sections)

    async def test_person_has_correct_template_key(self, async_engine):
        factory = async_sessionmaker(async_engine, expire_on_commit=False)
        async with factory() as session:
            await seed_builtin_kinds(session)
        async with factory() as session:
            person = (await session.execute(select(ConceptKindDef).where(ConceptKindDef.name == "person"))).scalar_one()
            assert person.prompt_template_key == "concept_synthesis_person"


class TestValidateRegistryAgainstPrompts:
    async def test_passes_with_valid_templates(self, async_engine):
        factory = async_sessionmaker(async_engine, expire_on_commit=False)
        async with factory() as session:
            await seed_builtin_kinds(session)
        async with factory() as session:
            await validate_registry_against_prompts(session)

    async def test_fails_with_missing_template(self, async_engine, monkeypatch):
        factory = async_sessionmaker(async_engine, expire_on_commit=False)
        async with factory() as session:
            await seed_builtin_kinds(session)
        modified = {k: v for k, v in PROMPT_TEMPLATES.items() if k != "concept_synthesis_topic"}
        monkeypatch.setattr("wikimind.engine.concept_kind_registry.PROMPT_TEMPLATES", modified)
        async with factory() as session:
            with pytest.raises(RegistryTemplateMismatchError, match="concept_synthesis_topic"):
                await validate_registry_against_prompts(session)

    async def test_passes_with_empty_registry(self, async_engine):
        factory = async_sessionmaker(async_engine, expire_on_commit=False)
        async with factory() as session:
            await validate_registry_against_prompts(session)
