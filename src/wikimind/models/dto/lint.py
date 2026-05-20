"""Linter DTOs — dependency-light request/response schemas."""

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Linter pipeline models
# ---------------------------------------------------------------------------


class LinterContradiction(BaseModel):
    """A contradiction found by the linter."""

    claim_a: str
    claim_b: str
    articles: list[str]


class LinterResult(BaseModel):
    """Output from wiki linter."""

    contradictions: list[LinterContradiction] = []
    orphaned_articles: list[str] = []
    stale_articles: list[str] = []
    gap_suggestions: list[str] = []
    coverage_scores: dict[str, float] = {}  # concept -> 0.0-1.0


# ---------------------------------------------------------------------------
# API response models
# ---------------------------------------------------------------------------


class JobTriggerResponse(BaseModel):
    """Response after triggering an async job."""

    status: str
    job_id: str | None = None
    message: str | None = None


class LintRunResponse(BaseModel):
    """Response after triggering a lint run."""

    status: str


class DismissFindingResponse(BaseModel):
    """Response after dismissing a lint finding."""

    dismissed: bool
    kind: str
    finding_id: str
