"""Integration tests for article-level confidence scoring (issue #422, #465).

These tests exercise the compiler helper that recomputes
``Article.confidence_score`` from the live source set + contradiction
backlinks and verify that the wiki service decays the score for stale
articles. They use the in-memory SQLite engine from conftest, not the
LLM, so they are hermetic and fast.

Issue #465 adds per-claim confidence persistence: claims get individual
``confidence_score`` values, and the article's score is the aggregate
(weighted mean) of its claims.
"""

from __future__ import annotations

import json
import math
from datetime import timedelta
from typing import TYPE_CHECKING

from wikimind._datetime import utcnow_naive
from wikimind.engine.compiler import Compiler
from wikimind.engine.confidence import compute_claim_confidence
from wikimind.models import (
    Article,
    ArticleSource,
    Backlink,
    CompilationResult,
    CompiledClaim,
    CompiledClaimDTO,
    ConfidenceLevel,
    PageType,
    RelationType,
    Source,
    SourceType,
)
from wikimind.services.wiki import _effective_confidence

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

from tests.conftest import TEST_USER_ID


async def _add_source(
    session: AsyncSession,
    title: str,
    age_days: int = 0,
) -> Source:
    src = Source(
        source_type=SourceType.TEXT,
        title=title,
        user_id=TEST_USER_ID,
    )
    if age_days:
        src.ingested_at = utcnow_naive() - timedelta(days=age_days)
    session.add(src)
    await session.commit()
    return src


async def _link_source(session: AsyncSession, article_id: str, source_id: str) -> None:
    session.add(ArticleSource(article_id=article_id, source_id=source_id))
    await session.commit()


async def test_confidence_score_increases_with_more_sources(db_session: AsyncSession) -> None:
    """Adding a confirming source should raise the recomputed confidence."""
    article = Article(
        slug="topic",
        title="Topic",
        file_path="topic.md",
        page_type=PageType.SOURCE,
        user_id=TEST_USER_ID,
    )
    db_session.add(article)
    await db_session.commit()

    src1 = await _add_source(db_session, "first")
    await _link_source(db_session, article.id, src1.id)

    compiler = Compiler(user_id=TEST_USER_ID)
    await compiler._refresh_confidence_score(article, db_session)
    one_source_score = article.confidence_score
    assert article.last_reinforced_at is not None

    src2 = await _add_source(db_session, "second")
    await _link_source(db_session, article.id, src2.id)

    await compiler._refresh_confidence_score(article, db_session)
    two_source_score = article.confidence_score

    assert two_source_score > one_source_score


async def test_confidence_score_decreases_with_contradiction(
    db_session: AsyncSession,
) -> None:
    """A new ``CONTRADICTS`` backlink should lower the recomputed confidence."""
    article = Article(
        slug="topic",
        title="Topic",
        file_path="topic.md",
        page_type=PageType.SOURCE,
        user_id=TEST_USER_ID,
    )
    other = Article(
        slug="counter",
        title="Counter",
        file_path="counter.md",
        page_type=PageType.SOURCE,
        user_id=TEST_USER_ID,
    )
    db_session.add(article)
    db_session.add(other)
    await db_session.commit()

    src = await _add_source(db_session, "src")
    await _link_source(db_session, article.id, src.id)

    compiler = Compiler(user_id=TEST_USER_ID)
    await compiler._refresh_confidence_score(article, db_session)
    before = article.confidence_score

    db_session.add(
        Backlink(
            source_article_id=other.id,
            target_article_id=article.id,
            relation_type=RelationType.CONTRADICTS,
            user_id=TEST_USER_ID,
        )
    )
    await db_session.commit()

    await compiler._refresh_confidence_score(article, db_session)
    after = article.confidence_score

    assert after < before


async def test_effective_confidence_decays_for_year_old_article(
    db_session: AsyncSession,
) -> None:
    """A year-old reinforcement should make ``effective_confidence`` strictly less than the base."""
    article = Article(
        slug="aged",
        title="Aged",
        file_path="aged.md",
        page_type=PageType.SOURCE,
        user_id=TEST_USER_ID,
        confidence_score=0.8,
        last_reinforced_at=utcnow_naive() - timedelta(days=365),
    )
    db_session.add(article)
    await db_session.commit()

    effective = _effective_confidence(article)
    assert effective < article.confidence_score
    # Sanity: with the documented multiplier (1 - 1*0.3) = 0.7, the effective
    # value should be in the right ballpark.
    assert effective < 0.8 * 0.75


