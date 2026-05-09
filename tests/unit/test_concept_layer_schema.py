"""Tests for the concept-layer schema migration (issue #466).

Covers:
- CompiledClaim, ConceptCluster, ClaimConcept table creation and round-trip
- CompiledClaimDTO (pipeline Pydantic model) with new fields
- Compiler persists CompiledClaim rows when saving an article
- ClaimConcept join table relationships
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import patch

from sqlmodel import select

from tests.conftest import TEST_USER_ID
from wikimind._datetime import utcnow_naive
from wikimind.engine import compiler as compiler_mod
from wikimind.engine.compiler import Compiler
from wikimind.models import (
    Article,
    ClaimConcept,
    ClaimConceptRole,
    ClusterStatus,
    CompilationResult,
    CompiledClaim,
    CompiledClaimDTO,
    ConceptCluster,
    ConfidenceLevel,
    IngestStatus,
    Provider,
    Source,
    SourceType,
)

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# CompiledClaimDTO (Pydantic pipeline model) tests
# ---------------------------------------------------------------------------


class TestCompiledClaimDTO:
    """Verify the pipeline DTO accepts new fields."""

    def test_minimal_claim(self) -> None:
        dto = CompiledClaimDTO(claim="X is fast", confidence=ConfidenceLevel.SOURCED)
        assert dto.claim == "X is fast"
        assert dto.subjects == []
        assert dto.predicate is None
        assert dto.source_ids == []

    def test_full_claim(self) -> None:
        dto = CompiledClaimDTO(
            claim="Redis is single-threaded",
            subjects=["Redis", "single-threaded execution"],
            predicate="is",
            confidence=ConfidenceLevel.SOURCED,
            quote="Redis uses a single thread",
            source_ids=["src-1", "src-2"],
        )
        assert dto.subjects == ["Redis", "single-threaded execution"]
        assert dto.predicate == "is"
        assert dto.source_ids == ["src-1", "src-2"]

    def test_backward_compat_no_subjects(self) -> None:
        """Old-style claims without subjects/predicate still parse."""
        dto = CompiledClaimDTO(claim="Test", confidence=ConfidenceLevel.INFERRED)
        assert dto.subjects == []
        assert dto.predicate is None


# ---------------------------------------------------------------------------
# CompiledClaim (SQLModel table) round-trip tests
# ---------------------------------------------------------------------------


async def test_compiled_claim_create_and_read(db_session) -> None:
    """CompiledClaim rows round-trip through SQLite."""
    # Create prerequisites
    from wikimind.models import User

    db_session.add(
        User(
            id=TEST_USER_ID,
            email="test@test.com",
            auth_provider="none",
            auth_provider_id="test",
        )
    )
    article = Article(
        slug="test-article",
        title="Test",
        file_path="test/test.md",
        confidence=ConfidenceLevel.SOURCED,
        user_id=TEST_USER_ID,
    )
    db_session.add(article)
    await db_session.commit()
    await db_session.refresh(article)

    now = utcnow_naive()
    claim = CompiledClaim(
        article_id=article.id,
        user_id=TEST_USER_ID,
        text="Redis is single-threaded",
        subjects=json.dumps(["Redis", "single-threaded execution"]),
        predicate="is",
        confidence_level=ConfidenceLevel.SOURCED.value,
        confidence_score=0.85,
        source_ids=json.dumps(["src-1"]),
        last_reinforced_at=now,
        quote="Redis uses a single thread",
        created_at=now,
        updated_at=now,
    )
    db_session.add(claim)
    await db_session.commit()

    result = await db_session.execute(select(CompiledClaim).where(CompiledClaim.article_id == article.id))
    rows = list(result.scalars().all())
    assert len(rows) == 1
    assert rows[0].text == "Redis is single-threaded"
    assert json.loads(rows[0].subjects) == ["Redis", "single-threaded execution"]
    assert rows[0].predicate == "is"
    assert rows[0].confidence_level == "sourced"
    assert rows[0].confidence_score == 0.85
    assert rows[0].cluster_assignment_reconciled is False
    assert rows[0].embedding is None
    assert rows[0].embedding_version is None


# ---------------------------------------------------------------------------
# ConceptCluster table round-trip tests
# ---------------------------------------------------------------------------


async def test_concept_cluster_create_and_read(db_session) -> None:
    """ConceptCluster rows round-trip through SQLite."""
    from wikimind.models import User

    db_session.add(
        User(
            id=TEST_USER_ID,
            email="test@test.com",
            auth_provider="none",
            auth_provider_id="test",
        )
    )
    await db_session.commit()

    now = utcnow_naive()
    cluster = ConceptCluster(
        user_id=TEST_USER_ID,
        canonical_text="Redis",
        member_count=0,
        status=ClusterStatus.CANDIDATE,
        last_reinforced_at=now,
        created_at=now,
        updated_at=now,
    )
    db_session.add(cluster)
    await db_session.commit()

    result = await db_session.execute(select(ConceptCluster).where(ConceptCluster.user_id == TEST_USER_ID))
    rows = list(result.scalars().all())
    assert len(rows) == 1
    assert rows[0].canonical_text == "Redis"
    assert rows[0].status == ClusterStatus.CANDIDATE
    assert rows[0].member_count == 0
    assert rows[0].superseded_by is None
    assert rows[0].last_reconciled_at is None


async def test_concept_cluster_status_transitions(db_session) -> None:
    """ConceptCluster status can transition from candidate to active."""
    from wikimind.models import User

    db_session.add(
        User(
            id=TEST_USER_ID,
            email="test@test.com",
            auth_provider="none",
            auth_provider_id="test",
        )
    )
    await db_session.commit()

    now = utcnow_naive()
    cluster = ConceptCluster(
        user_id=TEST_USER_ID,
        canonical_text="Testing",
        status=ClusterStatus.CANDIDATE,
        last_reinforced_at=now,
    )
    db_session.add(cluster)
    await db_session.commit()
    await db_session.refresh(cluster)

    # Promote to active
    cluster.status = ClusterStatus.ACTIVE
    cluster.member_count = 3
    cluster.last_reconciled_at = now
    db_session.add(cluster)
    await db_session.commit()
    await db_session.refresh(cluster)

    assert cluster.status == ClusterStatus.ACTIVE
    assert cluster.member_count == 3


# ---------------------------------------------------------------------------
# ClaimConcept join table tests
# ---------------------------------------------------------------------------


async def test_claim_concept_join(db_session) -> None:
    """ClaimConcept links a compiled claim to a concept cluster."""
    from wikimind.models import User

    db_session.add(
        User(
            id=TEST_USER_ID,
            email="test@test.com",
            auth_provider="none",
            auth_provider_id="test",
        )
    )
    article = Article(
        slug="test-join",
        title="Test Join",
        file_path="test/test-join.md",
        confidence=ConfidenceLevel.SOURCED,
        user_id=TEST_USER_ID,
    )
    db_session.add(article)
    await db_session.commit()
    await db_session.refresh(article)

    now = utcnow_naive()
    claim = CompiledClaim(
        article_id=article.id,
        user_id=TEST_USER_ID,
        text="Redis is fast",
        confidence_level=ConfidenceLevel.SOURCED.value,
        last_reinforced_at=now,
    )
    cluster = ConceptCluster(
        user_id=TEST_USER_ID,
        canonical_text="Redis",
        last_reinforced_at=now,
    )
    db_session.add(claim)
    db_session.add(cluster)
    await db_session.commit()
    await db_session.refresh(claim)
    await db_session.refresh(cluster)

    join_row = ClaimConcept(
        claim_id=claim.id,
        concept_id=cluster.id,
        role=ClaimConceptRole.SUBJECT,
        advisory=True,
    )
    db_session.add(join_row)
    await db_session.commit()

    result = await db_session.execute(select(ClaimConcept).where(ClaimConcept.claim_id == claim.id))
    rows = list(result.scalars().all())
    assert len(rows) == 1
    assert rows[0].concept_id == cluster.id
    assert rows[0].role == ClaimConceptRole.SUBJECT
    assert rows[0].advisory is True


# ---------------------------------------------------------------------------
# Compiler persists CompiledClaim rows tests
# ---------------------------------------------------------------------------


def _compiler_for(tmp_path: Path) -> Compiler:
    with (
        patch.object(compiler_mod, "get_llm_router"),
        patch.object(
            compiler_mod,
            "get_settings",
            return_value=SimpleNamespace(data_dir=str(tmp_path)),
        ),
    ):
        return Compiler(user_id=TEST_USER_ID)


async def _make_source(session) -> Source:
    source = Source(
        id=str(uuid.uuid4()),
        source_type=SourceType.TEXT,
        title="Test Source",
        status=IngestStatus.PROCESSING,
        ingested_at=utcnow_naive(),
        user_id=TEST_USER_ID,
    )
    session.add(source)
    await session.commit()
    await session.refresh(source)
    return source


async def test_save_article_persists_compiled_claims(db_session, tmp_path) -> None:
    """save_article must create CompiledClaim rows for each key_claim."""
    compiler = _compiler_for(tmp_path)
    source = await _make_source(db_session)

    claims = [
        CompiledClaimDTO(
            claim="Redis is fast",
            subjects=["Redis"],
            predicate="is",
            confidence=ConfidenceLevel.SOURCED,
            quote="blazing fast",
        ),
        CompiledClaimDTO(
            claim="Redis is single-threaded",
            subjects=["Redis", "threading"],
            predicate="is",
            confidence=ConfidenceLevel.SOURCED,
        ),
    ]
    result = CompilationResult(
        title="Redis Overview",
        summary="Redis is a fast in-memory store. It uses a single-threaded architecture.",
        key_claims=claims,
        concepts=["redis"],
        backlink_suggestions=[],
        open_questions=[],
        article_body="## Body\n\n" + "Redis content. " * 50,
    )

    article = await compiler.save_article(result, source, db_session)

    claim_result = await db_session.execute(select(CompiledClaim).where(CompiledClaim.article_id == article.id))
    claim_rows = list(claim_result.scalars().all())
    assert len(claim_rows) == 2

    texts = {r.text for r in claim_rows}
    assert "Redis is fast" in texts
    assert "Redis is single-threaded" in texts

    # Verify JSON fields
    for row in claim_rows:
        if row.text == "Redis is fast":
            assert json.loads(row.subjects) == ["Redis"]
            assert row.predicate == "is"
            assert row.quote == "blazing fast"
            assert row.confidence_level == "sourced"
            assert json.loads(row.source_ids) == [source.id]

    # Verify user scoping
    for row in claim_rows:
        assert row.user_id == TEST_USER_ID


async def test_recompile_clears_old_claims(db_session, tmp_path) -> None:
    """Recompiling an article replaces old CompiledClaim rows."""
    compiler = _compiler_for(tmp_path)
    compiler._last_provider_used = Provider.ANTHROPIC
    source = await _make_source(db_session)

    # First compile with 2 claims
    result1 = CompilationResult(
        title="Test",
        summary="A summary. Two sentences.",
        key_claims=[
            CompiledClaimDTO(claim="Claim A", confidence=ConfidenceLevel.SOURCED),
            CompiledClaimDTO(claim="Claim B", confidence=ConfidenceLevel.INFERRED),
        ],
        concepts=["test"],
        backlink_suggestions=[],
        open_questions=[],
        article_body="Body text. " * 50,
    )
    article = await compiler.save_article(result1, source, db_session)
    claim_result = await db_session.execute(select(CompiledClaim).where(CompiledClaim.article_id == article.id))
    assert len(list(claim_result.scalars().all())) == 2

    # Second compile with 1 claim (replacing)
    result2 = CompilationResult(
        title="Test",
        summary="A summary. Two sentences.",
        key_claims=[
            CompiledClaimDTO(claim="Claim C", confidence=ConfidenceLevel.SOURCED),
        ],
        concepts=["test"],
        backlink_suggestions=[],
        open_questions=[],
        article_body="New body text. " * 50,
    )
    await compiler.save_article(result2, source, db_session)

    claim_result = await db_session.execute(select(CompiledClaim).where(CompiledClaim.article_id == article.id))
    claims = list(claim_result.scalars().all())
    assert len(claims) == 1
    assert claims[0].text == "Claim C"


# ---------------------------------------------------------------------------
# Enum value tests
# ---------------------------------------------------------------------------


def test_cluster_status_values() -> None:
    """ClusterStatus enum has the expected values."""
    assert ClusterStatus.CANDIDATE == "candidate"
    assert ClusterStatus.ACTIVE == "active"
    assert ClusterStatus.ARCHIVED == "archived"
    assert ClusterStatus.SUPERSEDED == "superseded"
    assert ClusterStatus.REJECTED == "rejected"


def test_claim_concept_role_values() -> None:
    """ClaimConceptRole enum has the expected values."""
    assert ClaimConceptRole.SUBJECT == "subject"
    assert ClaimConceptRole.MENTIONED == "mentioned"
