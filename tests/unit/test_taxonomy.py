"""Tests for the concept taxonomy service."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import select

from wikimind.models import Article, CompletionResponse, Concept, Provider
from wikimind.services.taxonomy import (
    _exceeds_max_depth,
    _has_cycles,
    _parse_concept_ids,
    maybe_trigger_taxonomy_rebuild,
    rebuild_taxonomy,
    update_article_counts,
    upsert_concepts,
)

# ---------------------------------------------------------------------------
# _parse_concept_ids
# ---------------------------------------------------------------------------


class TestParseConceptIds:
    def test_parses_valid_json(self):
        assert _parse_concept_ids('["a", "b"]') == ["a", "b"]

    def test_returns_empty_for_none(self):
        assert _parse_concept_ids(None) == []

    def test_returns_empty_for_empty_string(self):
        assert _parse_concept_ids("") == []

    def test_returns_empty_for_malformed(self):
        assert _parse_concept_ids("not json") == []

    def test_returns_empty_for_non_list(self):
        assert _parse_concept_ids('"just a string"') == []


# ---------------------------------------------------------------------------
# upsert_concepts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestUpsertConcepts:
    async def test_creates_new_concept(self, db_session):
        concepts = await upsert_concepts(["Machine Learning"], db_session)
        assert len(concepts) == 1
        assert concepts[0].name == "machine-learning"
        assert concepts[0].description == "Machine Learning"

    async def test_idempotent_upsert(self, db_session):
        first = await upsert_concepts(["Machine Learning"], db_session)
        second = await upsert_concepts(["Machine Learning"], db_session)
        assert first[0].id == second[0].id

    async def test_normalization_deduplicates(self, db_session):
        first = await upsert_concepts(["Machine Learning"], db_session)
        second = await upsert_concepts(["machine-learning"], db_session)
        assert first[0].id == second[0].id

    async def test_empty_list_returns_empty(self, db_session):
        concepts = await upsert_concepts([], db_session)
        assert concepts == []

    async def test_multiple_concepts(self, db_session):
        concepts = await upsert_concepts(
            ["Deep Learning", "NLP", "Computer Vision"],
            db_session,
        )
        assert len(concepts) == 3
        names = {c.name for c in concepts}
        assert names == {"deep-learning", "nlp", "computer-vision"}

    async def test_skips_empty_slugified_names(self, db_session):
        # Names that slugify to empty string are skipped
        concepts = await upsert_concepts(["---", "valid-name"], db_session)
        assert len(concepts) == 1
        assert concepts[0].name == "valid-name"

    async def test_preserves_description_on_first_create(self, db_session):
        await upsert_concepts(["Machine Learning"], db_session)
        # Second call with different casing should not overwrite description
        await upsert_concepts(["machine learning"], db_session)
        result = await db_session.execute(select(Concept).where(Concept.name == "machine-learning"))
        concept = result.scalar_one()
        assert concept.description == "Machine Learning"


# ---------------------------------------------------------------------------
# update_article_counts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestUpdateArticleCounts:
    async def test_counts_articles_per_concept(self, db_session, tmp_path):
        # Create concepts
        await upsert_concepts(["ML", "NLP"], db_session)

        # Create articles referencing concepts
        fp1 = tmp_path / "art1.md"
        fp1.write_text("# Art1", encoding="utf-8")
        art1 = Article(
            slug="art1",
            title="Art1",
            file_path=str(fp1),
            concept_ids=json.dumps(["ML", "NLP"]),
        )
        fp2 = tmp_path / "art2.md"
        fp2.write_text("# Art2", encoding="utf-8")
        art2 = Article(
            slug="art2",
            title="Art2",
            file_path=str(fp2),
            concept_ids=json.dumps(["ML"]),
        )
        db_session.add_all([art1, art2])
        await db_session.commit()

        await update_article_counts(db_session)

        result = await db_session.execute(select(Concept))
        concepts = {c.name: c.article_count for c in result.scalars().all()}
        assert concepts["ml"] == 2
        assert concepts["nlp"] == 1

    async def test_resets_count_to_zero_for_unreferenced(self, db_session):
        # Create a concept that no article references
        await upsert_concepts(["orphan-concept"], db_session)

        # Manually set a stale count
        result = await db_session.execute(select(Concept).where(Concept.name == "orphan-concept"))
        concept = result.scalar_one()
        concept.article_count = 5
        db_session.add(concept)
        await db_session.commit()

        await update_article_counts(db_session)

        await db_session.refresh(concept)
        assert concept.article_count == 0


# ---------------------------------------------------------------------------
# maybe_trigger_taxonomy_rebuild
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestMaybeTriggerRebuild:
    async def test_does_not_trigger_below_threshold(self, db_session):
        # Create fewer unparented concepts than the default threshold (5)
        await upsert_concepts(["a", "b"], db_session)
        with patch(
            "wikimind.services.taxonomy.rebuild_taxonomy",
            new_callable=AsyncMock,
        ) as mock_rebuild:
            triggered = await maybe_trigger_taxonomy_rebuild(db_session)
            assert not triggered
            mock_rebuild.assert_not_called()

    async def test_triggers_at_threshold(self, db_session):
        await upsert_concepts(["a", "b", "c", "d", "e"], db_session)
        with patch(
            "wikimind.services.taxonomy.rebuild_taxonomy",
            new_callable=AsyncMock,
        ) as mock_rebuild:
            triggered = await maybe_trigger_taxonomy_rebuild(db_session)
            assert triggered
            mock_rebuild.assert_called_once()


# ---------------------------------------------------------------------------
# Cycle / depth validation
# ---------------------------------------------------------------------------


class TestCycleDetection:
    def test_no_cycles(self):
        mapping = {"a": None, "b": "a", "c": "a"}
        assert not _has_cycles(mapping)

    def test_direct_cycle(self):
        mapping = {"a": "b", "b": "a"}
        assert _has_cycles(mapping)

    def test_indirect_cycle(self):
        mapping = {"a": "b", "b": "c", "c": "a"}
        assert _has_cycles(mapping)

    def test_self_cycle(self):
        mapping = {"a": "a"}
        assert _has_cycles(mapping)


class TestMaxDepth:
    def test_within_limit(self):
        mapping = {"a": None, "b": "a", "c": "b"}
        assert not _exceeds_max_depth(mapping, 3)

    def test_exceeds_limit(self):
        mapping = {"a": None, "b": "a", "c": "b", "d": "c"}
        assert _exceeds_max_depth(mapping, 3)

    def test_flat_hierarchy(self):
        mapping = {"a": None, "b": None, "c": None}
        assert not _exceeds_max_depth(mapping, 1)


# ---------------------------------------------------------------------------
# rebuild_taxonomy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRebuildTaxonomy:
    async def test_rebuild_applies_hierarchy(self, db_session):
        """LLM response is applied as parent-child relationships."""
        await upsert_concepts(["ml", "deep-learning", "nlp"], db_session)

        llm_response = json.dumps(
            [
                {"name": "ml", "parent": None},
                {"name": "deep-learning", "parent": "ml"},
                {"name": "nlp", "parent": "ml"},
            ]
        )
        fake_resp = CompletionResponse(
            content=llm_response,
            provider_used=Provider.MOCK,
            model_used="mock-1",
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            latency_ms=0,
        )
        mock_router = AsyncMock()
        mock_router.complete = AsyncMock(return_value=fake_resp)
        mock_router.parse_json_response = lambda r: json.loads(r.content)

        with patch(
            "wikimind.services.taxonomy.get_llm_router",
            return_value=mock_router,
        ):
            await rebuild_taxonomy(db_session)

        result = await db_session.execute(select(Concept))
        concepts = {c.name: c for c in result.scalars().all()}
        assert concepts["ml"].parent_id is None
        assert concepts["deep-learning"].parent_id == concepts["ml"].id
        assert concepts["nlp"].parent_id == concepts["ml"].id

    async def test_rebuild_rejects_cycles(self, db_session):
        """LLM response with cycles is rejected and parent_ids stay None."""
        await upsert_concepts(["a", "b"], db_session)

        llm_response = json.dumps(
            [
                {"name": "a", "parent": "b"},
                {"name": "b", "parent": "a"},
            ]
        )
        fake_resp = CompletionResponse(
            content=llm_response,
            provider_used=Provider.MOCK,
            model_used="mock-1",
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            latency_ms=0,
        )
        mock_router = AsyncMock()
        mock_router.complete = AsyncMock(return_value=fake_resp)
        mock_router.parse_json_response = lambda r: json.loads(r.content)

        with patch(
            "wikimind.services.taxonomy.get_llm_router",
            return_value=mock_router,
        ):
            await rebuild_taxonomy(db_session)

        result = await db_session.execute(select(Concept))
        for concept in result.scalars().all():
            assert concept.parent_id is None

    async def test_rebuild_skips_empty_concepts(self, db_session):
        """No-op when the concept table is empty."""
        mock_router = AsyncMock()
        with patch(
            "wikimind.services.taxonomy.get_llm_router",
            return_value=mock_router,
        ):
            await rebuild_taxonomy(db_session)
            mock_router.complete.assert_not_called()

    async def test_rebuild_rejects_excessive_depth(self, db_session):
        """LLM response exceeding max_hierarchy_depth is rejected."""
        await upsert_concepts(["a", "b", "c", "d"], db_session)

        # Chain: a -> b -> c -> d (depth 4, exceeds default max 3)
        llm_response = json.dumps(
            [
                {"name": "a", "parent": None},
                {"name": "b", "parent": "a"},
                {"name": "c", "parent": "b"},
                {"name": "d", "parent": "c"},
            ]
        )
        fake_resp = CompletionResponse(
            content=llm_response,
            provider_used=Provider.MOCK,
            model_used="mock-1",
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            latency_ms=0,
        )
        mock_router = AsyncMock()
        mock_router.complete = AsyncMock(return_value=fake_resp)
        mock_router.parse_json_response = lambda r: json.loads(r.content)

        with patch(
            "wikimind.services.taxonomy.get_llm_router",
            return_value=mock_router,
        ):
            await rebuild_taxonomy(db_session)

        result = await db_session.execute(select(Concept))
        for concept in result.scalars().all():
            assert concept.parent_id is None
