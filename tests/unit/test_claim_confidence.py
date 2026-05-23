"""Tests for per-claim confidence scoring (issue #465).

Covers:
- compute_claim_confidence() pure function
- aggregate_claim_confidence() pure function
- CompiledClaim.confidence_score persistence
- Article.confidence_score aggregated from claims
- GET /api/wiki/articles/{id}/claims endpoint
"""

from __future__ import annotations

import json
import math
import uuid

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from tests.conftest import TEST_USER_ID
from wikimind.engine.confidence import (
    aggregate_claim_confidence,
    compute_claim_confidence,
)
from wikimind.models import (
    Article,
    CompiledClaim,
    Source,
)
from wikimind.services.citation import CitationService
from wikimind.services.wiki import WikiService


def _uid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Pure function tests
# ---------------------------------------------------------------------------


class TestComputeClaimConfidence:
    """Verify compute_claim_confidence math."""

    def test_sourced_single_source(self) -> None:
        # baseline 0.8 + 0.2 * min(1, 1/4) = 0.8 + 0.05 = 0.85
        score = compute_claim_confidence("sourced", source_count=1)
        assert math.isclose(score, 0.85, abs_tol=1e-9)

    def test_sourced_four_sources_saturates(self) -> None:
        # baseline 0.8 + 0.2 * 1.0 = 1.0
        score = compute_claim_confidence("sourced", source_count=4)
        assert math.isclose(score, 1.0, abs_tol=1e-9)

    def test_sourced_ten_sources_clamped(self) -> None:
        # Cannot exceed 1.0
        score = compute_claim_confidence("sourced", source_count=10)
        assert score == 1.0

    def test_mixed_single_source(self) -> None:
        # baseline 0.5 + 0.2 * 0.25 = 0.55
        score = compute_claim_confidence("mixed", source_count=1)
        assert math.isclose(score, 0.55, abs_tol=1e-9)

    def test_inferred_no_sources(self) -> None:
        # baseline 0.3 + 0.2 * 0.0 = 0.3
        score = compute_claim_confidence("inferred", source_count=0)
        assert math.isclose(score, 0.3, abs_tol=1e-9)

    def test_opinion_single_source(self) -> None:
        # baseline 0.2 + 0.2 * 0.25 = 0.25
        score = compute_claim_confidence("opinion", source_count=1)
        assert math.isclose(score, 0.25, abs_tol=1e-9)

    def test_unknown_level_uses_default(self) -> None:
        # unknown level -> default baseline 0.3
        score = compute_claim_confidence("unknown_level", source_count=0)
        assert math.isclose(score, 0.3, abs_tol=1e-9)

    def test_negative_source_count(self) -> None:
        # Negative treated as zero
        score = compute_claim_confidence("sourced", source_count=-5)
        assert math.isclose(score, 0.8, abs_tol=1e-9)

    def test_always_in_unit_interval(self) -> None:
        for level in ("sourced", "mixed", "inferred", "opinion"):
            for sc in (-1, 0, 1, 4, 100):
                v = compute_claim_confidence(level, sc)
                assert 0.0 <= v <= 1.0


class TestAggregateClaimConfidence:
    """Verify aggregate_claim_confidence math."""

    def test_empty_returns_default(self) -> None:
        assert aggregate_claim_confidence([]) == 0.5

    def test_single_score(self) -> None:
        assert aggregate_claim_confidence([0.8]) == 0.8

    def test_mean_of_scores(self) -> None:
        result = aggregate_claim_confidence([0.6, 0.8, 1.0])
        assert math.isclose(result, 0.8, abs_tol=1e-9)

    def test_clamped_to_unit(self) -> None:
        # Even with edge values the result stays in [0, 1]
        result = aggregate_claim_confidence([0.0, 1.0])
        assert 0.0 <= result <= 1.0


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------


class TestCitationServiceGetClaims:
    """Verify CitationService.get_article_claims."""

    @pytest.mark.asyncio
    async def test_article_not_found(self, db_session: AsyncSession) -> None:
        service = CitationService()
        wiki_service = WikiService()
        with pytest.raises(Exception, match="Article not found"):
            await service.get_article_claims(
                "nonexistent",
                db_session,
                user_id=TEST_USER_ID,
                wiki_service=wiki_service,
            )

    @pytest.mark.asyncio
    async def test_article_with_no_claims(self, db_session: AsyncSession) -> None:
        article_id = _uid()
        article = Article(
            id=article_id,
            user_id=TEST_USER_ID,
            slug="no-claims-article",
            title="No Claims Article",
            file_path="wiki/no-claims.md",
            confidence_score=0.5,
        )
        db_session.add(article)
        await db_session.flush()

        service = CitationService()
        wiki_service = WikiService()
        result = await service.get_article_claims(
            article_id,
            db_session,
            user_id=TEST_USER_ID,
            wiki_service=wiki_service,
        )

        assert result.article_id == article_id
        assert result.article_title == "No Claims Article"
        assert result.article_confidence_score == 0.5
        assert result.claims == []

    @pytest.mark.asyncio
    async def test_article_with_claims(self, db_session: AsyncSession) -> None:
        source_id = _uid()
        source = Source(
            id=source_id,
            user_id=TEST_USER_ID,
            source_type="url",
            title="Test Source",
        )
        db_session.add(source)
        await db_session.flush()

        article_id = _uid()
        article = Article(
            id=article_id,
            user_id=TEST_USER_ID,
            slug="claims-article",
            title="Claims Article",
            file_path="wiki/claims.md",
            confidence_score=0.85,
        )
        db_session.add(article)
        await db_session.flush()

        claim = CompiledClaim(
            id=_uid(),
            article_id=article_id,
            user_id=TEST_USER_ID,
            text="Neural networks are effective.",
            confidence_level="sourced",
            confidence_score=0.85,
            source_ids=json.dumps([source_id]),
        )
        db_session.add(claim)
        await db_session.flush()

        service = CitationService()
        wiki_service = WikiService()
        result = await service.get_article_claims(
            article_id,
            db_session,
            user_id=TEST_USER_ID,
            wiki_service=wiki_service,
        )

        assert result.article_id == article_id
        assert result.article_title == "Claims Article"
        assert result.article_confidence_score == 0.85
        assert len(result.claims) == 1
        assert result.claims[0].text == "Neural networks are effective."
        assert result.claims[0].confidence_level == "sourced"
        assert result.claims[0].confidence_score == 0.85
        assert result.claims[0].source_ids == [source_id]

    @pytest.mark.asyncio
    async def test_resolve_by_slug(self, db_session: AsyncSession) -> None:
        article_id = _uid()
        article = Article(
            id=article_id,
            user_id=TEST_USER_ID,
            slug="claims-slug-test",
            title="Claims Slug Test",
            file_path="wiki/claims-slug.md",
        )
        db_session.add(article)
        await db_session.flush()

        service = CitationService()
        wiki_service = WikiService()
        result = await service.get_article_claims(
            "claims-slug-test",
            db_session,
            user_id=TEST_USER_ID,
            wiki_service=wiki_service,
        )

        assert result.article_id == article_id


