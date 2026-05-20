"""Lint tables — reports, findings, contradictions, and pair cache."""

import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from wikimind._datetime import utcnow_naive
from wikimind.models.enums import (
    ContradictionStatus,
    LintFindingKind,
    LintReportStatus,
    LintSeverity,
)


class LintReport(SQLModel, table=True):
    """One run of the linter. All findings from a run FK back to this row via report_id."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    generated_at: datetime = Field(default_factory=utcnow_naive, index=True)
    completed_at: datetime | None = None
    status: LintReportStatus = LintReportStatus.IN_PROGRESS
    article_count: int = 0
    total_findings: int = 0
    contradictions_count: int = 0
    orphans_count: int = 0
    structural_count: int = 0
    checked_articles: int | None = None
    missing_pages_count: int = 0
    dismissed_count: int = 0
    total_pairs: int = 0
    checked_pairs: int = 0
    error_message: str | None = None
    job_id: str | None = Field(default=None, foreign_key="job.id", index=True)


class _LintFindingBase(SQLModel):
    """Fields shared across every per-kind finding table. NOT a table itself."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    report_id: str = Field(foreign_key="lintreport.id", index=True)
    severity: LintSeverity = LintSeverity.WARN
    description: str
    created_at: datetime = Field(default_factory=utcnow_naive)
    dismissed: bool = False
    dismissed_at: datetime | None = None
    content_hash: str = Field(index=True)


class ContradictionFinding(_LintFindingBase, table=True):
    """A contradiction between key claims of two articles that share a concept."""

    kind: LintFindingKind = Field(default=LintFindingKind.CONTRADICTION)
    article_a_id: str = Field(foreign_key="article.id", index=True)
    article_b_id: str = Field(foreign_key="article.id", index=True)
    article_a_claim: str
    article_b_claim: str
    llm_confidence: str  # "high" | "medium" | "low"
    shared_concept_id: str | None = Field(default=None, foreign_key="concept.id", index=True)
    contradiction_id: str | None = Field(default=None, index=True)  # FK to Contradiction


class OrphanFinding(_LintFindingBase, table=True):
    """An article with zero inbound AND zero outbound backlinks."""

    kind: LintFindingKind = Field(default=LintFindingKind.ORPHAN)
    article_id: str = Field(foreign_key="article.id", index=True)
    article_title: str


class StructuralFinding(_LintFindingBase, table=True):
    """A structural integrity violation detected by the backlink enforcer."""

    kind: LintFindingKind = Field(default=LintFindingKind.STRUCTURAL)
    article_id: str = Field(foreign_key="article.id", index=True)
    violation_type: str  # source_no_concepts | concept_insufficient_synthesizes | ...
    auto_repaired: bool = False
    detail: str = ""


class DismissedFinding(SQLModel, table=True):
    """Cross-run dismiss record — keyed by content hash."""

    content_hash: str = Field(primary_key=True)
    kind: LintFindingKind
    dismissed_at: datetime = Field(default_factory=utcnow_naive)
    reason: str | None = None


class Contradiction(SQLModel, table=True):
    """A persisted contradiction between claims in two wiki articles.

    Created by the linter when it detects contradictory claims across articles.
    Users can browse, resolve, or dismiss contradictions as first-class wiki content.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    claim_a: str
    claim_b: str
    article_a_id: str = Field(foreign_key="article.id", index=True)
    article_b_id: str = Field(foreign_key="article.id", index=True)
    source_finding_id: str | None = None  # FK to ContradictionFinding that created this
    claim_fingerprint: str = Field(default="", index=True)  # SHA-256 of sorted article+claim pair
    detected_at: datetime = Field(default_factory=utcnow_naive)
    status: ContradictionStatus = ContradictionStatus.ACTIVE
    resolution: str | None = None
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    user_id: str = Field(foreign_key="user.id", index=True)


class LintPairCache(SQLModel, table=True):
    """Cache of LLM contradiction check results for article pairs.

    Keyed by sorted article pair IDs. Invalidated when either article's
    updated_at changes.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    article_a_id: str = Field(index=True)
    article_b_id: str = Field(index=True)
    article_a_updated_at: str
    article_b_updated_at: str
    result_json: str  # JSON list of contradiction dicts
    checked_at: datetime = Field(default_factory=utcnow_naive)