# ---------------------------------------------------------------------------
# Per-claim confidence → article aggregation (issue #465)
# ---------------------------------------------------------------------------


async def test_article_confidence_aggregated_from_claims(
    db_session: AsyncSession,
) -> None:
    """Article confidence_score should be the mean of its claim scores when claims exist."""
    article = Article(
        slug="claim-agg",
        title="Claim Aggregation",
        file_path="claim-agg.md",
        page_type=PageType.SOURCE,
        user_id=TEST_USER_ID,
    )
    db_session.add(article)
    await db_session.commit()

    src = await _add_source(db_session, "claim-source")
    await _link_source(db_session, article.id, src.id)

    # Insert two claims with known confidence scores.
    claim1 = CompiledClaim(
        article_id=article.id,
        user_id=TEST_USER_ID,
        text="Claim with high confidence.",
        confidence_level="sourced",
        confidence_score=compute_claim_confidence("sourced", source_count=2),
        source_ids=json.dumps([src.id]),
    )
    claim2 = CompiledClaim(
        article_id=article.id,
        user_id=TEST_USER_ID,
        text="Claim with lower confidence.",
        confidence_level="inferred",
        confidence_score=compute_claim_confidence("inferred", source_count=0),
        source_ids="[]",
    )
    db_session.add_all([claim1, claim2])
    await db_session.commit()

    compiler = Compiler(user_id=TEST_USER_ID)
    await compiler._refresh_confidence_score(article, db_session)

    # Expected: mean of (0.9, 0.3) = 0.6
    expected = (claim1.confidence_score + claim2.confidence_score) / 2
    assert math.isclose(article.confidence_score, expected, abs_tol=1e-9)


async def test_persist_claims_stores_source_ids_and_subjects(
    db_session: AsyncSession,
) -> None:
    """_persist_claims should store source_ids and subjects from CompiledClaimDTO."""
    article = Article(
        slug="persist-claims",
        title="Persist Claims",
        file_path="persist-claims.md",
        page_type=PageType.SOURCE,
        user_id=TEST_USER_ID,
    )
    db_session.add(article)
    await db_session.commit()

    src = await _add_source(db_session, "src-for-claims")

    result = CompilationResult(
        title="Persist Claims",
        summary="Test article.",
        key_claims=[
            CompiledClaimDTO(
                claim="ML models need data.",
                confidence=ConfidenceLevel.SOURCED,
                subjects=["machine learning", "data"],
                source_ids=[src.id],
            ),
            CompiledClaimDTO(
                claim="This is inferred.",
                confidence=ConfidenceLevel.INFERRED,
                subjects=["inference"],
            ),
        ],
        concepts=["ml"],
        backlink_suggestions=[],
        open_questions=[],
        article_body="Body text here.",
    )

    compiler = Compiler(user_id=TEST_USER_ID)
    await compiler._persist_claims(article.id, result, src, db_session)

    from sqlmodel import select

    claims = (
        await db_session.execute(
            select(CompiledClaim)
            .where(CompiledClaim.article_id == article.id)
            .order_by(CompiledClaim.text)
        )
    ).scalars().all()

    assert len(claims) == 2

    # First claim (alphabetical): "ML models need data."
    ml_claim = claims[0]
    assert ml_claim.text == "ML models need data."
    assert json.loads(ml_claim.source_ids) == [src.id]
    assert json.loads(ml_claim.subjects) == ["machine learning", "data"]
    # sourced + 1 source: 0.8 + 0.2 * 0.25 = 0.85
    assert math.isclose(ml_claim.confidence_score, 0.85, abs_tol=1e-9)

    # Second claim: "This is inferred."
    inf_claim = claims[1]
    assert inf_claim.text == "This is inferred."
    # No source_ids on DTO, falls back to [src.id]
    assert json.loads(inf_claim.source_ids) == [src.id]
    assert json.loads(inf_claim.subjects) == ["inference"]
    # inferred + 1 source: 0.3 + 0.2 * 0.25 = 0.35
    assert math.isclose(inf_claim.confidence_score, 0.35, abs_tol=1e-9)
