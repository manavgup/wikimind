"""Compilation tables — drafts, compiled claims, concept clusters."""

import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from wikimind._datetime import utcnow_naive
from wikimind.models.enums import ClusterStatus


class CompilationDraft(SQLModel, table=True):
    """Draft compilation output awaiting user review before finalizing.

    Created when ``compilation.interactive`` is enabled. The LLM extracts
    key takeaways and a draft article; the user reviews, optionally adds
    guidance, and approves or rejects before the article is saved to the wiki.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    source_id: str = Field(foreign_key="source.id", index=True)
    title: str
    summary: str
    key_takeaways: str  # JSON array of strings
    draft_result_json: str  # Serialized CompilationResult
    user_guidance: str | None = None  # User-provided focus direction
    status: str = "pending"  # pending | approved | rejected
    created_at: datetime = Field(default_factory=utcnow_naive)
    reviewed_at: datetime | None = None


class CompiledClaim(SQLModel, table=True):
    """A persisted compiled claim extracted from a source article (issue #466).

    Promoted from the Pydantic-only ``CompiledClaimDTO`` to a first-class table
    so that claims are individually queryable, linkable to concept clusters,
    and carry their own embedding for semantic similarity.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    article_id: str = Field(foreign_key="article.id", index=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    text: str  # The claim text
    subjects: str = "[]"  # JSON list[str]: LLM-extracted canonical subject names
    predicate: str | None = None  # LLM-extracted predicate (nullable initially)
    confidence_level: str  # ConfidenceLevel enum value
    confidence_score: float = Field(default=0.5)  # numeric, reused from #422
    source_ids: str = "[]"  # JSON list of source UUIDs supporting this claim
    last_reinforced_at: datetime = Field(default_factory=utcnow_naive)
    quote: str | None = None
    embedding: bytes | None = None  # raw float32 array; nullable until embedding runs
    embedding_version: str | None = None  # e.g. "bge-small-1.5"
    source_span_ids: str = "[]"  # JSON list of SourceSpan UUIDs (issue #450)
    cluster_assignment_reconciled: bool = False
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)


class ConceptCluster(SQLModel, table=True):
    """An implicit concept cluster derived from compiled claim subjects (issue #466).

    Clusters group semantically related claims by subject. The two-stage pipeline
    assigns claims to clusters: online (advisory) at ingest time, offline
    (reconciled) by the batch reconciler.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    canonical_text: str  # canonical subject name
    centroid_embedding: bytes | None = None  # raw float32 array
    embedding_version: str | None = None  # centroid valid only for this version
    member_count: int = 0
    status: str = Field(default=ClusterStatus.CANDIDATE)  # ClusterStatus enum value
    superseded_by: str | None = Field(default=None, foreign_key="conceptcluster.id")
    last_reinforced_at: datetime = Field(default_factory=utcnow_naive)
    last_reconciled_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow_naive)
    updated_at: datetime = Field(default_factory=utcnow_naive)


class ClaimConcept(SQLModel, table=True):
    """Join table linking compiled claims to concept clusters (issue #466).

    ``advisory=True`` is the default at ingest time — the online clusterer's
    best guess. The offline reconciler sets ``advisory=False`` and updates
    ``CompiledClaim.cluster_assignment_reconciled=True``.
    """

    claim_id: str = Field(foreign_key="compiledclaim.id", primary_key=True)
    concept_id: str = Field(foreign_key="conceptcluster.id", primary_key=True, index=True)
    role: str = Field(primary_key=True)  # ClaimConceptRole enum value
    advisory: bool = True  # TRUE until offline reconciler confirms
    created_at: datetime = Field(default_factory=utcnow_naive)
