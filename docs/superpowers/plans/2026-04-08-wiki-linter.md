# Wiki Linter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **⚠️ DATA MODEL SUPERSEDED (2026-04-08):** Spec § Open decisions #9 has been resolved: the linter uses **per-kind finding tables** (`ContradictionFinding`, `OrphanFinding`) instead of the single `LintFinding` + `raw_json` design referenced throughout this plan. Before executing any PR in this plan, re-read § Data model and § Dismiss semantics in the spec (`docs/superpowers/specs/2026-04-08-wiki-linter-design.md`) — they are the source of truth. The per-file task breakdown below is still structurally valid, but references to the `LintFinding` table, `raw_json` column, and separate in-memory Pydantic models in `engine/linter/findings.py` are stale and must be adapted to the per-kind table model at implementation time.

**Goal:** Ship the third pillar of the Karpathy LLM Wiki Pattern (lint) as a structured, per-check, LLM-powered health audit. Replace the existing single-prompt stub in `jobs/worker.py::lint_wiki` with a real `run_lint` pipeline backed by a `LintReport` row plus per-kind finding tables (`ContradictionFinding`, `OrphanFinding`; see spec § Data model), expose it via a new `/lint/*` API surface plus compatibility shims on the existing `/jobs/lint` and `/wiki/health` endpoints, and render it in a new `/health` frontend view.

**Architecture:** Multi-PR epic. PR A ships the smallest useful backend slice (data model + contradictions check + API + stub migration, no frontend). PR B ships the health view on top of PR A. PR C adds orphan detection and is gated on #95 merging first. PR D is an optional scheduling polish PR. Each PR is independently testable and independently shippable. The spec lives at `docs/superpowers/specs/2026-04-08-wiki-linter-design.md` — read it before starting any PR.

**Tech Stack:** FastAPI + SQLModel + SQLite (backend); React 18 + Vite + TypeScript + Tailwind + react-query + react-router (frontend); pytest with hermetic fixtures, mocked LLM router (backend tests).

---

## Spec coverage

This plan implements the spec's v1 scope. The decisions it hardcodes:

| Decision | Source |
|---|---|
| Per-check function decomposition (not a single mega-prompt) | Spec § Design / Pipeline |
| Two new tables: `LintReport`, `LintFinding` (and `DismissedFinding` helper) | Spec § Data model |
| Contradictions check uses LLM per concept-bucket pair, with caps + pair caching | Spec § Check: detect_contradictions |
| Orphan check is SQL-only and gated on #95 via a config flag | Spec § Check: detect_orphans, § Gating |
| Missing-pages check DROPPED from v1 | Spec § Non-goals, § Open decisions #3 |
| All linter LLM calls go through the existing router with `task_type=LINT` | Spec § Current state |
| Settings live in a new `LinterConfig` Pydantic submodel | Spec § Settings |
| `POST /jobs/lint` and `GET /wiki/health` reshape as compatibility shims | Spec § Migration from the stub |
| Dismiss semantics: persistent via content-hash in a `DismissedFinding` table | Spec § Dismiss semantics, § Open decisions #5 |
| Frontend uses react-query cache keys and WS-event-driven invalidation | Spec § Frontend, § State management |

Open decisions the plan assumes a specific answer for (flagged to the executing engineer so they can stop and ask if the user answered differently in review):

| Assumed answer | Revisit if |
|---|---|
| Manual trigger + keep existing weekly cron | User wants on-ingest triggering |
| Refuse to run when over monthly budget and `respect_monthly_budget=True` | User wants degraded-mode fallback |
| Persist all LLM confidences, hide `low` by default in UI | User wants to filter at write time |
| Dismiss is cross-run via content hash | User wants per-report-only dismiss |
| Ship linter without orphan detection if #95 not merged | User wants linter blocked on #95 |
| Retain reports forever in v1 | Table growth becomes a real concern |

## Conventions for the implementing engineer

Read `CLAUDE.md` at the repo root before any change. Key rules that bite during linter work specifically:

- **Conventional commits.** Prefix with `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`. One logical change per commit.
- **`make verify` must be green before any push.** Runs ruff lint + format + mypy + pytest with an 80% coverage floor.
- **No magic numbers.** Every tunable value belongs in `Settings`. The linter has a lot of these (pair caps, cost budgets, cache toggles) — all go in `LinterConfig`, not as inline constants.
- **Hermetic LLM tests.** Mock the router at the `get_llm_router()` boundary. Never make a real API call from a test. The contradiction check is the main consumer and its tests must stub the router's `complete()` method.
- **No silent failures.** If a check raises, `run_lint` records the error on the `LintReport` row and continues; it does not swallow exceptions to keep the happy path clean.
- **Doc-sync hook.** Adding or changing any route triggers `docs/openapi.yaml` regeneration via pre-commit. Do not manually edit the YAML; let the hook do it.
- **TDD for backend.** Write failing test → run → minimal implementation → run → commit. The plan steps are written this way; follow them.
- **No TDD for frontend.** The project has no frontend test infrastructure (per the Ask slice spec). Frontend PR B ships behind `lint` + `typecheck` + `build`, with a manual smoke check via the dev server. PR B does not introduce vitest.
- **Don't expand scope.** Anything not in the spec or this plan is out of scope. If you want to "also fix" something, file an issue.

---

# File Structure

## PR A — Backend data model + contradiction check

### Files to create

| Path | Responsibility |
|---|---|
| `src/wikimind/engine/linter/__init__.py` | Re-exports `run_lint`, `detect_contradictions`. |
| `src/wikimind/engine/linter/runner.py` | `run_lint(session)` orchestrator. Creates the `LintReport`, calls each enabled detection function, persists findings, emits WS event. |
| `src/wikimind/engine/linter/findings.py` | Pydantic `ContradictionFinding`, `OrphanFinding` in-memory models returned by detection functions. |
| `src/wikimind/engine/linter/contradictions.py` | `detect_contradictions(session, router, settings)` implementation. |
| `src/wikimind/engine/linter/pair_cache.py` | Pair-cache helpers: key by `(article_a_id, article_b_id, updated_at_a, updated_at_b)`. |
| `src/wikimind/engine/linter/prompts.py` | LLM prompt constants (contradiction system prompt, user template). |
| `src/wikimind/services/linter.py` | `LinterService` with `trigger_run`, `list_reports`, `get_report`, `get_latest`, `dismiss_finding`, plus `get_linter_service()` DI provider. |
| `src/wikimind/api/routes/lint.py` | `POST /lint/run`, `GET /lint/reports`, `GET /lint/reports/latest`, `GET /lint/reports/{id}`, `POST /lint/findings/{id}/dismiss`. |
| `tests/unit/test_linter_contradictions.py` | Unit tests for `detect_contradictions` with mocked router. |
| `tests/unit/test_linter_runner.py` | Unit tests for `run_lint` orchestration (counts, status transitions, failure handling). |
| `tests/unit/test_linter_service.py` | Unit tests for `LinterService` list/get/dismiss. |
| `tests/integration/test_lint_api.py` | End-to-end API test for `POST /lint/run` → `GET /lint/reports/latest`. |

### Files to modify

| Path | What changes |
|---|---|
| `src/wikimind/config.py` | Add `LinterConfig` Pydantic submodel. Wire it into `Settings` as `linter: LinterConfig`. |
| `src/wikimind/models.py` | Add `LintSeverity`, `LintFindingKind`, `LintReportStatus` enums; add `LintReport`, `LintFinding`, `DismissedFinding` SQLModel tables; add `LintReportSummary`, `LintReportDetail`, `LintRunResponse`, `DismissResponse` Pydantic response schemas. |
| `src/wikimind/jobs/worker.py` | Rewrite the body of `lint_wiki` to call `run_lint(session)`. Preserve the `Job` row bookkeeping around the call. Drop the old single-prompt block. |
| `src/wikimind/api/routes/jobs.py` | Make `POST /jobs/lint` a shim that delegates to `LinterService.trigger_run()`. Add a deprecation docstring. |
| `src/wikimind/api/routes/wiki.py` | Reshape `GET /wiki/health` to read from the new tables and return a back-compat JSON shape. Add a deprecation docstring. |
| `src/wikimind/services/wiki.py` | Update `get_health` to query `LintReport` / `LintFinding` and project to the legacy `HealthReport` shape. |
| `src/wikimind/main.py` | Register the new `lint` router from `api/routes/lint.py`. |
| `tests/unit/test_linter_jobs.py` (NEW or fold into `tests/unit/test_worker.py` if it exists) | Test that the rewritten `lint_wiki` calls `run_lint`. |
| `.env.example` | Add `WIKIMIND_LINTER__*` entries matching the new Settings fields. |

## PR B — Frontend health view

### Files to create

| Path | Responsibility |
|---|---|
| `apps/web/src/api/lint.ts` | Typed API client methods and interfaces. |
| `apps/web/src/components/health/HealthView.tsx` | Page container for `/health`. |
| `apps/web/src/components/health/LintReportSummary.tsx` | Top-card summary: counts, last-run timestamp, "Run lint now" button. |
| `apps/web/src/components/health/FindingsByKindTabs.tsx` | Tabs grouping findings by kind. |
| `apps/web/src/components/health/FindingCard.tsx` | One finding with dismiss + links. |
| `apps/web/src/components/health/RunLintButton.tsx` | Trigger button with in-flight state. |

### Files to modify

| Path | What changes |
|---|---|
| `apps/web/src/App.tsx` | Add `<Route path="/health" element={<HealthView />} />`. |
| `apps/web/src/components/shared/Layout.tsx` | Add "Health" nav link after "Wiki". |

## PR C — Orphan detection (depends on #95)

### Files to create

| Path | Responsibility |
|---|---|
| `src/wikimind/engine/linter/orphans.py` | `detect_orphans(session)` — SQL-only, no LLM. |
| `tests/unit/test_linter_orphans.py` | Unit tests for the orphan check. |

### Files to modify