# ---------------------------------------------------------------------------
# Persistence tests — confidence_score on CompiledClaim
# ---------------------------------------------------------------------------


class TestClaimConfidenceScorePersistence:
    """Verify that confidence_score is stored and read back correctly."""

    @pytest.mark.asyncio
    async def test_default_confidence_score(self, db_session: AsyncSession) -> None:
        article_id = _uid()
        article = Article(
            id=article_id,
            user_id=TEST_USER_ID,
            slug="default-score",
            title="Default Score",
            file_path="wiki/default-score.md",
        )
        db_session.add(article)
        await db_session.flush()

        claim = CompiledClaim(
            id=_uid(),
            article_id=article_id,
            user_id=TEST_USER_ID,
            text="A claim.",
            confidence_level="mixed",
        )
        db_session.add(claim)
        await db_session.flush()
        await db_session.refresh(claim)

        assert claim.confidence_score == 0.5  # default

    @pytest.mark.asyncio
    async def test_computed_confidence_score_stored(self, db_session: AsyncSession) -> None:
        article_id = _uid()
        article = Article(
            id=article_id,
            user_id=TEST_USER_ID,
            slug="computed-score",
            title="Computed Score",
            file_path="wiki/computed-score.md",
        )
        db_session.add(article)
        await db_session.flush()

        score = compute_claim_confidence("sourced", source_count=2)
        claim = CompiledClaim(
            id=_uid(),
            article_id=article_id,
            user_id=TEST_USER_ID,
            text="A well-sourced claim.",
            confidence_level="sourced",
            confidence_score=score,
            source_ids=json.dumps(["src-1", "src-2"]),
        )
        db_session.add(claim)
        await db_session.flush()
        await db_session.refresh(claim)

        # sourced baseline=0.8 + 0.2 * (2/4) = 0.9
        assert math.isclose(claim.confidence_score, 0.9, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


class TestClaimsEndpoint:
    """Verify GET /api/wiki/articles/{id}/claims endpoint."""

    @pytest.mark.asyncio
    async def test_claims_endpoint_not_found(self, client) -> None:
        resp = await client.get("/api/wiki/articles/nonexistent/claims")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_claims_endpoint_empty_article(self, client, async_engine) -> None:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
        article_id = _uid()
        async with factory() as session:
            article = Article(
                id=article_id,
                user_id=TEST_USER_ID,
                slug="claims-empty",
                title="Claims Empty",
                file_path="wiki/claims-empty.md",
                confidence_score=0.6,
            )
            session.add(article)
            await session.commit()

        resp = await client.get(f"/api/wiki/articles/{article_id}/claims")
        assert resp.status_code == 200
        data = resp.json()
        assert data["article_id"] == article_id
        assert data["article_title"] == "Claims Empty"
        assert data["article_confidence_score"] == 0.6
        assert data["claims"] == []

    @pytest.mark.asyncio
    async def test_claims_endpoint_with_claims(self, client, async_engine) -> None:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

        source_id = _uid()
        article_id = _uid()

        async with factory() as session:
            source = Source(
                id=source_id,
                user_id=TEST_USER_ID,
                source_type="url",
                title="Web Source",
            )
            session.add(source)
            await session.flush()

            article = Article(
                id=article_id,
                user_id=TEST_USER_ID,
                slug="claims-with-data",
                title="Claims With Data",
                file_path="wiki/claims-with-data.md",
                confidence_score=0.85,
            )
            session.add(article)
            await session.flush()

            claim = CompiledClaim(
                id=_uid(),
                article_id=article_id,
                user_id=TEST_USER_ID,
                text="An important claim.",
                confidence_level="sourced",
                confidence_score=0.85,
                source_ids=json.dumps([source_id]),
            )
            session.add(claim)
            await session.commit()

        resp = await client.get(f"/api/wiki/articles/{article_id}/claims")
        assert resp.status_code == 200
        data = resp.json()
        assert data["article_id"] == article_id
        assert data["article_title"] == "Claims With Data"
        assert data["article_confidence_score"] == 0.85
        assert len(data["claims"]) == 1
        assert data["claims"][0]["text"] == "An important claim."
        assert data["claims"][0]["confidence_level"] == "sourced"
        assert data["claims"][0]["confidence_score"] == 0.85
        assert data["claims"][0]["source_ids"] == [source_id]
        assert "last_reinforced_at" in data["claims"][0]
        assert "created_at" in data["claims"][0]
