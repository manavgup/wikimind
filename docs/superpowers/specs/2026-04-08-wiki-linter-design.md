# Wiki Linter — Design

**Date:** 2026-04-08
**Status:** Draft (open decisions flagged in § Open decisions)
**Author:** Spec session against the WikiMind / Karpathy LLM Wiki Pattern
**Related issues:** [#4 Epic 4: Health + Linter](https://github.com/manavgup/wikimind/issues/4), [#26 Wiki linter — LLM-powered health audit](https://github.com/manavgup/wikimind/issues/26), [#27 React UI: Health Dashboard](https://github.com/manavgup/wikimind/issues/27), [#95 Wikilinks unresolved](https://github.com/manavgup/wikimind/issues/95)

## Context

The linter is the **third core operation of the Karpathy LLM Wiki Pattern** (gist: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f), alongside ingest and query. Karpathy frames it as a periodic health check that the LLM runs against the wiki to look for contradictions, stale claims, orphan pages, missing pages, and data gaps. Without a lint pass, "the wiki accumulates drift as sources and claims compound" — meaning ingest and query are not enough on their own to keep a compounding knowledge base honest.

WikiMind has ingest and query shipped (the Ask vertical slice closed the Karpathy loop in PR #85/#92/#93). It does **not** yet have a real linter. What it does have is a **stub**: `src/wikimind/jobs/worker.py::lint_wiki` is a single LLM call that dumps the first 50 articles into one prompt, asks for contradictions + orphans + gaps + coverage scores in one pass, and writes the result to `wiki/_meta/health.json` as an opaque blob. There is an ARQ cron wired to run it weekly (`cron_jobs = [cron(lint_wiki, weekday=0, hour=2, minute=0)]`), a `POST /jobs/lint` trigger, a `GET /wiki/health` route that reads the JSON file, a `Job` table entry for each run, a WebSocket `emit_linter_alert` event, and an empty `apps/web/src/components/health/` directory earmarked for the UI. None of this produces structured, queryable, per-finding data; none of it is independently testable check-by-check; and the single-prompt design does not scale past the 50-article cap that already exists in code.

This spec replaces the stub with a real, structured, check-per-function linter backed by a `LintReport` row plus **one table per finding kind** (`ContradictionFinding`, `OrphanFinding`, …), while preserving the existing API surface (`POST /jobs/lint`, `GET /wiki/health`) as a thin compatibility shim on top of the new model so the frontend health dashboard can be built on structured data instead of an opaque JSON blob. See § Data model for why per-kind tables over a single `raw_json` blob.

## Current state — what the linter can build on

The linter is not starting from zero. The relevant infrastructure already exists and should be reused:

| Capability | Where | Used by the linter how |
|---|---|---|
| Multi-provider LLM router with cost tracking | `src/wikimind/engine/llm_router.py` (ADR-003) | All LLM calls go through `get_llm_router().complete()` with `task_type=TaskType.LINT`, which is already defined. Cost tracking and provider fallback are free. |
| ARQ + fakeredis background jobs | `src/wikimind/jobs/worker.py`, `src/wikimind/jobs/background.py` (ADR-002) | The linter runs as a background job. `BackgroundCompiler.schedule_lint()` already exists — we reshape what it does, not whether it exists. The existing weekly cron trigger stays. |
| `ConfidenceLevel` enum on claims | `src/wikimind/models.py::ConfidenceLevel` (ADR-005) | Input signal for contradiction detection: two `SOURCED` claims that contradict each other are a higher-severity finding than two `INFERRED` claims. |
| Article retrieval + scoring | `src/wikimind/engine/qa_agent.py::QAAgent._retrieve_context` | Reusable for "find related articles by shared keywords" when batching article pairs for contradiction detection. The current naive token-overlap scoring is good enough for this — pair-finding doesn't need embeddings. |
| `Backlink` table (schema only) | `src/wikimind/models.py::Backlink` | The ORM table and the `backlinks_in` / `backlinks_out` relationships already exist. **The table is empty in practice** because the compiler never writes rows to it — that's what #95 is about. Orphan detection is therefore blocked on #95 (see § Goals). |
| `Concept` taxonomy | `src/wikimind/models.py::Concept`, `Article.concept_ids` (JSON array) | Used to batch articles that are about the same topic, keeping contradiction detection O(articles within a concept) instead of O(articles²). |
| `Job` table + WS event bus | `src/wikimind/models.py::Job`, `src/wikimind/api/routes/ws.py::emit_linter_alert` | Lint runs get a `Job` row for progress tracking. Completion emits a WebSocket event so the health view can re-fetch without polling. |
| Empty frontend placeholder | `apps/web/src/components/health/` | Target directory for the health view components. Nothing to migrate — the directory is genuinely empty. |
| Stub `lint_wiki` ARQ function + `POST /jobs/lint` + `GET /wiki/health` + weekly cron | `src/wikimind/jobs/worker.py`, `src/wikimind/api/routes/jobs.py`, `src/wikimind/api/routes/wiki.py` | Gets replaced internally. External API surface is preserved as a compatibility shim. See § Migration from the stub. |

**What does not yet exist**: structured per-finding storage, per-check function decomposition, a real `LintReport` + per-kind finding data model, a dedicated health view, dismiss semantics, or any unit tests on the linter path.

## Goals — v1 scope

The linter v1 must:

1. **Detect contradictions** between `key_claims` of different articles that share at least one concept. Contradiction detection is the single highest-value check — it is the one thing no amount of structural analysis can do without an LLM, and it is the one thing a non-linted wiki silently gets wrong.
2. **Detect orphan articles** — articles with zero inbound backlinks AND zero outbound backlinks. **This check depends on #95 (wikilinks unresolved) being merged first.** Until #95 lands, the `Backlink` table is empty and every article looks orphaned, so the check is useless. Call this out in the plan and ship the linter without it if #95 is delayed.
3. **Produce a structured health report** — a `LintReport` row plus N rows across the per-kind finding tables (`ContradictionFinding`, `OrphanFinding`), queryable from SQL, renderable as JSON for the UI. Not an opaque blob.
4. **Persist reports so the user can see history** — every lint run creates a new `LintReport` row. Old reports are retained (no auto-delete in v1).
5. **Run on demand via a manual trigger**, and on the existing weekly cron. The cron already exists; reshape what it does, keep the schedule.
6. **Emit a WebSocket completion event** so the health dashboard re-fetches without polling. The existing `emit_linter_alert` event bus is reusable.

### Explicit in-scope checks for v1

| Check | Implementation | Depends on |
|---|---|---|
| Contradictions | LLM per concept-bucket | Concept taxonomy (exists) |
| Orphans | Pure SQL on `Backlink` table | #95 (Backlink population at compile time) |
| Missing pages | **DROPPED from v1** — see § Non-goals and § Open decisions | — |

## Non-goals — v1

Each of these is a real Karpathy lint category that v1 deliberately defers:

- **Stale claims detection** — requires per-claim timestamps and a way to know when a source has been superseded. `Article.updated_at` exists but `CompiledClaim` has no timestamp of its own, and "superseded" needs cross-article reasoning that is expensive. Out of scope. File as follow-up if the user wants it.
- **Data gaps detection** — requires a model of user interest (queries asked, queries left unanswered, topics the user has spent time on). This is a phase-5 signal that does not exist yet. Out of scope.
- **Missing pages detection** — the algorithm is either "LLM-per-article" (expensive, redundant with contradiction detection's token budget) or "reuse #95's wikilink resolver" (blocked on #95 being merged and also on a decision about whether missing-page surfacing belongs in lint or in the compile-time resolver itself). Dropped from v1 by recommendation; see § Open decisions.
- **Auto-fix / auto-rewrite** — the linter is strictly read-only in v1. It surfaces findings and lets the user decide what to do about them. Auto-fix is a massive blast-radius feature that requires a separate design.
- **Compiler prompt engineering** — contradiction detection may reveal patterns that would be better prevented at compile time, but v1 does not touch the compiler. Lint is a separate pass, by design.
- **Per-finding email / push notifications** — WebSocket events are in; external notifications are out.
- **Linter cost dashboard** — cost tracking is already in `CostLog` (keyed by `task_type=LINT`). A dedicated view of lint cost history is a polish item and out of scope.

## Design

### Pipeline

```text
POST /lint/run                        (or weekly cron)
    │
    ▼
BackgroundCompiler.schedule_lint()    (unchanged — ARQ in prod, asyncio.create_task in dev)
    │
    ▼
worker.lint_wiki(ctx)                 (REWRITTEN — dispatch to run_lint)
    │
    ▼
engine/linter/runner.py::run_lint(session)
    │
    ├─► create LintReport(status="in_progress")
    ├─► detect_contradictions(session) → list[ContradictionFinding]
    ├─► detect_orphans(session) → list[OrphanFinding]    # no-op if Backlink table empty
    ├─► persist contradictions to ContradictionFinding, orphans to OrphanFinding
    │     (each row FK'd to the report via report_id)
    ├─► update LintReport(status="complete", counts populated)
    └─► emit_linter_alert event over WebSocket
```

Each check is a **standalone async function** that takes a session and returns a list of typed findings. The top-level `run_lint(session)` is the only thing that knows about `LintReport`; the individual checks know nothing about persistence. This makes each check independently unit-testable, and it makes adding a fourth check in the future a one-line change to `run_lint`.

### Check: `detect_contradictions`

```python
async def detect_contradictions(
    session: AsyncSession,
    router: LLMRouter,
    settings: Settings,
) -> list[ContradictionFinding]:
    """For each concept, LLM-compare article pairs within that concept bucket."""
```

**Algorithm:**

1. Load all `Concept` rows. For each concept, load all `Article` rows whose `concept_ids` JSON array contains that concept's id.
2. Within each concept bucket, enumerate article pairs (up to a cap — see § Settings). Call the LLM once per pair with the two articles' `key_claims` (parsed from the `Article` body or a pre-stored structured field — see § Open decision on input shape).
3. The LLM returns a JSON list of contradictions, each with `description`, `article_a_claim`, `article_b_claim`, `confidence` (high|medium|low). Non-contradictions return an empty list.
4. Return each parsed contradiction as one `ContradictionFinding` instance. Because `ContradictionFinding` is a SQLModel table (see § Data model), `run_lint` persists the returned objects directly — no intermediate conversion step.
5. Cap: `settings.linter.max_contradiction_pairs_per_concept` (default 10). If a concept bucket has more pairs than the cap, sample — do not scan all.
6. Cap: `settings.linter.max_concepts_per_run` (default 25). If the wiki has more concepts than the cap, process the N most-recently-updated concepts first. This keeps a single lint pass bounded at roughly `25 × 10 = 250` LLM calls in the worst case. With caching by `(article_a.id, article_b.id, article_a.updated_at, article_b.updated_at)` across runs (see § Caching), steady-state cost is much lower.

**Prompt sketch** (strict JSON, matching ADR-007 convention):

```text
System: You are a wiki health auditor. Given two short wiki articles about the same topic,
identify any contradictory assertions between their key claims. Return strict JSON.

User:
Article A: "{article_a.title}"
Key claims:
- {claim 1}
- {claim 2}
...

Article B: "{article_b.title}"
Key claims:
- {claim 1}
- {claim 2}
...

Return JSON of this shape:
{
  "contradictions": [
    {
      "description": "one-sentence summary of the contradiction",
      "article_a_claim": "the specific claim from A",
      "article_b_claim": "the specific claim from B",
      "confidence": "high" | "medium" | "low"
    }
  ]
}
If there are no contradictions, return {"contradictions": []}.
```

The LLM call uses `task_type=TaskType.LINT` so cost lands in the existing `CostLog` rows with a distinguishable task type. The provider / model selection is handled by the router per ADR-003 and can be overridden per-request if needed.

### Check: `detect_orphans`

```python
async def detect_orphans(session: AsyncSession) -> list[OrphanFinding]:
    """SQL-only: articles with zero inbound AND zero outbound backlinks."""
```

**Algorithm** (no LLM call):

1. `SELECT article.id FROM article LEFT JOIN backlink bl_in ON bl_in.target_article_id = article.id LEFT JOIN backlink bl_out ON bl_out.source_article_id = article.id WHERE bl_in.target_article_id IS NULL AND bl_out.source_article_id IS NULL`.
2. For each returned id, build an `OrphanFinding(article_id, title)`.

**Dependency note:** This query only produces meaningful results once #95 ships and the `Backlink` table is actually populated by the compiler. Before #95, the table is empty and every article is "orphaned" — the check must be **disabled** in that state. See § Gating orphan detection below.

### Gating orphan detection on #95

Two options for handling the #95 dependency gracefully:

**Option 1 (recommended):** A `settings.linter.enable_orphan_detection: bool = False` flag, default off. Once #95 lands, flip the default to `True` in the same PR that lands #95 (or the PR right after). This keeps the linter shippable without waiting for #95 and makes the dependency explicit.

**Option 2:** Runtime check: `SELECT COUNT(*) FROM backlink` at the start of `detect_orphans`; if zero, return `[]` and log a warning. Simpler but silently hides the feature's absence.

This spec recommends Option 1 because it is explicit in configuration and surfaces the dependency at review time instead of hiding it in a runtime branch.

### Data model

One `LintReport` table plus **one table per finding kind** (`ContradictionFinding`, `OrphanFinding`). All use the existing `utcnow_naive` datetime helper from `src/wikimind/_datetime.py` (the project's replacement for `datetime.utcnow()` — see PRs #60-#64).

**Why per-kind tables instead of a single `LintFinding` with a `raw_json` blob?** The driving requirement is analytics. Questions like "which concepts produced the most contradictions last quarter", "what is the mean LLM confidence for dismissed vs undismissed contradictions", or "how long do orphans stay orphaned on average" are trivial SQL on typed columns and painful on a JSON blob. A single table with `raw_json` is smaller and avoids a new table per check kind, but every future analytics query has to parse JSON in application code. Per-kind tables pay a one-time design cost (one new table when adding a check) for permanent queryability. See § Alternatives for the discarded single-table design, and § Open decisions #9 for the decision record.

A non-table base class `_LintFindingBase` holds fields common to every kind (id, report FK, severity, description, lifecycle fields, content hash). Concrete subclasses add kind-specific columns and set `table=True`. SQLModel supports this pattern natively.

```python
# src/wikimind/models.py

class LintSeverity(StrEnum):
    """Severity level for a lint finding."""

    INFO = "info"
    WARN = "warn"
    ERROR = "error"


class LintFindingKind(StrEnum):
    """Kind of lint finding — maps 1:1 to a detection function AND a table.

    Used as the content_hash prefix (so dismiss state is keyed by kind + content)
    and as the discriminator field in the frontend API response union.
    """

    CONTRADICTION = "contradiction"
    ORPHAN = "orphan"
    # Future: MISSING_PAGE, STALE_CLAIM, DATA_GAP — each adds its own table + enum entry.


class LintReportStatus(StrEnum):
    """Lifecycle of a lint report."""

    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    FAILED = "failed"


class LintReport(SQLModel, table=True):
    """One run of the linter. All findings from a run FK back to this row via report_id."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    generated_at: datetime = Field(default_factory=utcnow_naive, index=True)
    completed_at: datetime | None = None
    status: LintReportStatus = LintReportStatus.IN_PROGRESS
    article_count: int = 0  # snapshot of Article count at run time
    total_findings: int = 0
    contradictions_count: int = 0
    orphans_count: int = 0
    error_message: str | None = None
    # Link back to the Job row so the existing jobs UI can point at the report
    job_id: str | None = Field(default=None, foreign_key="job.id", index=True)


class _LintFindingBase(SQLModel):
    """Fields shared across every per-kind finding table. NOT a table itself."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    report_id: str = Field(foreign_key="lintreport.id", index=True)
    severity: LintSeverity = LintSeverity.WARN
    # Human-readable short description shown in the UI.
    description: str
    created_at: datetime = Field(default_factory=utcnow_naive)
    # Dismiss state is per-finding. Dismissed findings stay in the DB but are
    # filtered out of default queries. See § Dismiss semantics for what "dismissed"
    # means across runs (it is NOT just "hidden in this report").
    dismissed: bool = False
    dismissed_at: datetime | None = None
    # Content hash — stable sha256 of (kind, article ids, description) used for
    # cross-run dedup of dismissed findings. Indexed for O(log n) suppression lookup.
    # See § Dismiss semantics.
    content_hash: str = Field(index=True)


class ContradictionFinding(_LintFindingBase, table=True):
    """A contradiction between key claims of two articles that share a concept."""

    kind: LintFindingKind = Field(default=LintFindingKind.CONTRADICTION)

    # Both articles involved. Required (unlike the old nullable related_article_id).
    article_a_id: str = Field(foreign_key="article.id", index=True)
    article_b_id: str = Field(foreign_key="article.id", index=True)

    # Typed analytics fields — the whole point of per-kind storage.
    article_a_claim: str
    article_b_claim: str
    llm_confidence: str  # "high" | "medium" | "low" — LLM self-assessment

    # Which shared concept produced this pair. Enables
    # "which concepts produce the most contradictions" queries trivially.
    shared_concept_id: str | None = Field(
        default=None, foreign_key="concept.id", index=True
    )


class OrphanFinding(_LintFindingBase, table=True):
    """An article with zero inbound AND zero outbound backlinks."""

    kind: LintFindingKind = Field(default=LintFindingKind.ORPHAN)

    article_id: str = Field(foreign_key="article.id", index=True)
    # Denormalized for display convenience — keeps the frontend from needing a
    # second fetch just to show the title. Also lets "orphans by title prefix"
    # analytics queries stay in one table.
    article_title: str
```

**Schema additions via the lightweight migration helper:** all tables are new, so `SQLModel.metadata.create_all()` in `init_db()` creates them on startup with no migration-helper changes. Matches the `Conversation` table approach from the Ask slice. Each new check kind in the future follows the same pattern: add a subclass of `_LintFindingBase` with `table=True`, add an entry to `LintFindingKind`, add the corresponding SELECT in the service layer (see § Service layer). No migrations to existing tables.

**Check functions return SQLModel instances directly.** Because `ContradictionFinding` and `OrphanFinding` are SQLModel tables (which are Pydantic `BaseModel` subclasses under the hood), the check functions in `engine/linter/contradictions.py` / `engine/linter/orphans.py` return lists of these instances and the runner persists them via `session.add_all(...)`. There is no separate layer of in-memory Pydantic models — the table class is the contract.

**Query shape for "all findings in a report":** the service layer runs one SELECT per kind and composes the result into a `LintReportDetail` object. This is N small SELECTs (where N is the number of finding kinds, currently 2) instead of one UNION — SQLite handles both equally well and the composed object is directly what the frontend needs.

### Settings (no magic numbers)

Per `CLAUDE.md`: "Keep constants configurable via Settings, not hardcoded magic numbers." Add a `LinterConfig` Pydantic submodel to `src/wikimind/config.py` and wire it into `Settings` alongside `server` and `qa`.

```python
class LinterConfig(BaseModel):
    """Wiki linter configuration."""

    # Gating — #95 dependency, see spec § Gating orphan detection
    enable_orphan_detection: bool = False

    # Contradiction detection caps
    max_concepts_per_run: int = 25
    max_contradiction_pairs_per_concept: int = 10

    # LLM behavior
    contradiction_llm_max_tokens: int = 1024
    contradiction_llm_temperature: float = 0.2

    # Cost budget (see § Open decisions)
    respect_monthly_budget: bool = True
    max_cost_per_run_usd: float = 1.00

    # Caching — skip re-evaluating an article pair whose (updated_at_a, updated_at_b)
    # has not changed since the last time we lint-scored it
    enable_pair_cache: bool = True
```

All defaults are conservative and tunable in `.env` via `WIKIMIND_LINTER__*` prefixes, matching the existing `WIKIMIND_SERVER__*` and `WIKIMIND_QA__*` conventions.

### Caching

To keep steady-state cost under control, the linter caches per-pair contradiction results keyed by `(article_a.id, article_b.id, article_a.updated_at, article_b.updated_at)`. A new helper table stores these cache entries. When a run encounters a pair with unchanged `updated_at` on both sides and a cache hit, it reuses the previous finding state instead of re-calling the LLM.

The exact cache storage is deferred to the plan step. The conceptual guarantee is: **a lint run over a wiki where nothing has changed since the last run is zero-LLM-cost**. This matters because the weekly cron will run on mostly-static wikis most weeks.

### API surface

Five new endpoints. The existing stub endpoints are reshaped as compatibility shims.

```text
POST /lint/run
    body: {} (empty)
    returns: { report_id: str, status: "in_progress" }
    side effects: creates a LintReport row, schedules the ARQ job, returns immediately

GET /lint/reports?limit=20
    returns: list[LintReportSummary]  # ordered by generated_at DESC

GET /lint/reports/latest
    returns: LintReportDetail  # most recent report with all (non-dismissed) findings
    404 if no reports exist yet

GET /lint/reports/{report_id}
    returns: LintReportDetail
    query params: ?include_dismissed=false

POST /lint/findings/{kind}/{finding_id}/dismiss
    path params: kind ∈ {"contradiction", "orphan"} — tells the handler which per-kind
                 table to update. Required because finding_id alone does not carry kind.
    returns: { dismissed: true, kind: str, finding_id: str }
    side effect: sets dismissed=true, dismissed_at=now on the per-kind row, and records
                 the content_hash in the DismissedFinding table (see § Dismiss semantics)
                 so future runs suppress equivalent findings automatically.
```

**Compatibility shim endpoints** (preserved because they already exist and have one in-tree caller each):

```text
POST /jobs/lint
    DEPRECATED alias for POST /lint/run. Returns the same payload.
    Keep for one release then remove.

GET /wiki/health
    DEPRECATED. Reshaped to return a JSON-serialized version of the latest
    LintReportDetail, matching the old HealthReport shape as closely as
    possible so any existing frontend caller keeps working during migration.
    Keep for one release then remove.
```

Both shims live in their current files (`api/routes/jobs.py`, `api/routes/wiki.py`) and delegate to the new `LinterService`. The new endpoints live in a new `api/routes/lint.py`.

### Service layer

New file `src/wikimind/services/linter.py`:

```python
class LinterService:
    async def trigger_run(self) -> LintReport: ...
    async def list_reports(self, session: AsyncSession, limit: int = 20) -> list[LintReport]: ...
    async def get_report(self, session: AsyncSession, report_id: str, *, include_dismissed: bool = False) -> LintReportDetail: ...
    async def get_latest(self, session: AsyncSession) -> LintReportDetail: ...
    # Dismissal needs the kind discriminator because the finding_id alone does not
    # tell us which per-kind table to look in.
    async def dismiss_finding(
        self, session: AsyncSession, kind: LintFindingKind, finding_id: str
    ) -> ContradictionFinding | OrphanFinding: ...


def get_linter_service() -> LinterService: ...   # DI provider
```

The service is thin — it persists/loads rows. All check logic lives in `engine/linter/`. `get_report` composes a `LintReportDetail` by running one SELECT per per-kind finding table (currently `ContradictionFinding` and `OrphanFinding`) and returning them in a structured object:

```python
class LintReportDetail(BaseModel):
    """API response shape for a single report."""

    report: LintReport
    contradictions: list[ContradictionFinding]
    orphans: list[OrphanFinding]
```

Adding a new check kind in the future means: add a new `list[NewKindFinding]` field here, and add one more SELECT in `get_report`.

### Engine layer

New directory `src/wikimind/engine/linter/`:

```text
src/wikimind/engine/linter/
├── __init__.py            # re-exports run_lint, detection functions
├── runner.py              # run_lint(session) orchestrator
├── findings.py            # ContradictionFinding, OrphanFinding Pydantic models
├── contradictions.py      # detect_contradictions()
├── orphans.py             # detect_orphans()
├── pair_cache.py          # caching helpers (if non-trivial)
└── prompts.py             # LLM prompt constants
```

### Frontend — new components in `apps/web/src/components/health/`

The placeholder directory is empty today. Six new components:

| Component | Responsibility |
|---|---|
| `HealthView.tsx` | Page container. Two-column layout similar to `WikiExplorerView`. Top: `LintReportSummary`. Bottom: `FindingsByKindTabs`. |
| `LintReportSummary.tsx` | Top card: last-run timestamp, total findings, counts by kind, severity breakdown, "Run lint now" button (triggers `POST /lint/run`). Re-fetches via react-query on WS `linter.alert` event. |
| `FindingsByKindTabs.tsx` | Tab view grouping findings by kind. Default tab: Contradictions. Each tab's count appears in the tab label. |
| `FindingCard.tsx` | One finding. Shows severity badge, description, links to involved article(s) (via `/wiki/:id`), LLM confidence chip, dismiss button. Calls `POST /lint/findings/{id}/dismiss` on dismiss. |
| `RunLintButton.tsx` | Embedded in summary. Shows "Run lint now" when idle; "Running…" with a spinner when a report is in progress; re-enables when complete. |
| `LintHistoryList.tsx` | Optional v1.x: sidebar list of past runs. Omit from v1 if time is tight — a single "latest report" view is enough for the MVP. |

**API client changes** in `apps/web/src/api/` (new file `lint.ts` matching the existing `query.ts` / `wiki.ts` pattern):

```typescript
export interface LintReport { ... }

// Shared fields across every finding kind — mirrors _LintFindingBase on the backend.
interface LintFindingCommon {
  id: string;
  report_id: string;
  severity: "info" | "warn" | "error";
  description: string;
  created_at: string;
  dismissed: boolean;
  dismissed_at: string | null;
  content_hash: string;
}

export interface LintContradictionFinding extends LintFindingCommon {
  kind: "contradiction";
  article_a_id: string;
  article_b_id: string;
  article_a_claim: string;
  article_b_claim: string;
  llm_confidence: "high" | "medium" | "low";
  shared_concept_id: string | null;
}

export interface LintOrphanFinding extends LintFindingCommon {
  kind: "orphan";
  article_id: string;
  article_title: string;
}

export type LintFinding = LintContradictionFinding | LintOrphanFinding;

// The backend returns pre-grouped lists so the UI does not have to filter.
export interface LintReportDetail {
  report: LintReport;
  contradictions: LintContradictionFinding[];
  orphans: LintOrphanFinding[];
}

export async function runLint(): Promise<{ report_id: string; status: string }>;
export async function getLatestReport(): Promise<LintReportDetail>;
export async function getReport(id: string): Promise<LintReportDetail>;
export async function listReports(limit?: number): Promise<LintReport[]>;
// Dismiss needs the kind discriminator so the backend knows which per-kind table to update.
export async function dismissFinding(kind: LintFinding["kind"], id: string): Promise<{ dismissed: boolean }>;
```

**Routing** in `App.tsx`: add `<Route path="/health" element={<HealthView />} />`. **Nav link** in `Layout.tsx`: add "Health" between "Wiki" and any future right-side items, in the same style as the existing Inbox / Ask / Wiki links.

**State management:** react-query for all server state. Cache keys: `["lint", "reports"]`, `["lint", "report", id]`, `["lint", "latest"]`. The WebSocket `linter.alert` event handler invalidates `["lint", "latest"]`.

### Dismiss semantics

A dismissed finding must stay dismissed across runs, otherwise the user plays whack-a-mole with the same contradiction every Monday morning. The design:

1. When a finding is dismissed, compute `content_hash = sha256(kind | article_ids | description)` where `article_ids` is the finding's kind-specific article identifiers (e.g. `article_a_id | article_b_id` for contradictions, `article_id` for orphans). Store the hash in a dedicated `DismissedFinding` table (see below).
2. When a new lint run produces a finding, compute the same hash. If a dismissed entry with that hash exists, mark the new finding as `dismissed=true` at write time (and `dismissed_at` = now).
3. The `content_hash` column is indexed on every per-kind finding table so the suppression lookup is O(log n).

The `DismissedFinding` table is a **separate** SQLModel table — it is deliberately not a column on the per-kind finding tables because dismiss state needs to survive even if the original finding row is eventually garbage-collected:

```python
class DismissedFinding(SQLModel, table=True):
    """Cross-run dismiss record — keyed by content hash."""

    content_hash: str = Field(primary_key=True)
    kind: LintFindingKind  # denormalized for analytics ("how many contradictions dismissed this month?")
    dismissed_at: datetime = Field(default_factory=utcnow_naive)
    reason: str | None = None  # optional user note, v1 leaves null
```

The `kind` column is not strictly necessary (it can be parsed out of the hash input) but denormalizing it makes dismiss-state analytics a simple `GROUP BY kind` and is consistent with the analytics-friendly motivation for per-kind finding tables in the first place.

### Hermetic testing

All linter tests must be hermetic. The LLM router is mocked at the test fixture level (same pattern as the existing Q&A tests). No real network calls. SQLite is real. ARQ is mocked by the existing fakeredis fixtures.

Key test shapes:

| Test | Purpose |
|---|---|
| `test_detect_contradictions_single_concept_with_real_contradiction` | Inject two articles with genuinely contradictory claims into a fixture concept; mock the LLM to return a contradiction; assert the finding is produced. |
| `test_detect_contradictions_respects_pair_cap` | Inject 30 articles in one concept; assert `max_contradiction_pairs_per_concept` caps LLM calls. |
| `test_detect_contradictions_cache_hit_skips_llm` | Run the check twice with no article changes; assert the second run makes zero LLM calls. |
| `test_detect_orphans_returns_empty_when_backlinks_disabled` | Assert the check is a no-op when `enable_orphan_detection=False`. |
| `test_detect_orphans_finds_article_with_no_links_when_enabled` | Inject one linked article and one unlinked article; assert only the unlinked one is in the result. |
| `test_run_lint_creates_report_with_correct_counts` | Integration-ish: run the full pipeline with mocked LLM; assert LintReport.contradictions_count matches. |
| `test_run_lint_sets_status_failed_on_check_exception` | Inject a raising check; assert the report ends in `FAILED` and `error_message` is populated. |
| `test_dismiss_finding_persists_and_suppresses_on_next_run` | Dismiss a finding; re-run the linter with the same inputs; assert the new finding is auto-dismissed. |
| `test_lint_run_endpoint_returns_in_progress_immediately` | POST /lint/run; assert the response is a report_id and status=in_progress; assert the ARQ job was scheduled. |

Coverage target: 90%+ on the new `engine/linter/*` modules, 80%+ on the service and routes. The existing `make verify` 80% floor is enforced and the new code must not regress it.

### Migration from the stub

The existing stub in `jobs/worker.py::lint_wiki` is rewritten rather than deleted so the existing cron and `POST /jobs/lint` entry point keep working:

1. The body of `lint_wiki` is replaced with: open a session, call `run_lint(session)`, done. The existing `emit_linter_alert` call still happens (now from inside `run_lint`).
2. The existing `wiki/_meta/health.json` file is **not written anymore**. The old `GET /wiki/health` endpoint is reshaped to query the new tables instead and produce a back-compat JSON shape.
3. The weekly cron entry stays as-is — it already calls `lint_wiki`.
4. Any existing `health.json` on disk is orphaned. The linter does not delete it; ops can clean it up manually. One release later it stops mattering entirely.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| **Pure-SQL linter (no LLM)** | Orphans are cheap in SQL, but contradictions and missing pages fundamentally need LLM reasoning. Shipping only SQL checks would ship only the easy one. |
| **Synchronous linter (no job queue)** | A lint pass can take minutes with dozens of LLM calls. Blocking the API request on that is wrong. Use the existing ARQ path. |
| **Store findings as markdown in `wiki/_meta/health.md`** | Can't be queried, can't be paginated, can't be dismissed on a per-finding basis. The current stub already stores as JSON and that is already too opaque. |
| **One mega-prompt that asks the LLM to do all checks at once** (what the stub does) | Current behavior. Rejected because (a) it caps at 50 articles or token budget explodes, (b) it produces unstructured output, (c) it can't be incrementally cached, (d) each check can't be unit-tested in isolation, (e) adding a check requires rewriting the prompt. |
| **Auto-fix mode** (linter rewrites articles) | Blast radius too large for a v1. The user must be in the loop. Read-only v1 is the safe default. |
| **Single `LintFinding` table with a `raw_json` blob for kind-specific fields** | Smaller (one table, no new migration per check). Rejected because every future analytics query ("mean LLM confidence on dismissed contradictions", "orphans-by-title-prefix") would have to parse JSON in application code. Per-kind tables move those queries into straight SQL. The one-table-per-kind cost is a single new table each time a check is added, paid once; the JSON-parse cost would be paid on every analytics read forever. See § Data model and § Open decisions #9. |
| **Make the compiler emit contradictions at compile time** | Compiler only sees one source; it cannot compare across articles. Contradiction detection is fundamentally a cross-article operation, which is what lint is for. |

## Consequences

**Enables:**

- **Karpathy pattern completeness.** Ingest + query + lint are the three pillars of the pattern. Shipping the linter closes the structural gap. The wiki can now self-diagnose.
- **User trust in wiki health over time.** The single most important signal from the linter to a user of a compounding knowledge base is "your wiki is not quietly contradicting itself". Without it, the user has to re-read every compiled article to be sure.
- **Empirical signal for Epic 3 (Knowledge Graph).** Contradictions are graph edges with a `conflict` edge type. Missing pages are candidate nodes. Orphans are disconnected components. The linter's outputs are a data source for the graph view.
- **Structured test fixture for compiler regressions.** When a compiler prompt change introduces a contradiction with an existing article, the next lint run will catch it. This is a long-term quality ratchet.
- **Cost-tracked LLM usage visibility.** Every lint call lands in `CostLog` with `task_type=LINT`. Users can see how much the linter costs them per week.

**Constrains:**

- **Orphan detection depends on #95.** Until #95 merges, orphan detection cannot produce meaningful results and is shipped disabled by config flag. This is an architectural coupling that must be honored at review time.
- **Concept taxonomy quality determines contradiction recall.** Two genuinely contradictory articles that don't share a concept will never be compared. Concept auto-generation quality (#24) becomes a linter-blocking dependency for good recall. v1 accepts this limitation; concept quality improvements are tracked separately.
- **LLM reliability determines precision.** LLMs hallucinate contradictions sometimes. Mitigated by showing `llm_confidence` and letting users dismiss, but the linter will produce some false positives. v1 accepts this and makes dismissal easy.

**Risks:**

- **Combinatorial explosion.** A wiki with 100 articles all tagged "AI" would be `100 * 99 / 2 = 4950` pairs in one concept. Mitigated by `max_contradiction_pairs_per_concept=10` cap, but aggressive sampling means some real contradictions will be missed. The cap is tunable in Settings.
- **Cost runaway.** A lint pass over a 100-article wiki could realistically be 20-50 LLM calls on the first run, much less on subsequent runs thanks to the pair cache. Mitigated by `max_cost_per_run_usd` budget, `respect_monthly_budget` flag, and pair caching. See § Open decisions for the budget-enforcement question.
- **False positives eroding trust.** If the first run produces 15 contradictions and 12 of them are the LLM being confused by wording differences, the user dismisses them all and stops looking. Mitigated by showing confidence, letting users dismiss once (sticky), and by persisting `article_a_claim` / `article_b_claim` / `llm_confidence` as explicit `ContradictionFinding` columns so the user can evaluate each finding against the exact quoted claims in context. First-run experience is the critical UX moment for this feature.
- **Dismiss-table unbounded growth.** Every dismissed finding leaves a row in `DismissedFinding` forever. Low risk in practice (users dismiss dozens, not millions) but worth noting. Garbage collection deferred.
- **The weekly cron runs against whatever provider is default at 2am Monday.** No provider pinning. A mid-week provider swap means the next lint run uses the new provider silently. Acceptable for v1; users who care can trigger manually after a provider swap.

## Open decisions — flagged for user review

These should be answered in spec review, not decided autonomously:

1. **Schedule.** Keep the existing weekly Monday-2am cron? Also add a manual trigger (recommended)? Add "run after every N ingests"? **Recommendation: manual trigger + keep existing weekly cron. Defer "after N ingests" to v1.x.**

2. **LLM cost budgeting.** Does the linter respect `LinterConfig.respect_monthly_budget`? If the monthly budget is already near cap, does the linter (a) refuse to run, (b) run in degraded mode (fewer pairs per concept), or (c) run anyway? **Recommendation: refuse with a clear error when `respect_monthly_budget=True` and budget would be exceeded; let the user manually override by flipping the flag.**

3. **Missing-page detection.** Drop from v1 entirely (recommendation) or implement it as a cheap LLM-per-article check (expensive) or defer until #95 ships and reuse the resolver (preferred if kept)? **Recommendation: drop from v1. It is the lowest-value of the three Karpathy checks we could implement (contradictions are higher value, orphans are free once #95 ships). Track as follow-up.**

4. **Contradiction confidence threshold.** Persist all LLM-returned contradictions regardless of confidence? Or only `high` and `medium`? **Recommendation: persist all but filter `low` out of the default UI view; let the user toggle a "show low-confidence" checkbox. Storing them is cheap; hiding them by default is the right first impression.**

5. **Dismiss semantics.** Hide forever, keyed by content hash (recommendation)? Or only hide in the current report, so the user sees the same contradiction re-filed next week? **Recommendation: hide forever via the `DismissedFinding` table. Playing whack-a-mole weekly is a feature killer.**

6. **Dependency on #95.** Acceptable to ship the linter WITHOUT orphan detection if #95 is not yet merged? **Recommendation: yes. Ship v1 with contradictions only. Orphan detection is one small PR (PR C in the implementation plan) that lands the moment #95 merges. This decouples the linter's ship date from #95's ship date.**

7. **Concept taxonomy quality.** Concept auto-generation (#24) is still open. How should the linter behave when no concepts exist yet? **Recommendation: fall back to running contradiction detection across the top-N articles by `updated_at`, using a single synthetic "all articles" bucket capped at `max_contradiction_pairs_per_concept`. This keeps the feature working on a concept-free wiki; it does not replace real concept taxonomies.**

8. **Retention.** Keep lint reports forever? Or auto-delete after N days? **Recommendation: keep forever in v1. Addition later as `linter.report_retention_days` config if the table grows unwieldy (it won't at a weekly cadence).**

9. **Finding-storage shape: single table with `raw_json` blob vs. one table per kind.** **RESOLVED (user, 2026-04-08): per-kind tables.** Rationale: analytics. The whole point of structured lint storage is to enable queries like "which concepts produce the most contradictions" or "mean LLM confidence on dismissed findings" — questions that are trivial SQL on typed columns and painful against a `raw_json` blob. The per-kind cost is one new table per check (paid once), whereas the JSON-parse cost of the single-table approach would be paid on every analytics read forever. v1 ships with `ContradictionFinding` and `OrphanFinding` tables. Future check kinds follow the same pattern (new subclass of `_LintFindingBase`, new enum entry, new SELECT in `LinterService.get_report`). The full rewritten data model is in § Data model, and the rejected alternative is recorded in § Alternatives considered.

## Related issues

Found via `gh issue list --search "lint OR health" --repo manavgup/wikimind --state open`:

- **[#4 Epic 4: Health + Linter](https://github.com/manavgup/wikimind/issues/4)** — the umbrella epic this spec implements. Close or amend when the plan lands.
- **[#26 Wiki linter — LLM-powered health audit](https://github.com/manavgup/wikimind/issues/26)** — the direct backend issue. This spec is its design doc.
- **[#27 React UI: Health Dashboard](https://github.com/manavgup/wikimind/issues/27)** — the direct frontend issue. Implemented in PR B of the plan.
- **[#95 Wikilinks in compiled articles are unresolved](https://github.com/manavgup/wikimind/issues/95)** — hard dependency for orphan detection; see § Gating orphan detection.
- **[#23 Backlink extraction + graph tables](https://github.com/manavgup/wikimind/issues/23)** — adjacent; overlaps with #95's scope for the backlink producer.
- **[#24 Concept taxonomy auto-generation](https://github.com/manavgup/wikimind/issues/24)** — affects contradiction recall quality, not a hard blocker.

## Definition of done

- [ ] PR A (backend, data model + contradictions): new tables migrate cleanly, `detect_contradictions` unit-tested with mocked LLM, `run_lint` integration test passes, `POST /lint/run` + `GET /lint/reports/latest` live, stub `lint_wiki` rewritten to call `run_lint`, old `GET /wiki/health` reshaped to return new-model data.
- [ ] PR B (frontend health view): `HealthView` reachable at `/health`, summary card and findings list render real data from PR A, "Run lint now" button works, dismiss button works, WS `linter.alert` triggers re-fetch.
- [ ] PR C (orphan detection, gated on #95): `detect_orphans` added, `enable_orphan_detection` flag flipped to `True` in the same PR that lands #95.
- [ ] PR D (scheduling polish, optional): richer cron config; currently the existing weekly cron is kept as-is.
- [ ] `make verify` green on every PR. Coverage floor maintained.
- [ ] All open decisions in § Open decisions answered in review and recorded in the PR descriptions.
- [ ] `docs/openapi.yaml` regenerated by the doc-sync hook.
- [ ] Epic #4 closed, #26 closed, #27 closed (PR B), #95 unblocks PR C.
