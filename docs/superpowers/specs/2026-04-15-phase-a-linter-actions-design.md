# Phase A: Linter Actions, Enforcer Integration, Batch LLM

**Date:** 2026-04-15
**Status:** Approved
**Epic:** 4 (Health + Linter)
**Issues:** #137 (Finding Actions), #138 (Batch LLM Calls)

## Context

The Health Dashboard (PR #131) and schema overhaul (PRs #144-#148) delivered contradiction/orphan detection and typed backlinks. The linter loop is detect-surface but not yet detect-surface-**act**. Three gaps remain before Epic 4 is complete:

1. **Finding actions** — users can dismiss findings but cannot navigate to articles, resolve contradictions, or trigger recompiles from the dashboard.
2. **Backlink enforcer** — `enforce_backlinks()` exists and is tested but is not wired into the lint pipeline. Structural violations are invisible.
3. **Batch LLM calls** — contradiction detection makes one LLM call per article pair, which is slow and expensive for concepts with many sources.

## Decisions

### Recompile as a first-class action (ADR-016)

Recompilation is triggered via API and runs asynchronously via ARQ (extending ADR-009's decoupled pattern). Two modes:

- **Source recompile:** Re-reads the raw file from disk, calls the source compiler, overwrites the existing article.
- **Concept re-synthesis:** Re-runs the concept compiler for a concept page, incorporating any new sources or contradiction resolutions.

The endpoint infers mode from the article's `page_type` (source vs concept). Both modes are always async — the API returns immediately with a job ID, the frontend shows "Recompiling..." optimistic state, and auto-refreshes when the WebSocket `article.recompiled` event fires.

### Backlink enforcer as lint phase with auto-repair (ADR-017)

The enforcer runs as the third phase of each lint run (after contradictions and orphans). When it finds auto-repairable issues (missing inverse links for symmetric relation types), it creates the missing link AND reports it as a finding with `auto_repaired=True`. This means lint runs have write side-effects, but only when the fix is deterministic and safe (symmetric link creation). Fixes requiring human judgment (e.g., source missing concepts) are reported without auto-repair.

### Batched LLM calls for contradiction detection (ADR-018)

Article pairs are grouped into batches of N (default 4) per LLM call. On failure: retry the batch once, then fall back to individual per-pair calls. Per-pair cache granularity is preserved — cached pairs are filtered out before batching, and results are saved per-pair after parsing.

## Architecture

### PR 1: Finding Actions (#137)

#### Backend

**New endpoint:** `POST /articles/{article_id}/recompile`

Location: `src/wikimind/api/routes/wiki.py`

```
Request:
  mode: "source" | "concept" | null  (null = infer from page_type)

Response:
  {"status": "scheduled", "job_id": "<uuid>"}
```

Schedules a `recompile_article` job via `BackgroundCompiler`. The job:
1. Loads the article from DB
2. If source: reads raw file from `article.file_path`, calls source compiler
3. If concept: loads the concept, calls `ConceptCompiler.compile_concept_page()`
4. Emits WebSocket event `article.recompiled` with `{article_id, status, page_type}`

**New job type:** `recompile_article` in `src/wikimind/jobs/worker.py`

#### Frontend

**FindingCard.tsx** — contradiction findings get 3 new action buttons:

1. **"View Articles"** — two `<Link>` elements to `/wiki/{article_a_id}` and `/wiki/{article_b_id}`
2. **"Resolve"** — dropdown with options: `source_a_wins`, `source_b_wins`, `both_valid`, `superseded`, plus an optional note text field. Calls existing `POST /wiki/backlinks/{source_id}/{target_id}/resolve`. On success, finding card updates to show resolution badge.
3. **"Recompile"** — calls `POST /articles/{id}/recompile`. Shows "Recompiling..." spinner. Listens for WebSocket `article.recompiled` event to clear the spinner and refresh the report.

**FindingCard.tsx** — orphan findings get 2 new action buttons:

1. **"View Article"** — link to `/wiki/{article_id}`
2. **"Recompile"** — same pattern as above

#### ADR-016

New ADR documenting the recompile action as extending ADR-009's decoupled ingest/compilation pattern.

#### ADR-009 revision

Add note that recompilation is now triggered via API (not just at ingest time). Reference ADR-016.

---

### PR 2: Backlink Enforcer Integration

#### Backend

**New finding kind:** `STRUCTURAL` added to `LintFindingKind` enum in `models.py`.

**New finding model:** `StructuralFinding` extending `_LintFindingBase`:

```python
class StructuralFinding(SQLModel, table=True):
    # inherits: id, report_id, kind, severity, description, dismissed
    article_id: str
    violation_type: str  # source_no_concepts | concept_insufficient_synthesizes | orphan | missing_inverse_link
    auto_repaired: bool = False
    detail: str
```

Violation types:
- `source_no_concepts` — source page has empty `concept_ids`
- `concept_insufficient_synthesizes` — concept page has fewer than 2 `synthesizes` outbound links
- `missing_inverse_link` — symmetric relation type (contradicts, related_to) missing its inverse. Auto-repaired.

Note: orphan detection stays in `detect_orphans()` (Phase 2). The enforcer does not duplicate orphan checks — it focuses on structural invariants that orphan detection does not cover (concept link counts, missing concepts, symmetric link integrity).

**Runner integration:** `src/wikimind/engine/linter/runner.py`

```
Phase 1: detect_contradictions(session, router, settings, report)
Phase 2: detect_orphans(session, settings, report.id)
Phase 3: run_enforcer_checks(session, report)         ← NEW
```

`run_enforcer_checks()`:
1. Loads all articles
2. For each article, calls `enforce_backlinks(article.id, session)`
3. Converts returned warning strings to `StructuralFinding` rows
4. Findings with auto-repair get `auto_repaired=True`
5. Updates `report.checked_articles` for progress tracking

**Progress field:** `LintReport` gets `checked_articles: int | None` alongside existing `checked_pairs`.

#### Frontend

**FindingsByKindTabs.tsx** — third tab: "Structural" with count badge.

**FindingCard** renders structural findings:
- Violation type badge (color-coded per type)
- "View Article" link
- Auto-repaired findings show green "Auto-fixed" label — informational only, no user action needed
- Non-repaired findings show "Recompile" button (reuses PR 1's recompile action)

#### ADR-017

New ADR documenting the enforcer-as-lint-phase pattern and the auto-repair decision.

#### ADR-012 revision

Update status from "Proposed" to "Accepted". Add note about enforcer auto-repair.

---

### PR 3: Batch LLM Calls (#138)

#### Backend

**New prompt templates** in `src/wikimind/engine/linter/prompts.py`:

```python
CONTRADICTION_BATCH_SYSTEM = """You are a wiki health auditor. Given multiple pairs of wiki articles
about the same topic, identify contradictory assertions between each pair's key claims.
Return strict JSON: an array of objects, one per pair_index."""

CONTRADICTION_BATCH_USER = """Compare the following {pair_count} article pairs for contradictions.

{pair_sections}

For each pair, return:
{{"pair_index": <int>, "contradictions": [
  {{"description": "...", "article_a_claim": "...", "article_b_claim": "...", "confidence": "high|medium|low"}}
]}}

Return a JSON array of {pair_count} objects. If a pair has no contradictions, return empty array for that pair."""
```

**Batching logic** in `src/wikimind/engine/linter/contradictions.py`:

1. Collect all uncached pairs for a concept
2. Group into batches of `contradiction_batch_size` (default 4)
3. For each batch:
   a. Make one LLM call with batch prompt
   b. Parse response — map results to individual pairs by `pair_index`
   c. On failure: retry once with same batch
   d. On second failure: fall back to individual per-pair calls for that batch
   e. Save per-pair cache entries for each pair in the batch
4. `report.checked_pairs` incremented per-pair within each batch (smooth progress)

**Cache interaction:** Unchanged. Before batching, filter out cached pairs. Only uncached pairs enter batches. A batch may be smaller than `batch_size` if some pairs were cached.

**Config additions** to `Settings.linter` in `config.py`:

```python
contradiction_batch_size: int = 4
contradiction_batch_enabled: bool = True
```

Env vars: `WIKIMIND_LINTER__CONTRADICTION_BATCH_SIZE`, `WIKIMIND_LINTER__CONTRADICTION_BATCH_ENABLED`.

**No frontend changes.** Batching is invisible to users.

#### ADR-018

New ADR documenting the batch design, retry-then-fallback strategy, and cache preservation.

---

## PR Ordering

```
PR 1: Finding Actions (#137)
  ├── Recompile endpoint + job type
  ├── FindingCard actions (view, resolve, recompile)
  ├── ADR-016 + ADR-009 revision
  └── Tests: endpoint, job, UI actions

PR 2: Backlink Enforcer Integration  [after PR 1 merges]
  ├── STRUCTURAL finding kind + model
  ├── Runner phase 3
  ├── Frontend: Structural tab + cards
  ├── ADR-017 + ADR-012 revision
  └── Tests: enforcer in runner, finding persistence, auto-repair

PR 3: Batch LLM Calls (#138)  [independent, can start anytime]
  ├── Batch prompt template
  ├── Batching logic + retry/fallback
  ├── Config additions
  ├── ADR-018
  └── Tests: batch parsing, retry, fallback, cache interaction
```

PR 3 is fully independent. PR 2 has a soft dependency on PR 1 (FindingCard action pattern is cleaner to extend if already in place).

## Files Modified

### PR 1
- `src/wikimind/api/routes/wiki.py` — recompile endpoint
- `src/wikimind/jobs/worker.py` — recompile_article job
- `apps/web/src/components/health/FindingCard.tsx` — action buttons
- `apps/web/src/api/lint.ts` — recompile API call
- `docs/adr/adr-016-article-recompilation.md` — new
- `docs/adr/adr-009-decoupled-ingest-compilation.md` — revision note

### PR 2
- `src/wikimind/models.py` — STRUCTURAL finding kind, StructuralFinding model
- `src/wikimind/engine/linter/runner.py` — phase 3 dispatch
- `src/wikimind/engine/backlink_enforcer.py` — return structured data (not just strings)
- `apps/web/src/components/health/FindingsByKindTabs.tsx` — structural tab
- `apps/web/src/components/health/FindingCard.tsx` — structural finding display
- `docs/adr/adr-017-backlink-enforcer-lint-phase.md` — new
- `docs/adr/adr-012-knowledge-graph-architecture.md` — status update

### PR 3
- `src/wikimind/engine/linter/prompts.py` — batch templates
- `src/wikimind/engine/linter/contradictions.py` — batching logic
- `src/wikimind/config.py` — batch config fields
- `.env.example` — new env vars
- `docs/adr/adr-018-batched-contradiction-detection.md` — new

## Testing Strategy

### PR 1
- Unit: recompile endpoint returns job ID, handles missing article (404), handles invalid mode
- Unit: recompile_article job calls correct compiler based on page_type
- Integration: recompile source article end-to-end (mock LLM)
- Frontend: FindingCard renders action buttons, resolve dropdown calls API

### PR 2
- Unit: run_enforcer_checks produces StructuralFinding rows for each violation type
- Unit: auto-repaired findings have `auto_repaired=True`
- Unit: enforcer findings persisted and returned in report
- Integration: full lint run includes all 3 phases, findings from all kinds appear in report

### PR 3
- Unit: batch prompt correctly formats N pairs with indices
- Unit: batch response parsed into per-pair results
- Unit: retry on first failure, fallback on second
- Unit: cached pairs excluded from batches
- Unit: per-pair cache saved after batch completes
- Integration: full contradiction run with batching enabled vs disabled produces same findings

## Open Questions

None. All design decisions resolved during brainstorming.