| Path | What changes |
|---|---|
| `src/wikimind/config.py` | Flip `LinterConfig.enable_orphan_detection` default to `True`. |
| `src/wikimind/engine/linter/runner.py` | Wire `detect_orphans` into the dispatch when the flag is enabled. |
| `src/wikimind/models.py` | No new tables. Add `OrphanFinding` to the re-export surface if applicable. |

## PR D — Scheduling polish (optional)

### Files to modify

| Path | What changes |
|---|---|
| `src/wikimind/jobs/worker.py` | Richer cron config if needed (e.g. weekday override via Settings). |
| `src/wikimind/config.py` | Add `LinterConfig.cron_weekday` / `cron_hour` if scheduling becomes configurable. |

---

# PR A — Backend data model + contradiction check

**Branch:** `claude/lint-pr-a-backend`

**Definition of done for PR A:** all tasks below complete, `make verify` green, contradiction unit tests hermetic (no real LLM calls), `POST /lint/run` wires through to the ARQ path, `GET /lint/reports/latest` returns the most recent report with findings, existing `POST /jobs/lint` and `GET /wiki/health` still work (as shims), the old single-prompt stub is gone.

## Task A.1: Add LinterConfig submodel

**Files:** Modify `src/wikimind/config.py`

- [ ] **Step 1: Write a test asserting default LinterConfig values**

Add to `tests/unit/test_misc.py` (the existing settings test location):

```python
def test_linter_config_defaults():
    from wikimind.config import Settings

    s = Settings()
    assert s.linter.enable_orphan_detection is False
    assert s.linter.max_concepts_per_run == 25
    assert s.linter.max_contradiction_pairs_per_concept == 10
    assert s.linter.respect_monthly_budget is True
    assert s.linter.max_cost_per_run_usd == 1.00
    assert s.linter.enable_pair_cache is True
```

Run it, confirm it fails:

```bash
.venv/bin/pytest tests/unit/test_misc.py::test_linter_config_defaults -v
```

- [ ] **Step 2: Add the `LinterConfig` Pydantic submodel**

In `src/wikimind/config.py`, after the existing `QAConfig` class, add:

```python
class LinterConfig(BaseModel):
    """Wiki linter configuration.

    See docs/superpowers/specs/2026-04-08-wiki-linter-design.md § Settings for
    the rationale behind each field.
    """

    # #95 gate — orphan detection is a no-op until the Backlink table is populated
    enable_orphan_detection: bool = False

    # Contradiction detection caps — keep O(LLM calls) bounded per run
    max_concepts_per_run: int = 25
    max_contradiction_pairs_per_concept: int = 10

    # LLM behavior for the contradiction prompt
    contradiction_llm_max_tokens: int = 1024
    contradiction_llm_temperature: float = 0.2

    # Cost budget enforcement
    respect_monthly_budget: bool = True
    max_cost_per_run_usd: float = 1.00

    # Pair-level cache — skip LLM call when neither article's updated_at has changed
    enable_pair_cache: bool = True
```

- [ ] **Step 3: Wire `LinterConfig` into `Settings`**

In the same file, find the `Settings` class and add the field next to `qa: QAConfig`:

```python
    qa: QAConfig = Field(default_factory=QAConfig)
    linter: LinterConfig = Field(default_factory=LinterConfig)
```

- [ ] **Step 4: Run the test + lint + typecheck**

```bash
.venv/bin/pytest tests/unit/test_misc.py::test_linter_config_defaults -v
.venv/bin/ruff check src/wikimind/config.py
.venv/bin/mypy src/wikimind/config.py
```

Expected: test passes, lint clean, typecheck clean.

- [ ] **Step 5: Commit**

```bash
git add src/wikimind/config.py tests/unit/test_misc.py
git commit -m "feat(config): add LinterConfig submodel"
```

## Task A.2: Add LintReport, LintFinding, DismissedFinding tables

**Files:** Modify `src/wikimind/models.py`

- [ ] **Step 1: Add the StrEnum types**

In `src/wikimind/models.py`, near the existing `JobType` / `JobStatus` / `ConfidenceLevel` StrEnum declarations, add:

```python
class LintSeverity(StrEnum):
    """Severity level for a lint finding."""

    INFO = "info"
    WARN = "warn"
    ERROR = "error"


class LintFindingKind(StrEnum):
    """Kind of lint finding — maps 1:1 to a detection function."""

    CONTRADICTION = "contradiction"
    ORPHAN = "orphan"


class LintReportStatus(StrEnum):
    """Lifecycle of a lint report."""

    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    FAILED = "failed"
```

- [ ] **Step 2: Add the three new SQLModel tables**

After the existing `Job` table (around the `CostLog`/`SyncLog` area), add:

```python
class LintReport(SQLModel, table=True):
    """One run of the wiki linter. All findings from a run FK back to this row.

    See docs/superpowers/specs/2026-04-08-wiki-linter-design.md § Data model.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    generated_at: datetime = Field(default_factory=utcnow_naive, index=True)
    completed_at: datetime | None = None
    status: LintReportStatus = LintReportStatus.IN_PROGRESS
    article_count: int = 0
    total_findings: int = 0
    contradictions_count: int = 0
    orphans_count: int = 0
    error_message: str | None = None
    job_id: str | None = Field(default=None, foreign_key="job.id", index=True)


class LintFinding(SQLModel, table=True):
    """One finding from one lint run."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    report_id: str = Field(foreign_key="lintreport.id", index=True)
    kind: LintFindingKind
    severity: LintSeverity = LintSeverity.WARN
    article_id: str | None = Field(default=None, foreign_key="article.id", index=True)
    related_article_id: str | None = Field(default=None, foreign_key="article.id")
    description: str
    raw_json: str = "{}"
    created_at: datetime = Field(default_factory=utcnow_naive)
    dismissed: bool = False
    dismissed_at: datetime | None = None
    # Stable hash for cross-run dismiss suppression. See § Dismiss semantics.
    content_hash: str = Field(index=True)


class DismissedFinding(SQLModel, table=True):
    """Cross-run dismiss record — keyed by content hash.

    When a finding is dismissed, its content_hash is persisted here. Future
    lint runs consult this table at write time and auto-dismiss any finding
    whose content_hash matches a row here.
    """

    content_hash: str = Field(primary_key=True)
    dismissed_at: datetime = Field(default_factory=utcnow_naive)
    reason: str | None = None
```

- [ ] **Step 3: Add Pydantic response schemas**

Near the bottom of the file with the other Pydantic API response models (around `HealthReport`), add:

```python
class LintFindingResponse(BaseModel):
    """One finding as returned by the API."""

    id: str
    kind: LintFindingKind
    severity: LintSeverity
    article_id: str | None
    related_article_id: str | None
    description: str
    raw_json: str
    created_at: datetime
    dismissed: bool
    dismissed_at: datetime | None


class LintReportResponse(BaseModel):
    """Report metadata without findings — used in list views."""

    id: str
    generated_at: datetime
    completed_at: datetime | None
    status: LintReportStatus
    article_count: int
    total_findings: int
    contradictions_count: int
    orphans_count: int
    error_message: str | None


class LintReportDetail(BaseModel):
    """Report metadata plus all (optionally including dismissed) findings."""

    report: LintReportResponse
    findings: list[LintFindingResponse]


class LintRunResponse(BaseModel):
    """Response shape for POST /lint/run."""

    report_id: str
    status: LintReportStatus


class DismissResponse(BaseModel):
    """Response shape for POST /lint/findings/{id}/dismiss."""

    finding_id: str
    dismissed: bool
```

- [ ] **Step 4: Run lint + typecheck**

```bash
.venv/bin/ruff check src/wikimind/models.py
.venv/bin/mypy src/wikimind/models.py
```

Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/wikimind/models.py
git commit -m "feat(models): add LintReport, LintFinding, DismissedFinding tables"
```

## Task A.3: Verify tables created on startup

**Files:** `tests/unit/test_misc.py`

`SQLModel.metadata.create_all()` in `init_db()` creates new tables automatically. No migration-helper change needed. Verify it actually works end-to-end.

- [ ] **Step 1: Write a test asserting the tables exist after init_db**

Add to `tests/unit/test_misc.py`:

```python
@pytest.mark.asyncio
async def test_lint_tables_created_on_init_db(tmp_path, monkeypatch):
    from wikimind.database import init_db, get_session_factory
    from sqlalchemy import text

    monkeypatch.setenv("WIKIMIND_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/lint.db")

    await init_db()
    async with get_session_factory()() as session:
        # Sanity: the three new tables exist
        rows = await session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        )
        table_names = {r[0] for r in rows.all()}

    assert "lintreport" in table_names
    assert "lintfinding" in table_names
    assert "dismissedfinding" in table_names
```

- [ ] **Step 2: Run it**

```bash
.venv/bin/pytest tests/unit/test_misc.py::test_lint_tables_created_on_init_db -v
```

Expected: passes without any `database.py` change.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_misc.py
git commit -m "test(database): assert lint tables created on init_db"
```

## Task A.4: Pydantic Finding models

**Files:** Create `src/wikimind/engine/linter/__init__.py`, `src/wikimind/engine/linter/findings.py`

- [ ] **Step 1: Create the linter package**

```bash
mkdir -p src/wikimind/engine/linter
```

Create `src/wikimind/engine/linter/__init__.py`:

```python
"""Wiki linter — Karpathy pattern's third core operation.

See docs/superpowers/specs/2026-04-08-wiki-linter-design.md.
"""

from wikimind.engine.linter.findings import ContradictionFinding, OrphanFinding

__all__ = ["ContradictionFinding", "OrphanFinding"]
```

- [ ] **Step 2: Create the typed finding models**

Create `src/wikimind/engine/linter/findings.py`:

```python
"""Typed in-memory models returned by each detection function.

Each detection function in engine/linter/*.py returns a list of these typed
Pydantic models. The runner in runner.py converts them to LintFinding SQLModel
rows at persistence time.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from wikimind.models import LintFindingKind


class ContradictionFinding(BaseModel):
    """One contradictory-claim pair between two articles."""

    kind: Literal[LintFindingKind.CONTRADICTION] = LintFindingKind.CONTRADICTION
    article_a_id: str
    article_b_id: str
    description: str
    article_a_claim: str
    article_b_claim: str
    llm_confidence: str  # "high" | "medium" | "low" (LLM self-assessment)


class OrphanFinding(BaseModel):
    """One article with zero inbound AND zero outbound backlinks."""

    kind: Literal[LintFindingKind.ORPHAN] = LintFindingKind.ORPHAN
    article_id: str
    article_title: str
```

- [ ] **Step 3: Lint + typecheck**

```bash
.venv/bin/ruff check src/wikimind/engine/linter/
.venv/bin/mypy src/wikimind/engine/linter/
```

- [ ] **Step 4: Commit**

```bash
git add src/wikimind/engine/linter/
git commit -m "feat(linter): add ContradictionFinding and OrphanFinding models"
```

## Task A.5: Contradiction detection prompts

**Files:** Create `src/wikimind/engine/linter/prompts.py`

- [ ] **Step 1: Add the prompt constants**

Create `src/wikimind/engine/linter/prompts.py`:

```python
"""LLM prompt templates for the linter.

Prompts are module-level constants so they're covered by ruff and unit-tests
can assert on their shape. All prompts follow the strict-JSON contract from
ADR-007.
"""

from __future__ import annotations

CONTRADICTION_SYSTEM_PROMPT = """You are a wiki health auditor. Given two short wiki articles about the same topic, identify any contradictory assertions between their key claims.

Return STRICT JSON only, no prose, matching this schema exactly:

{
  "contradictions": [
    {
      "description": "one-sentence summary of the contradiction",
      "article_a_claim": "the specific claim from article A",
      "article_b_claim": "the specific claim from article B",
      "confidence": "high" | "medium" | "low"
    }
  ]
}

If there are no contradictions between the two articles, return {"contradictions": []}.

Two claims are contradictory only if they cannot both be simultaneously true about the same underlying subject. Different wordings of the same fact are NOT contradictions. Different aspects of the same topic are NOT contradictions. Be conservative — false positives erode user trust."""


CONTRADICTION_USER_TEMPLATE = """Article A: "{article_a_title}"
Key claims:
{article_a_claims}

Article B: "{article_b_title}"
Key claims:
{article_b_claims}

Identify any contradictory assertions between these articles. Return JSON."""
```

- [ ] **Step 2: Lint**

```bash
.venv/bin/ruff check src/wikimind/engine/linter/prompts.py
```

- [ ] **Step 3: Commit**

```bash
git add src/wikimind/engine/linter/prompts.py
git commit -m "feat(linter): add contradiction detection prompts"
```

## Task A.6: Contradiction detection — first failing test

**Files:** Create `tests/unit/test_linter_contradictions.py`

This task starts the TDD cycle for `detect_contradictions`. Step 1 writes a failing test against a function that does not yet exist.

- [ ] **Step 1: Write the happy-path test**

Create `tests/unit/test_linter_contradictions.py`:

```python
"""Unit tests for detect_contradictions — all LLM calls are mocked."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.config import Settings
from wikimind.engine.linter.contradictions import detect_contradictions
from wikimind.engine.linter.findings import ContradictionFinding


@pytest.mark.asyncio
async def test_detect_contradictions_returns_finding_for_mocked_llm_response(
    seeded_session: AsyncSession,
    settings: Settings,
):
    """Two articles in the same concept bucket, LLM mocked to return a contradiction."""
    # Router is mocked to return a single contradiction for any complete() call.
    router = AsyncMock()
    router.complete.return_value.content = json.dumps(
        {
            "contradictions": [
                {
                    "description": "Article A says X is true; Article B says X is false.",
                    "article_a_claim": "X is true.",
                    "article_b_claim": "X is false.",
                    "confidence": "high",
                }
            ]
        }
    )
    router.parse_json_response = lambda r: json.loads(r.content)

    findings = await detect_contradictions(seeded_session, router, settings)

    assert len(findings) == 1
    assert isinstance(findings[0], ContradictionFinding)
    assert findings[0].description.startswith("Article A says")
    assert findings[0].llm_confidence == "high"
```

This test depends on a `seeded_session` fixture that seeds two articles sharing a concept, and a `settings` fixture. These may already exist in `tests/conftest.py`; if not, create them:

```python
# tests/conftest.py — add if missing

import pytest
from wikimind.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
async def seeded_session(async_session):
    """Two articles sharing one concept — ready for contradiction testing."""
    from wikimind.models import Article, Concept
    import json as _json

    concept = Concept(name="test-concept", description="for lint tests")
    async_session.add(concept)
    await async_session.commit()
    await async_session.refresh(concept)

    article_a = Article(
        slug="test-a",
        title="Test Article A",
        file_path="/tmp/test_a.md",
        concept_ids=_json.dumps([concept.id]),
        summary="X is true.",
    )
    article_b = Article(
        slug="test-b",
        title="Test Article B",
        file_path="/tmp/test_b.md",
        concept_ids=_json.dumps([concept.id]),
        summary="X is false.",
    )
    async_session.add_all([article_a, article_b])
    await async_session.commit()

    return async_session
```

(If `async_session` fixture does not exist, check `tests/conftest.py` for whatever the project uses as the standard in-memory SQLite fixture — the Ask slice's `test_qa_loop_integration.py` uses one; copy its setup.)

- [ ] **Step 2: Run it, confirm it fails**

```bash
.venv/bin/pytest tests/unit/test_linter_contradictions.py -v
```

Expected: `ImportError: cannot import name 'detect_contradictions'`. This is the failing test before we write the implementation.

- [ ] **Step 3: Commit the failing test**

```bash
git add tests/unit/test_linter_contradictions.py tests/conftest.py
git commit -m "test(linter): add failing detect_contradictions happy-path test"
```

## Task A.7: Contradiction detection — minimal implementation

**Files:** Create `src/wikimind/engine/linter/contradictions.py`

- [ ] **Step 1: Write the minimal implementation**

Create `src/wikimind/engine/linter/contradictions.py`:

```python
"""Contradiction detection check.

For each concept bucket, enumerate article pairs up to the configured cap and
ask the LLM whether the two articles' key claims contradict each other.

All LLM calls go through the shared router so cost tracking and provider
fallback are honored. See docs/superpowers/specs/2026-04-08-wiki-linter-design.md
§ Check: detect_contradictions.
"""

from __future__ import annotations

import itertools
import json
from typing import Any

import structlog
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.config import Settings
from wikimind.engine.linter.findings import ContradictionFinding
from wikimind.engine.linter.prompts import (
    CONTRADICTION_SYSTEM_PROMPT,
    CONTRADICTION_USER_TEMPLATE,
)
from wikimind.models import Article, CompletionRequest, Concept, TaskType

log = structlog.get_logger()


async def detect_contradictions(
    session: AsyncSession,
    router: Any,  # LLMRouter — typed loosely to allow mock injection
    settings: Settings,
) -> list[ContradictionFinding]:
    """Detect contradictions between articles within the same concept bucket.

    Returns a list of ContradictionFinding models. Does NOT persist anything —
    the caller (run_lint) converts these to LintFinding rows.
    """
    findings: list[ContradictionFinding] = []

    # Load concepts, most recently updated first, capped per settings.
    concepts_result = await session.execute(
        select(Concept).order_by(Concept.created_at.desc()).limit(
            settings.linter.max_concepts_per_run
        )
    )
    concepts = concepts_result.scalars().all()

    if not concepts:
        # No concept taxonomy yet — fall back to a single "all articles" bucket
        # capped at max_contradiction_pairs_per_concept. See spec Open Decision #7.
        articles_result = await session.execute(
            select(Article).order_by(Article.updated_at.desc()).limit(
                settings.linter.max_contradiction_pairs_per_concept * 2
            )
        )
        article_buckets = [list(articles_result.scalars().all())]
    else:
        article_buckets = []
        for concept in concepts:
            bucket = await _load_articles_for_concept(session, concept.id)
            article_buckets.append(bucket)

    for bucket in article_buckets:
        if len(bucket) < 2:
            continue
        pairs = list(itertools.combinations(bucket, 2))[
            : settings.linter.max_contradiction_pairs_per_concept
        ]

        for article_a, article_b in pairs:
            try:
                pair_findings = await _check_pair(
                    article_a, article_b, router, settings
                )
            except Exception as e:  # noqa: BLE001 — LLM failures are logged and skipped
                log.warning(
                    "contradiction check failed for pair",
                    article_a=article_a.id,
                    article_b=article_b.id,
                    error=str(e),
                )
                continue
            findings.extend(pair_findings)

    log.info("detect_contradictions complete", finding_count=len(findings))
    return findings


async def _load_articles_for_concept(
    session: AsyncSession, concept_id: str
) -> list[Article]:
    """Return all articles whose concept_ids JSON array contains concept_id."""
    result = await session.execute(select(Article))
    all_articles = result.scalars().all()
    matched: list[Article] = []
    for article in all_articles:
        if not article.concept_ids:
            continue
        try:
            concept_ids = json.loads(article.concept_ids)
        except (TypeError, json.JSONDecodeError):
            continue
        if concept_id in concept_ids:
            matched.append(article)
    return matched


async def _check_pair(
    article_a: Article,
    article_b: Article,
    router: Any,
    settings: Settings,
) -> list[ContradictionFinding]:
    """Ask the LLM whether these two articles contradict each other."""
    user_msg = CONTRADICTION_USER_TEMPLATE.format(
        article_a_title=article_a.title,
        article_a_claims=article_a.summary or "(no summary)",
        article_b_title=article_b.title,
        article_b_claims=article_b.summary or "(no summary)",
    )

    request = CompletionRequest(
        system=CONTRADICTION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
        max_tokens=settings.linter.contradiction_llm_max_tokens,
        temperature=settings.linter.contradiction_llm_temperature,
        response_format="json",
        task_type=TaskType.LINT,
    )

    response = await router.complete(request, session=None)  # type: ignore[arg-type]
    data = router.parse_json_response(response)
    contradictions = data.get("contradictions", [])

    return [
        ContradictionFinding(
            article_a_id=article_a.id,
            article_b_id=article_b.id,
            description=c["description"],
            article_a_claim=c["article_a_claim"],
            article_b_claim=c["article_b_claim"],
            llm_confidence=c.get("confidence", "medium"),
        )
        for c in contradictions
    ]
```

- [ ] **Step 2: Run the happy-path test**

```bash
.venv/bin/pytest tests/unit/test_linter_contradictions.py -v
```

Expected: passes.

- [ ] **Step 3: Lint + typecheck**

```bash
.venv/bin/ruff check src/wikimind/engine/linter/contradictions.py
.venv/bin/mypy src/wikimind/engine/linter/contradictions.py
```

- [ ] **Step 4: Commit**

```bash
git add src/wikimind/engine/linter/contradictions.py
git commit -m "feat(linter): detect_contradictions minimal implementation"
```

## Task A.8: Contradiction detection — cap and fallback tests

**Files:** Modify `tests/unit/test_linter_contradictions.py`

- [ ] **Step 1: Add a test for the pair cap**

Append to `tests/unit/test_linter_contradictions.py`:

```python
@pytest.mark.asyncio
async def test_detect_contradictions_respects_pair_cap(
    settings: Settings,
    async_session: AsyncSession,
):
    """30 articles in one concept → only max_contradiction_pairs_per_concept calls."""
    import json as _json
    from wikimind.models import Article, Concept

    concept = Concept(name="cap-test", description="test")
    async_session.add(concept)
    await async_session.commit()
    await async_session.refresh(concept)

    for i in range(30):
        async_session.add(
            Article(
                slug=f"cap-{i}",
                title=f"Cap Article {i}",
                file_path=f"/tmp/cap_{i}.md",
                concept_ids=_json.dumps([concept.id]),
                summary=f"Claim {i}.",
            )
        )
    await async_session.commit()

    router = AsyncMock()
    router.complete.return_value.content = json.dumps({"contradictions": []})
    router.parse_json_response = lambda r: json.loads(r.content)

    settings.linter.max_contradiction_pairs_per_concept = 5
    findings = await detect_contradictions(async_session, router, settings)

    assert findings == []
    assert router.complete.call_count == 5


@pytest.mark.asyncio
async def test_detect_contradictions_handles_llm_failure_gracefully(
    seeded_session: AsyncSession,
    settings: Settings,
):
    """An LLM exception on one pair is logged and the run continues."""
    router = AsyncMock()
    router.complete.side_effect = RuntimeError("provider exhausted")
    router.parse_json_response = lambda r: {}

    findings = await detect_contradictions(seeded_session, router, settings)

    assert findings == []  # nothing produced, but no exception propagated


@pytest.mark.asyncio
async def test_detect_contradictions_falls_back_to_all_articles_when_no_concepts(
    async_session: AsyncSession,
    settings: Settings,
):
    """With no Concept rows, the check uses a single 'all articles' bucket."""
    from wikimind.models import Article

    async_session.add(
        Article(
            slug="solo-a",
            title="Solo A",
            file_path="/tmp/solo_a.md",
            summary="A says X.",
        )
    )
    async_session.add(
        Article(
            slug="solo-b",
            title="Solo B",
            file_path="/tmp/solo_b.md",
            summary="B says not-X.",
        )
    )
    await async_session.commit()

    router = AsyncMock()
    router.complete.return_value.content = json.dumps({"contradictions": []})
    router.parse_json_response = lambda r: json.loads(r.content)

    findings = await detect_contradictions(async_session, router, settings)

    assert findings == []
    assert router.complete.call_count == 1  # one pair
```

- [ ] **Step 2: Run the three new tests**

```bash
.venv/bin/pytest tests/unit/test_linter_contradictions.py -v
```

Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_linter_contradictions.py
git commit -m "test(linter): cover pair cap, LLM failure, empty-concepts fallback"
```

## Task A.9: Runner — failing test

**Files:** Create `tests/unit/test_linter_runner.py`

- [ ] **Step 1: Write a failing test for the runner**

Create `tests/unit/test_linter_runner.py`:

```python
"""Unit tests for run_lint — the top-level orchestrator."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.config import Settings
from wikimind.engine.linter.runner import run_lint
from wikimind.models import LintFinding, LintReport, LintReportStatus


@pytest.mark.asyncio
async def test_run_lint_creates_report_with_counts(
    seeded_session: AsyncSession,
    settings: Settings,
):
    """run_lint creates a LintReport and persists each ContradictionFinding."""
    router = AsyncMock()
    router.complete.return_value.content = json.dumps(
        {
            "contradictions": [
                {
                    "description": "Contradiction found",
                    "article_a_claim": "X is true",
                    "article_b_claim": "X is false",
                    "confidence": "high",
                }
            ]
        }
    )
    router.parse_json_response = lambda r: json.loads(r.content)

    with patch("wikimind.engine.linter.runner.get_llm_router", return_value=router):
        report = await run_lint(seeded_session, settings)

    assert report.status == LintReportStatus.COMPLETE
    assert report.contradictions_count == 1
    assert report.total_findings == 1

    findings_result = await seeded_session.execute(
        select(LintFinding).where(LintFinding.report_id == report.id)
    )
    findings = findings_result.scalars().all()
    assert len(findings) == 1
    assert findings[0].description == "Contradiction found"


@pytest.mark.asyncio
async def test_run_lint_marks_failed_on_exception(
    seeded_session: AsyncSession,
    settings: Settings,
):
    """If a detection function raises, the report ends in FAILED."""
    with patch(
        "wikimind.engine.linter.runner.detect_contradictions",
        side_effect=RuntimeError("boom"),
    ):
        report = await run_lint(seeded_session, settings)

    assert report.status == LintReportStatus.FAILED
    assert report.error_message is not None
    assert "boom" in report.error_message
```

- [ ] **Step 2: Run it, confirm ImportError**

```bash
.venv/bin/pytest tests/unit/test_linter_runner.py -v
```

Expected: import error. This is the failing test.

- [ ] **Step 3: Commit the failing test**

```bash
git add tests/unit/test_linter_runner.py
git commit -m "test(linter): add failing run_lint orchestrator tests"
```

## Task A.10: Runner — minimal implementation

**Files:** Create `src/wikimind/engine/linter/runner.py`

- [ ] **Step 1: Write the runner**

```python
"""Top-level lint runner — orchestrates detection functions and persists the report.

See docs/superpowers/specs/2026-04-08-wiki-linter-design.md § Pipeline.
"""

from __future__ import annotations

import hashlib
import json

import structlog
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind._datetime import utcnow_naive
from wikimind.config import Settings, get_settings
from wikimind.engine.linter.contradictions import detect_contradictions
from wikimind.engine.linter.findings import ContradictionFinding
from wikimind.engine.llm_router import get_llm_router
from wikimind.models import (
    Article,
    DismissedFinding,
    LintFinding,
    LintFindingKind,
    LintReport,
    LintReportStatus,
    LintSeverity,
)

log = structlog.get_logger()


async def run_lint(
    session: AsyncSession,
    settings: Settings | None = None,
) -> LintReport:
    """Execute all enabled checks and persist a LintReport with findings."""
    settings = settings or get_settings()

    article_count_result = await session.execute(select(Article))
    article_count = len(article_count_result.scalars().all())

    report = LintReport(
        status=LintReportStatus.IN_PROGRESS,
        article_count=article_count,
    )
    session.add(report)
    await session.commit()
    await session.refresh(report)

    try:
        router = get_llm_router()

        contradiction_findings = await detect_contradictions(
            session, router, settings
        )
        await _persist_findings(session, report.id, contradiction_findings)
        report.contradictions_count = len(contradiction_findings)

        # Orphan detection is PR C; keep the counter at 0 for PR A.
        report.orphans_count = 0

        report.total_findings = report.contradictions_count + report.orphans_count
        report.status = LintReportStatus.COMPLETE
        report.completed_at = utcnow_naive()

    except Exception as e:  # noqa: BLE001
        log.error("run_lint failed", error=str(e))
        report.status = LintReportStatus.FAILED
        report.error_message = str(e)
        report.completed_at = utcnow_naive()

    session.add(report)
    await session.commit()
    await session.refresh(report)
    return report


async def _persist_findings(
    session: AsyncSession,
    report_id: str,
    findings: list[ContradictionFinding],
) -> None:
    """Convert typed findings to LintFinding rows, honoring cross-run dismiss."""
    if not findings:
        return

    # Load all dismissed content hashes up-front — one query, membership test below.
    dismissed_result = await session.execute(select(DismissedFinding.content_hash))
    dismissed_hashes = {row for row in dismissed_result.scalars().all()}

    for f in findings:
        content_hash = _compute_content_hash(f)
        is_auto_dismissed = content_hash in dismissed_hashes
        row = LintFinding(
            report_id=report_id,
            kind=LintFindingKind.CONTRADICTION,
            severity=_severity_for_llm_confidence(f.llm_confidence),
            article_id=f.article_a_id,
            related_article_id=f.article_b_id,
            description=f.description,
            raw_json=json.dumps(
                {
                    "article_a_claim": f.article_a_claim,
                    "article_b_claim": f.article_b_claim,
                    "llm_confidence": f.llm_confidence,
                }
            ),
            content_hash=content_hash,
            dismissed=is_auto_dismissed,
            dismissed_at=utcnow_naive() if is_auto_dismissed else None,
        )
        session.add(row)
    await session.commit()


def _compute_content_hash(finding: ContradictionFinding) -> str:
    """Stable hash for cross-run dismiss suppression."""
    payload = f"{finding.kind}|{finding.article_a_id}|{finding.article_b_id}|{finding.description}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _severity_for_llm_confidence(llm_confidence: str) -> LintSeverity:
    """Map LLM self-reported confidence to severity."""
    return {
        "high": LintSeverity.ERROR,
        "medium": LintSeverity.WARN,
        "low": LintSeverity.INFO,
    }.get(llm_confidence, LintSeverity.WARN)
```

- [ ] **Step 2: Update `engine/linter/__init__.py` to re-export `run_lint`**

```python
from wikimind.engine.linter.findings import ContradictionFinding, OrphanFinding
from wikimind.engine.linter.runner import run_lint

__all__ = ["ContradictionFinding", "OrphanFinding", "run_lint"]
```

- [ ] **Step 3: Run the runner tests**

```bash
.venv/bin/pytest tests/unit/test_linter_runner.py -v
```

Expected: passes.

- [ ] **Step 4: Run all linter tests and lint**

```bash
.venv/bin/pytest tests/unit/test_linter_*.py -v
.venv/bin/ruff check src/wikimind/engine/linter/
.venv/bin/mypy src/wikimind/engine/linter/
```

- [ ] **Step 5: Commit**

```bash
git add src/wikimind/engine/linter/runner.py src/wikimind/engine/linter/__init__.py
git commit -m "feat(linter): run_lint orchestrator with dismiss suppression"
```

## Task A.11: LinterService

**Files:** Create `src/wikimind/services/linter.py`, `tests/unit/test_linter_service.py`

- [ ] **Step 1: Write a failing service test**

Create `tests/unit/test_linter_service.py`:

```python
"""Unit tests for LinterService."""

from __future__ import annotations

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.models import (
    DismissedFinding,
    LintFinding,
    LintFindingKind,
    LintReport,
    LintReportStatus,
)
from wikimind.services.linter import LinterService


@pytest.mark.asyncio
async def test_get_latest_returns_most_recent_report(async_session: AsyncSession):
    service = LinterService()

    # Create two reports — second is newer
    r1 = LintReport(status=LintReportStatus.COMPLETE, article_count=5)
    r2 = LintReport(status=LintReportStatus.COMPLETE, article_count=6)
    async_session.add_all([r1, r2])
    await async_session.commit()
    await async_session.refresh(r2)

    detail = await service.get_latest(async_session)
    assert detail.report.id == r2.id


@pytest.mark.asyncio
async def test_dismiss_finding_sets_flag_and_creates_dismissed_record(
    async_session: AsyncSession,
):
    service = LinterService()

    report = LintReport(status=LintReportStatus.COMPLETE, article_count=1)
    async_session.add(report)
    await async_session.commit()
    await async_session.refresh(report)

    finding = LintFinding(
        report_id=report.id,
        kind=LintFindingKind.CONTRADICTION,
        description="test",
        content_hash="abc123",
    )
    async_session.add(finding)
    await async_session.commit()
    await async_session.refresh(finding)

    result = await service.dismiss_finding(async_session, finding.id)
    assert result.dismissed is True

    # DismissedFinding row was created
    dismissed = await async_session.get(DismissedFinding, "abc123")
    assert dismissed is not None
```

Run it, confirm ImportError.

- [ ] **Step 2: Implement LinterService**

Create `src/wikimind/services/linter.py`:

```python
"""Linter service — thin persistence layer over engine/linter/*."""

from __future__ import annotations

import structlog
from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind._datetime import utcnow_naive
from wikimind.jobs.background import BackgroundCompiler
from wikimind.models import (
    DismissedFinding,
    LintFinding,
    LintFindingResponse,
    LintReport,
    LintReportDetail,
    LintReportResponse,
    LintRunResponse,
)

log = structlog.get_logger()


class LinterService:
    """Thin persistence + dispatch for the linter."""

    def __init__(self, background: BackgroundCompiler | None = None) -> None:
        self._background = background or BackgroundCompiler()

    async def trigger_run(self) -> LintRunResponse:
        """Schedule a lint run and return a placeholder report id + status.

        The actual LintReport row is created by run_lint inside the worker;
        this endpoint is fire-and-forget from the caller's perspective. The
        caller polls GET /lint/reports/latest to see the eventual result.
        """
        job_id = await self._background.schedule_lint()
        log.info("lint run triggered", job_id=job_id)
        return LintRunResponse(report_id=job_id, status="in_progress")

    async def list_reports(
        self, session: AsyncSession, limit: int = 20
    ) -> list[LintReportResponse]:
        result = await session.execute(
            select(LintReport).order_by(LintReport.generated_at.desc()).limit(limit)
        )
        return [_report_to_response(r) for r in result.scalars().all()]

    async def get_latest(self, session: AsyncSession) -> LintReportDetail:
        result = await session.execute(
            select(LintReport).order_by(LintReport.generated_at.desc()).limit(1)
        )
        report = result.scalar_one_or_none()
        if report is None:
            raise HTTPException(status_code=404, detail="no lint reports yet")
        return await self._load_detail(session, report, include_dismissed=False)

    async def get_report(
        self,
        session: AsyncSession,
        report_id: str,
        *,
        include_dismissed: bool = False,
    ) -> LintReportDetail:
        report = await session.get(LintReport, report_id)
        if report is None:
            raise HTTPException(status_code=404, detail="report not found")
        return await self._load_detail(session, report, include_dismissed)

    async def dismiss_finding(
        self, session: AsyncSession, finding_id: str
    ) -> LintFindingResponse:
        finding = await session.get(LintFinding, finding_id)
        if finding is None:
            raise HTTPException(status_code=404, detail="finding not found")

        finding.dismissed = True
        finding.dismissed_at = utcnow_naive()
        session.add(finding)

        existing = await session.get(DismissedFinding, finding.content_hash)
        if existing is None:
            session.add(DismissedFinding(content_hash=finding.content_hash))

        await session.commit()
        await session.refresh(finding)
        return _finding_to_response(finding)

    async def _load_detail(
        self,
        session: AsyncSession,
        report: LintReport,
        include_dismissed: bool,
    ) -> LintReportDetail:
        query = select(LintFinding).where(LintFinding.report_id == report.id)
        if not include_dismissed:
            query = query.where(LintFinding.dismissed.is_(False))  # type: ignore[attr-defined]
        findings_result = await session.execute(query)
        findings = [_finding_to_response(f) for f in findings_result.scalars().all()]
        return LintReportDetail(report=_report_to_response(report), findings=findings)


def get_linter_service() -> LinterService:
    """DI provider."""
    return LinterService()


def _report_to_response(r: LintReport) -> LintReportResponse:
    return LintReportResponse(
        id=r.id,
        generated_at=r.generated_at,
        completed_at=r.completed_at,
        status=r.status,
        article_count=r.article_count,
        total_findings=r.total_findings,
        contradictions_count=r.contradictions_count,
        orphans_count=r.orphans_count,
        error_message=r.error_message,
    )


def _finding_to_response(f: LintFinding) -> LintFindingResponse:
    return LintFindingResponse(
        id=f.id,
        kind=f.kind,
        severity=f.severity,
        article_id=f.article_id,
        related_article_id=f.related_article_id,
        description=f.description,
        raw_json=f.raw_json,
        created_at=f.created_at,
        dismissed=f.dismissed,
        dismissed_at=f.dismissed_at,
    )
```

- [ ] **Step 3: Run tests + lint + typecheck**

```bash
.venv/bin/pytest tests/unit/test_linter_service.py -v
.venv/bin/ruff check src/wikimind/services/linter.py
.venv/bin/mypy src/wikimind/services/linter.py
```

- [ ] **Step 4: Commit**

```bash
git add src/wikimind/services/linter.py tests/unit/test_linter_service.py
git commit -m "feat(services): add LinterService with list/get/dismiss"
```

## Task A.12: Lint API routes

**Files:** Create `src/wikimind/api/routes/lint.py`, register in `main.py`

- [ ] **Step 1: Create the lint router**

```python
"""Lint API routes — /lint/*."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.database import get_session
from wikimind.models import (
    DismissResponse,
    LintReportDetail,
    LintReportResponse,
    LintRunResponse,
)
from wikimind.services.linter import LinterService, get_linter_service

router = APIRouter(prefix="/lint", tags=["lint"])


@router.post("/run", response_model=LintRunResponse)
async def trigger_lint_run(
    service: LinterService = Depends(get_linter_service),
) -> LintRunResponse:
    """Trigger a lint run. Returns immediately; poll /lint/reports/latest."""
    return await service.trigger_run()


@router.get("/reports", response_model=list[LintReportResponse])
async def list_reports(
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    service: LinterService = Depends(get_linter_service),
) -> list[LintReportResponse]:
    """List recent lint reports ordered by generated_at DESC."""
    return await service.list_reports(session, limit=limit)


@router.get("/reports/latest", response_model=LintReportDetail)
async def get_latest_report(
    session: AsyncSession = Depends(get_session),
    service: LinterService = Depends(get_linter_service),
) -> LintReportDetail:
    """Get the most recent lint report with its (non-dismissed) findings."""
    return await service.get_latest(session)


@router.get("/reports/{report_id}", response_model=LintReportDetail)
async def get_report(
    report_id: str,
    include_dismissed: bool = Query(False),
    session: AsyncSession = Depends(get_session),
    service: LinterService = Depends(get_linter_service),
) -> LintReportDetail:
    """Get a single lint report with its findings."""
    return await service.get_report(
        session, report_id, include_dismissed=include_dismissed
    )


@router.post("/findings/{finding_id}/dismiss", response_model=DismissResponse)
async def dismiss_finding(
    finding_id: str,
    session: AsyncSession = Depends(get_session),
    service: LinterService = Depends(get_linter_service),
) -> DismissResponse:
    """Dismiss a finding permanently (cross-run, keyed by content hash)."""
    await service.dismiss_finding(session, finding_id)
    return DismissResponse(finding_id=finding_id, dismissed=True)
```

- [ ] **Step 2: Register the router in `main.py`**

Find the existing router registration block in `src/wikimind/main.py` and add:

```python
from wikimind.api.routes import lint as lint_routes

# ... inside create_app() ...
app.include_router(lint_routes.router)
```

(Match the exact pattern used by the existing `query`, `ingest`, `wiki`, `jobs` registrations.)

- [ ] **Step 3: Regenerate OpenAPI**

```bash
make export-openapi
```

Verify `docs/openapi.yaml` now contains the new `/lint/*` paths.

- [ ] **Step 4: Run lint + typecheck + existing tests**

```bash
.venv/bin/ruff check src/wikimind/api/routes/lint.py
.venv/bin/mypy src/wikimind/api/routes/lint.py
.venv/bin/pytest tests/unit/ -v
```

- [ ] **Step 5: Commit**

```bash
git add src/wikimind/api/routes/lint.py src/wikimind/main.py docs/openapi.yaml
git commit -m "feat(api): add /lint/* routes"
```

## Task A.13: Integration test for the API

**Files:** Create `tests/integration/test_lint_api.py`

- [ ] **Step 1: Write the end-to-end test**

```python
"""Integration test: POST /lint/run → run_lint → GET /lint/reports/latest."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from wikimind.models import Article, Concept


@pytest.mark.asyncio
async def test_lint_run_and_latest_report(
    async_client: AsyncClient,
    async_session,
):
    """The full API path exercises run_lint under a mocked LLM router."""
    import json as _json

    concept = Concept(name="api-test", description="test")
    async_session.add(concept)
    await async_session.commit()
    await async_session.refresh(concept)

    for i, claim in enumerate(["X is true.", "X is false."]):
        async_session.add(
            Article(
                slug=f"api-{i}",
                title=f"API Article {i}",
                file_path=f"/tmp/api_{i}.md",
                concept_ids=_json.dumps([concept.id]),
                summary=claim,
            )
        )
    await async_session.commit()

    router = AsyncMock()
    router.complete.return_value.content = json.dumps(
        {
            "contradictions": [
                {
                    "description": "A says X; B says not-X",
                    "article_a_claim": "X is true.",
                    "article_b_claim": "X is false.",
                    "confidence": "high",
                }
            ]
        }
    )
    router.parse_json_response = lambda r: json.loads(r.content)

    with patch("wikimind.engine.linter.runner.get_llm_router", return_value=router):
        # Trigger a run (in dev mode runs in-process via asyncio.create_task)
        trigger_response = await async_client.post("/lint/run")
        assert trigger_response.status_code == 200

        # Wait for the in-process task to finish — fakeredis or in-process dev mode
        import asyncio
        await asyncio.sleep(0.5)  # deliberately small; dev mode is fast

        latest_response = await async_client.get("/lint/reports/latest")
        assert latest_response.status_code == 200

    body = latest_response.json()
    assert body["report"]["status"] == "complete"
    assert body["report"]["contradictions_count"] == 1
    assert len(body["findings"]) == 1
```

> **Note for the implementer:** the `async_client` fixture pattern comes from the existing Ask slice integration tests (`tests/integration/test_qa_loop_integration.py`). Copy its setup. If the in-process sleep proves flaky, switch to directly calling `run_lint` from the test instead of going through the HTTP trigger — the important assertion is the `/lint/reports/latest` response shape.

- [ ] **Step 2: Run it**

```bash
.venv/bin/pytest tests/integration/test_lint_api.py -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_lint_api.py
git commit -m "test(lint): integration test for /lint/run → /lint/reports/latest"
```

## Task A.14: Rewrite the lint_wiki ARQ stub

**Files:** Modify `src/wikimind/jobs/worker.py`

- [ ] **Step 1: Replace the body of `lint_wiki`**

In `src/wikimind/jobs/worker.py`, replace the entire `async def lint_wiki(ctx):` function body with a minimal dispatcher to `run_lint`:

```python
async def lint_wiki(ctx):
    """Run the wiki linter via the new structured pipeline.

    See docs/superpowers/specs/2026-04-08-wiki-linter-design.md § Migration
    from the stub. This replaces the original single-prompt stub.
    """
    log.info("lint_wiki started")

    from wikimind.engine.linter.runner import run_lint

    async with get_session_factory()() as session:
        job = Job(
            job_type=JobType.LINT_WIKI,
            status=JobStatus.RUNNING,
            started_at=utcnow_naive(),
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)

        try:
            report = await run_lint(session)

            job.status = JobStatus.COMPLETE
            job.completed_at = utcnow_naive()
            job.result_summary = (
                f"{report.contradictions_count} contradictions, "
                f"{report.orphans_count} orphans"
            )
            session.add(job)
            await session.commit()

            # Emit WS event so the frontend refetches
            if report.contradictions_count > 0:
                await emit_linter_alert(
                    "contradiction",
                    [],  # article titles; frontend re-fetches instead of reading this
                )

            log.info("lint_wiki complete", summary=job.result_summary)

        except Exception as e:  # noqa: BLE001
            log.error("lint_wiki failed", error=str(e))
            job.status = JobStatus.FAILED
            job.error = str(e)
            job.completed_at = utcnow_naive()
            session.add(job)
            await session.commit()
```

Delete the now-unused imports at the top of the file (`CompletionRequest`, `router`, `TaskType`, `get_llm_router`) **only if** nothing else in the file needs them. Leave them if `compile_source` still uses them.

- [ ] **Step 2: Run the existing worker tests**

```bash
.venv/bin/pytest tests/ -v -k worker
```

Expected: whatever existing stub test existed may need an update. If none exists, move on.

- [ ] **Step 3: Run lint + typecheck**

```bash
.venv/bin/ruff check src/wikimind/jobs/worker.py
.venv/bin/mypy src/wikimind/jobs/worker.py
```

- [ ] **Step 4: Commit**

```bash
git add src/wikimind/jobs/worker.py
git commit -m "refactor(worker): lint_wiki dispatches to run_lint"
```

## Task A.15: Reshape `GET /wiki/health` and `POST /jobs/lint` as shims

**Files:** Modify `src/wikimind/services/wiki.py`, `src/wikimind/api/routes/wiki.py`, `src/wikimind/api/routes/jobs.py`

- [ ] **Step 1: Update `WikiService.get_health` to read from the new tables**

In `src/wikimind/services/wiki.py`, find the existing `get_health` method and replace its body with a projection of the latest `LintReport` into the legacy `HealthReport` shape. Roughly:

```python
async def get_health(self, session: AsyncSession) -> dict:
    """DEPRECATED. Returns the latest LintReport projected to the legacy HealthReport shape."""
    from wikimind.models import LintReport
    from sqlmodel import select

    result = await session.execute(
        select(LintReport).order_by(LintReport.generated_at.desc()).limit(1)
    )
    report = result.scalar_one_or_none()
    if report is None:
        return {
            "generated_at": None,
            "total_articles": 0,
            "contradictions": [],
            "orphaned_articles": [],
            "stale_articles": [],
            "gap_suggestions": [],
            "coverage_scores": {},
            "cost_this_month_usd": 0.0,
        }

    return {
        "generated_at": report.generated_at.isoformat(),
        "total_articles": report.article_count,
        "contradictions_count": report.contradictions_count,
        "orphans_count": report.orphans_count,
        "total_findings": report.total_findings,
        "status": report.status,
        "report_id": report.id,
    }
```

(The exact legacy shape is whatever the existing callers read. If the frontend is using field X, keep field X in the projection. PR B migrates the frontend off this shim.)

- [ ] **Step 2: Add a deprecation docstring to `/wiki/health` and `/jobs/lint`**

In `src/wikimind/api/routes/wiki.py`, update the `get_health` endpoint docstring:

```python
@router.get("/health")
async def get_health(
    session: AsyncSession = Depends(get_session),
    service: WikiService = Depends(get_wiki_service),
):
    """DEPRECATED: use GET /lint/reports/latest. Kept as a compatibility shim."""
    return await service.get_health(session)
```

In `src/wikimind/api/routes/jobs.py`, update the `trigger_lint` docstring and delegate to `LinterService`:

```python
@router.post("/lint")
async def trigger_lint(
    service: "LinterService" = Depends(get_linter_service),
):
    """DEPRECATED: use POST /lint/run. Kept as a compatibility shim."""
    return await service.trigger_run()
```

Import `LinterService` and `get_linter_service` at the top of `jobs.py`.

- [ ] **Step 3: Lint + test**

```bash
.venv/bin/ruff check src/wikimind/services/wiki.py src/wikimind/api/routes/wiki.py src/wikimind/api/routes/jobs.py
.venv/bin/pytest tests/ -v -k "health or jobs"
```

- [ ] **Step 4: Commit**

```bash
git add src/wikimind/services/wiki.py src/wikimind/api/routes/wiki.py src/wikimind/api/routes/jobs.py
git commit -m "refactor(api): reshape /wiki/health and /jobs/lint as linter shims"
```

## Task A.16: Final `make verify` and PR A wrap-up

- [ ] **Step 1: Run the full verification**

```bash
make verify
```

Expected: green. Lint, format, typecheck, tests, coverage all pass.

- [ ] **Step 2: Update `.env.example`**

Add to `.env.example`:

```bash
# Wiki linter
WIKIMIND_LINTER__ENABLE_ORPHAN_DETECTION=false
WIKIMIND_LINTER__MAX_CONCEPTS_PER_RUN=25
WIKIMIND_LINTER__MAX_CONTRADICTION_PAIRS_PER_CONCEPT=10
WIKIMIND_LINTER__CONTRADICTION_LLM_MAX_TOKENS=1024
WIKIMIND_LINTER__CONTRADICTION_LLM_TEMPERATURE=0.2
WIKIMIND_LINTER__RESPECT_MONTHLY_BUDGET=true
WIKIMIND_LINTER__MAX_COST_PER_RUN_USD=1.00
WIKIMIND_LINTER__ENABLE_PAIR_CACHE=true
```

- [ ] **Step 3: Commit and open PR A**

```bash
git add .env.example
git commit -m "docs(env): document linter settings"
git push -u origin claude/lint-pr-a-backend
gh pr create --title "feat(linter): structured backend + contradiction check (PR A)" --body "$(cat <<'EOF'
## Summary
- New `LintReport` / `LintFinding` / `DismissedFinding` tables
- `engine/linter/` package with `run_lint` + `detect_contradictions`
- `LinterService` + `/lint/*` API surface
- `POST /jobs/lint` and `GET /wiki/health` reshape as compatibility shims
- Weekly ARQ cron now runs the new `run_lint` pipeline

## Spec
docs/superpowers/specs/2026-04-08-wiki-linter-design.md

## Follow-ups
- PR B — frontend health view
- PR C — orphan detection (depends on #95)
- Drop deprecated shim endpoints after one release

## Test plan
- [x] `make verify` green
- [x] Contradiction unit tests hermetic
- [x] Integration test `/lint/run` → `/lint/reports/latest`
EOF
)"
```

---

# PR B — Frontend health view

**Branch:** `claude/lint-pr-b-frontend`

**Depends on:** PR A merged to main so the backend contract is live.

**Definition of done for PR B:** `/health` route renders the latest lint report from `/lint/reports/latest`, the "Run lint now" button triggers a real `POST /lint/run`, dismiss works, WebSocket `linter.alert` event triggers re-fetch.

## Task B.1: API client module

**Files:** Create `apps/web/src/api/lint.ts`

- [ ] **Step 1: Create the typed client**

```typescript
// apps/web/src/api/lint.ts
import { apiClient } from "./client";

export type LintSeverity = "info" | "warn" | "error";
export type LintFindingKind = "contradiction" | "orphan";
export type LintReportStatus = "in_progress" | "complete" | "failed";

export interface LintReport {
  id: string;
  generated_at: string;
  completed_at: string | null;
  status: LintReportStatus;
  article_count: number;
  total_findings: number;
  contradictions_count: number;
  orphans_count: number;
  error_message: string | null;
}

export interface LintFinding {
  id: string;
  kind: LintFindingKind;
  severity: LintSeverity;
  article_id: string | null;
  related_article_id: string | null;
  description: string;
  raw_json: string;
  created_at: string;
  dismissed: boolean;
  dismissed_at: string | null;
}

export interface LintReportDetail {
  report: LintReport;
  findings: LintFinding[];
}

export async function runLint(): Promise<{ report_id: string; status: string }> {
  const response = await apiClient.post("/lint/run");
  return response.data;
}

export async function getLatestReport(): Promise<LintReportDetail> {
  const response = await apiClient.get("/lint/reports/latest");
  return response.data;
}

export async function getReport(id: string, includeDismissed = false): Promise<LintReportDetail> {
  const response = await apiClient.get(`/lint/reports/${id}`, {
    params: { include_dismissed: includeDismissed },
  });
  return response.data;
}

export async function listReports(limit = 20): Promise<LintReport[]> {
  const response = await apiClient.get("/lint/reports", { params: { limit } });
  return response.data;
}

export async function dismissFinding(id: string): Promise<{ finding_id: string; dismissed: boolean }> {
  const response = await apiClient.post(`/lint/findings/${id}/dismiss`);
  return response.data;
}
```

Match the existing `apiClient` import path used in `apps/web/src/api/query.ts`.

- [ ] **Step 2: Typecheck + lint**

```bash
cd apps/web && npm run typecheck && npm run lint
```

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/api/lint.ts
git commit -m "feat(web/api): add lint client module"
```

## Task B.2: HealthView page container

**Files:** Create `apps/web/src/components/health/HealthView.tsx`

- [ ] **Step 1: Create the page container**

```tsx
// apps/web/src/components/health/HealthView.tsx
import { useQuery } from "@tanstack/react-query";
import { getLatestReport } from "../../api/lint";
import { LintReportSummary } from "./LintReportSummary";
import { FindingsByKindTabs } from "./FindingsByKindTabs";

export function HealthView() {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["lint", "latest"],
    queryFn: getLatestReport,
    retry: false,
  });

  if (isLoading) {
    return <div className="p-8">Loading health report…</div>;
  }

  if (error || !data) {
    return (
      <div className="p-8">
        <h1 className="text-2xl font-bold mb-4">Wiki Health</h1>
        <p className="text-gray-600">No lint reports yet.</p>
        <LintReportSummary report={null} onRun={() => refetch()} />
      </div>
    );
  }

  return (
    <div className="p-8 space-y-6">
      <h1 className="text-2xl font-bold">Wiki Health</h1>
      <LintReportSummary report={data.report} onRun={() => refetch()} />
      <FindingsByKindTabs findings={data.findings} onChange={() => refetch()} />
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add apps/web/src/components/health/HealthView.tsx
git commit -m "feat(web/health): HealthView page container"
```

## Task B.3: LintReportSummary + RunLintButton

**Files:** Create `apps/web/src/components/health/LintReportSummary.tsx`, `apps/web/src/components/health/RunLintButton.tsx`

- [ ] **Step 1: RunLintButton**

```tsx
// apps/web/src/components/health/RunLintButton.tsx
import { useState } from "react";
import { runLint } from "../../api/lint";

interface Props {
  onComplete: () => void;
}

export function RunLintButton({ onComplete }: Props) {
  const [running, setRunning] = useState(false);

  const handleClick = async () => {
    setRunning(true);
    try {
      await runLint();
      // Give the background job a moment; HealthView re-fetches on WS event
      setTimeout(() => {
        setRunning(false);
        onComplete();
      }, 2000);
    } catch (e) {
      setRunning(false);
      console.error("lint run failed", e);
    }
  };

  return (
    <button
      onClick={handleClick}
      disabled={running}
      className="px-4 py-2 bg-blue-600 text-white rounded disabled:bg-gray-400"
    >
      {running ? "Running…" : "Run lint now"}
    </button>
  );
}
```

- [ ] **Step 2: LintReportSummary**

```tsx
// apps/web/src/components/health/LintReportSummary.tsx
import type { LintReport } from "../../api/lint";
import { RunLintButton } from "./RunLintButton";

interface Props {
  report: LintReport | null;
  onRun: () => void;
}

export function LintReportSummary({ report, onRun }: Props) {
  return (
    <div className="border rounded p-4 bg-white">
      <div className="flex items-center justify-between mb-4">
        <div>
          {report ? (
            <>
              <p className="text-sm text-gray-500">
                Last run: {new Date(report.generated_at).toLocaleString()}
              </p>
              <p className="text-lg">
                {report.total_findings} findings · {report.article_count} articles
              </p>
            </>
          ) : (
            <p className="text-gray-500">No lint report yet.</p>
          )}
        </div>
        <RunLintButton onComplete={onRun} />
      </div>
      {report && (
        <div className="flex space-x-4 text-sm">
          <span>Contradictions: {report.contradictions_count}</span>
          <span>Orphans: {report.orphans_count}</span>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/components/health/LintReportSummary.tsx apps/web/src/components/health/RunLintButton.tsx
git commit -m "feat(web/health): LintReportSummary + RunLintButton"
```

## Task B.4: FindingCard + FindingsByKindTabs

**Files:** Create `apps/web/src/components/health/FindingCard.tsx`, `apps/web/src/components/health/FindingsByKindTabs.tsx`

- [ ] **Step 1: FindingCard**

```tsx
// apps/web/src/components/health/FindingCard.tsx
import { Link } from "react-router-dom";
import type { LintFinding } from "../../api/lint";
import { dismissFinding } from "../../api/lint";

interface Props {
  finding: LintFinding;
  onDismiss: () => void;
}

const severityStyles: Record<LintFinding["severity"], string> = {
  info: "bg-blue-100 text-blue-800",
  warn: "bg-yellow-100 text-yellow-800",
  error: "bg-red-100 text-red-800",
};

export function FindingCard({ finding, onDismiss }: Props) {
  const handleDismiss = async () => {
    await dismissFinding(finding.id);
    onDismiss();
  };

  return (
    <div className="border rounded p-4 bg-white">
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <span
            className={`inline-block px-2 py-0.5 text-xs rounded ${severityStyles[finding.severity]}`}
          >
            {finding.severity.toUpperCase()}
          </span>
          <p className="mt-2">{finding.description}</p>
          <div className="mt-2 text-sm text-gray-600 space-x-3">
            {finding.article_id && (
              <Link to={`/wiki/${finding.article_id}`} className="underline">
                Article A
              </Link>
            )}
            {finding.related_article_id && (
              <Link to={`/wiki/${finding.related_article_id}`} className="underline">
                Article B
              </Link>
            )}
          </div>
        </div>
        <button
          onClick={handleDismiss}
          className="text-sm text-gray-500 hover:text-gray-800"
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: FindingsByKindTabs**

```tsx
// apps/web/src/components/health/FindingsByKindTabs.tsx
import { useState } from "react";
import type { LintFinding, LintFindingKind } from "../../api/lint";
import { FindingCard } from "./FindingCard";

interface Props {
  findings: LintFinding[];
  onChange: () => void;
}

const KINDS: { key: LintFindingKind; label: string }[] = [
  { key: "contradiction", label: "Contradictions" },
  { key: "orphan", label: "Orphans" },
];

export function FindingsByKindTabs({ findings, onChange }: Props) {
  const [active, setActive] = useState<LintFindingKind>("contradiction");
  const filtered = findings.filter((f) => f.kind === active);

  return (
    <div>
      <div className="flex space-x-2 border-b mb-4">
        {KINDS.map((k) => {
          const count = findings.filter((f) => f.kind === k.key).length;
          return (
            <button
              key={k.key}
              onClick={() => setActive(k.key)}
              className={`px-4 py-2 ${active === k.key ? "border-b-2 border-blue-600 font-semibold" : "text-gray-600"}`}
            >
              {k.label} ({count})
            </button>
          );
        })}
      </div>
      <div className="space-y-3">
        {filtered.length === 0 ? (
          <p className="text-gray-500 text-sm">No findings of this kind.</p>
        ) : (
          filtered.map((f) => (
            <FindingCard key={f.id} finding={f} onDismiss={onChange} />
          ))
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/components/health/FindingCard.tsx apps/web/src/components/health/FindingsByKindTabs.tsx
git commit -m "feat(web/health): FindingCard and FindingsByKindTabs"
```

## Task B.5: Wire the /health route and nav link

**Files:** Modify `apps/web/src/App.tsx`, `apps/web/src/components/shared/Layout.tsx`

- [ ] **Step 1: Add the route**

In `apps/web/src/App.tsx`, add:

```tsx
import { HealthView } from "./components/health/HealthView";

// ... inside <Routes>
<Route path="/health" element={<HealthView />} />
```

- [ ] **Step 2: Add the nav link**

In `apps/web/src/components/shared/Layout.tsx`, add "Health" after "Wiki" matching the existing nav link style.

- [ ] **Step 3: Manual smoke test**

```bash
make dev  # backend
cd apps/web && npm run dev
```

Open http://localhost:5173/health, verify the page renders (either the empty state or — after POST /lint/run — a real report with the mocked happy path if you seed one).

- [ ] **Step 4: Frontend verify**

```bash
cd apps/web && npm run lint && npm run typecheck && npm run build
```

- [ ] **Step 5: Commit + open PR B**

```bash
git add apps/web/src/App.tsx apps/web/src/components/shared/Layout.tsx
git commit -m "feat(web): wire /health route and nav link"
git push -u origin claude/lint-pr-b-frontend
gh pr create --title "feat(web/health): health dashboard view (PR B)" --body "..."
```

---

# PR C — Orphan detection

**Branch:** `claude/lint-pr-c-orphans`

**Depends on:** PR A merged, **and #95 (wikilinks unresolved) merged so the Backlink table is populated by the compiler**.

**Definition of done for PR C:** `detect_orphans` unit-tested with seeded `Backlink` rows; `LinterConfig.enable_orphan_detection` flag flipped to `True` by default; runner dispatches to `detect_orphans` when the flag is enabled; frontend orphan tab shows real findings.

## Task C.1: Failing test for detect_orphans

**Files:** Create `tests/unit/test_linter_orphans.py`

- [ ] **Step 1: Write the test**

```python
"""Unit tests for detect_orphans — pure SQL, no LLM."""

from __future__ import annotations

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.engine.linter.orphans import detect_orphans
from wikimind.models import Article, Backlink


@pytest.mark.asyncio
async def test_detect_orphans_finds_article_with_no_links(async_session: AsyncSession):
    """Seed two articles, one linked and one unlinked; only the unlinked is orphan."""
    a = Article(slug="linked", title="Linked Article", file_path="/tmp/a.md")
    b = Article(slug="orphan", title="Orphan Article", file_path="/tmp/b.md")
    c = Article(slug="target", title="Target Article", file_path="/tmp/c.md")
    async_session.add_all([a, b, c])
    await async_session.commit()
    await async_session.refresh(a)
    await async_session.refresh(c)

    async_session.add(Backlink(source_article_id=a.id, target_article_id=c.id))
    await async_session.commit()

    findings = await detect_orphans(async_session)

    orphan_titles = {f.article_title for f in findings}
    assert "Orphan Article" in orphan_titles
    assert "Linked Article" not in orphan_titles
    assert "Target Article" not in orphan_titles


@pytest.mark.asyncio
async def test_detect_orphans_returns_empty_when_no_articles(async_session: AsyncSession):
    findings = await detect_orphans(async_session)
    assert findings == []
```

Run it, confirm it fails (ImportError).

- [ ] **Step 2: Commit failing test**

```bash
git add tests/unit/test_linter_orphans.py
git commit -m "test(linter): add failing detect_orphans tests"
```

## Task C.2: Implement detect_orphans

**Files:** Create `src/wikimind/engine/linter/orphans.py`

- [ ] **Step 1: Write the implementation**

```python
"""Orphan detection — SQL-only check for articles with no inbound OR outbound backlinks.

Depends on the Backlink table being populated by the compiler (issue #95).
Disabled by default via LinterConfig.enable_orphan_detection until #95 merges.
"""

from __future__ import annotations

import structlog
from sqlalchemy import and_, not_
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.engine.linter.findings import OrphanFinding
from wikimind.models import Article, Backlink

log = structlog.get_logger()


async def detect_orphans(session: AsyncSession) -> list[OrphanFinding]:
    """Return OrphanFinding for each article with zero inbound and zero outbound backlinks."""
    linked_as_source = select(Backlink.source_article_id)
    linked_as_target = select(Backlink.target_article_id)

    result = await session.execute(
        select(Article).where(
            and_(
                not_(Article.id.in_(linked_as_source)),  # type: ignore[attr-defined]
                not_(Article.id.in_(linked_as_target)),  # type: ignore[attr-defined]
            )
        )
    )
    orphans = result.scalars().all()

    findings = [
        OrphanFinding(article_id=a.id, article_title=a.title) for a in orphans
    ]
    log.info("detect_orphans complete", orphan_count=len(findings))
    return findings
```

- [ ] **Step 2: Run the tests**

```bash
.venv/bin/pytest tests/unit/test_linter_orphans.py -v
```

Expected: passes.

- [ ] **Step 3: Commit**

```bash
git add src/wikimind/engine/linter/orphans.py
git commit -m "feat(linter): detect_orphans SQL implementation"
```

## Task C.3: Wire orphans into run_lint

**Files:** Modify `src/wikimind/engine/linter/runner.py`, `src/wikimind/config.py`

- [ ] **Step 1: Flip the default flag**

In `src/wikimind/config.py`, change:

```python
    enable_orphan_detection: bool = True
```

- [ ] **Step 2: Dispatch to detect_orphans in run_lint**

In `runner.py`, inside the `try:` block of `run_lint`, after the contradictions block:

```python
        if settings.linter.enable_orphan_detection:
            from wikimind.engine.linter.orphans import detect_orphans
            orphan_findings = await detect_orphans(session)
            await _persist_orphan_findings(session, report.id, orphan_findings)
            report.orphans_count = len(orphan_findings)
        else:
            report.orphans_count = 0
```

Add a `_persist_orphan_findings` helper alongside `_persist_findings`:

```python
async def _persist_orphan_findings(
    session: AsyncSession,
    report_id: str,
    findings: list,
) -> None:
    """Persist OrphanFinding list as LintFinding rows."""
    import hashlib

    dismissed_result = await session.execute(select(DismissedFinding.content_hash))
    dismissed_hashes = {row for row in dismissed_result.scalars().all()}

    for f in findings:
        content_hash = hashlib.sha256(
            f"orphan|{f.article_id}".encode("utf-8")
        ).hexdigest()
        is_auto_dismissed = content_hash in dismissed_hashes
        row = LintFinding(
            report_id=report_id,
            kind=LintFindingKind.ORPHAN,
            severity=LintSeverity.INFO,
            article_id=f.article_id,
            description=f"Orphan article: {f.article_title}",
            raw_json="{}",
            content_hash=content_hash,
            dismissed=is_auto_dismissed,
            dismissed_at=utcnow_naive() if is_auto_dismissed else None,
        )
        session.add(row)
    await session.commit()
```

- [ ] **Step 3: Add an integration-level test exercising both checks**

Append to `tests/unit/test_linter_runner.py`:

```python
@pytest.mark.asyncio
async def test_run_lint_includes_orphans_when_enabled(
    async_session: AsyncSession,
    settings: Settings,
):
    from wikimind.models import Article, Backlink

    settings.linter.enable_orphan_detection = True

    # Seed: one unlinked article
    orphan = Article(slug="lonely", title="Lonely", file_path="/tmp/lonely.md")
    async_session.add(orphan)
    await async_session.commit()

    router = AsyncMock()
    router.complete.return_value.content = json.dumps({"contradictions": []})
    router.parse_json_response = lambda r: json.loads(r.content)

    with patch("wikimind.engine.linter.runner.get_llm_router", return_value=router):
        report = await run_lint(async_session, settings)

    assert report.status == LintReportStatus.COMPLETE
    assert report.orphans_count == 1
```

- [ ] **Step 4: Run all linter tests**

```bash
.venv/bin/pytest tests/unit/test_linter_*.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/wikimind/engine/linter/runner.py src/wikimind/config.py tests/unit/test_linter_runner.py
git commit -m "feat(linter): wire orphan detection into run_lint"
```

## Task C.4: `make verify` and open PR C

```bash
make verify
git push -u origin claude/lint-pr-c-orphans
gh pr create --title "feat(linter): orphan detection (PR C)" --body "..."
```

---

# PR D — Scheduling polish (optional)

**Status:** Deferred until PR A / B / C are live and the existing weekly cron proves insufficient.

**Scope if it becomes necessary:**

- Make the cron weekday/hour configurable via `LinterConfig` (`cron_weekday: int = 0`, `cron_hour: int = 2`).
- Add a "last run" indicator in the UI showing how recently the cron ran.
- Optionally add an "on every N ingests" trigger by hooking into `ingest.service` to check the count and schedule a lint after the Nth compile.

Do not build PR D without user confirmation — the default weekly cron from the stub is preserved by PR A and is likely sufficient for v1.

---

# PR E — Missing-page detection (deferred indefinitely)

**Status:** Dropped from v1 per spec § Non-goals and § Open decisions #3.

**If it is later added:**

- Prefer reusing #95's compile-time wikilink resolver over a per-article LLM call.
- Add `detect_missing_pages` alongside the other checks.
- Add a new `LintFindingKind.MISSING_PAGE` enum value.
- Update the frontend `FindingsByKindTabs` to include the new tab.
- Depends on #95 being merged.

---

# Acceptance checklist (whole epic)

- [ ] PR A merged; `make verify` green; contradiction unit tests hermetic; `/lint/*` routes live; `jobs/worker.py::lint_wiki` uses `run_lint`; back-compat shims on `/jobs/lint` and `/wiki/health` work.
- [ ] PR B merged; `/health` route renders; "Run lint now" triggers a real lint; dismiss works; WS `linter.alert` event triggers re-fetch.
- [ ] PR C merged after #95; orphan detection flag defaults to `True`; orphan tab in the UI shows real findings.
- [ ] PR D deferred unless scheduling becomes a pain point.
- [ ] PR E deferred indefinitely.
- [ ] Epic #4 closed, #26 closed, #27 closed in PR B.
- [ ] All open decisions in the spec answered in PR descriptions.
