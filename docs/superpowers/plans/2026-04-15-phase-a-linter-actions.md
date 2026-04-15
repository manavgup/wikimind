# Phase A: Linter Actions, Enforcer Integration, Batch LLM — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the detect-surface-act loop in the Health Dashboard — users can navigate to articles, resolve contradictions, trigger recompiles, see structural violations, and benefit from faster contradiction detection.

**Architecture:** Three independent PRs. PR 1 adds finding actions (view, resolve, recompile). PR 2 wires the backlink enforcer into the lint pipeline with auto-repair. PR 3 batches LLM calls for contradiction detection. Each PR includes its ADR.

**Tech Stack:** Python 3.11+ / FastAPI / SQLModel / SQLAlchemy async / ARQ jobs / React + TypeScript + Tailwind

**Spec:** `docs/superpowers/specs/2026-04-15-phase-a-linter-actions-design.md`

---

## File Structure

### PR 1: Finding Actions (#137)

| Action | Path | Responsibility |
|--------|------|---------------|
| Modify | `src/wikimind/models.py` | Add `RECOMPILE_ARTICLE` to `JobType` enum |
| Modify | `src/wikimind/api/routes/wiki.py` | Add `POST /articles/{article_id}/recompile` endpoint |
| Modify | `src/wikimind/jobs/worker.py` | Add `recompile_article` job function |
| Modify | `src/wikimind/api/routes/ws.py` | Add `emit_article_recompiled` WebSocket event |
| Modify | `apps/web/src/types/api.ts` | Add `recompile_article` to `JobType`, add `article.recompiled` to `WSEvent` |
| Modify | `apps/web/src/api/lint.ts` | Add `recompileArticle()` and `resolveContradiction()` API functions |
| Modify | `apps/web/src/components/health/FindingCard.tsx` | Add View Articles, Resolve, Recompile action buttons |
| Create | `docs/adr/adr-016-article-recompilation.md` | ADR for recompile as first-class action |
| Modify | `docs/adr/adr-009-decoupled-ingest-compilation.md` | Add revision note referencing ADR-016 |
| Create | `tests/unit/test_recompile.py` | Tests for recompile endpoint and job |

### PR 2: Backlink Enforcer Integration

| Action | Path | Responsibility |
|--------|------|---------------|
| Modify | `src/wikimind/models.py` | Add `STRUCTURAL` to `LintFindingKind`, add `StructuralFinding` model, add `structural_count` and `checked_articles` to `LintReport`, add `structurals` to `LintReportDetail` |
| Modify | `src/wikimind/engine/backlink_enforcer.py` | Return structured results (not just strings) |
| Modify | `src/wikimind/engine/linter/runner.py` | Add Phase 3: `run_enforcer_checks()` |
| Modify | `src/wikimind/services/linter.py` | Include structural findings in report queries |
| Modify | `src/wikimind/api/routes/lint.py` | Support `structural` kind in dismiss endpoint |
| Modify | `apps/web/src/api/lint.ts` | Add `LintStructuralFinding` type, update `LintReportDetail` |
| Modify | `apps/web/src/components/health/FindingsByKindTabs.tsx` | Add "Structural" tab |
| Modify | `apps/web/src/components/health/FindingCard.tsx` | Render structural findings |
| Create | `docs/adr/adr-017-backlink-enforcer-lint-phase.md` | ADR for enforcer as lint phase |
| Modify | `docs/adr/adr-012-knowledge-graph-architecture.md` | Update status to Accepted |
| Create | `tests/unit/test_enforcer_integration.py` | Tests for enforcer in lint pipeline |

### PR 3: Batch LLM Calls (#138)

| Action | Path | Responsibility |
|--------|------|---------------|
| Modify | `src/wikimind/engine/linter/prompts.py` | Add batch prompt templates |
| Modify | `src/wikimind/engine/linter/contradictions.py` | Add batching logic with retry/fallback |
| Modify | `src/wikimind/config.py` | Add `contradiction_batch_size` and `contradiction_batch_enabled` to `LinterConfig` |
| Modify | `.env.example` | Add batch config env vars |
| Create | `docs/adr/adr-018-batched-contradiction-detection.md` | ADR for batch design |
| Create | `tests/unit/test_batch_contradictions.py` | Tests for batching, retry, fallback, cache |

---

## PR 1: Finding Actions (#137)

### Task 1: Add RECOMPILE_ARTICLE job type to models

**Files:**
- Modify: `src/wikimind/models.py` (JobType enum, ~line 74-84)

- [ ] **Step 1: Add RECOMPILE_ARTICLE to JobType enum**

In `src/wikimind/models.py`, add `RECOMPILE_ARTICLE` to the `JobType` enum:

```python
class JobType(StrEnum):
    """Type of async job."""
    COMPILE_SOURCE = "compile_source"
    LINT_WIKI = "lint_wiki"
    SWEEP_WIKILINKS = "sweep_wikilinks"
    REINDEX = "reindex"
    EMBED_CHUNKS = "embed_chunks"
    RECOMPILE_ARTICLE = "recompile_article"
    SYNC_PUSH = "sync_push"
    SYNC_PULL = "sync_pull"
```

- [ ] **Step 2: Add recompile_article to frontend JobType**

In `apps/web/src/types/api.ts`, add `"recompile_article"` to the `JobType` union:

```typescript
export type JobType =
  | "compile_source"
  | "lint_wiki"
  | "reindex"
  | "embed_chunks"
  | "recompile_article"
  | "sync_push"
  | "sync_pull";
```

- [ ] **Step 3: Commit**

```bash
git add src/wikimind/models.py apps/web/src/types/api.ts
git commit -s -m "feat(models): add RECOMPILE_ARTICLE job type"
```

### Task 2: Add recompile endpoint and job

**Files:**
- Modify: `src/wikimind/api/routes/wiki.py` (~line 179, after resolve endpoint)
- Modify: `src/wikimind/jobs/worker.py` (~line 202, after lint_wiki)
- Modify: `src/wikimind/api/routes/ws.py` (add emit_article_recompiled)
- Test: `tests/unit/test_recompile.py`

- [ ] **Step 1: Write failing tests for recompile endpoint**

Create `tests/unit/test_recompile.py`:

```python
"""Tests for the article recompile endpoint and job."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from wikimind.models import Article, PageType, Source


@pytest.mark.asyncio
async def test_recompile_source_article(client: AsyncClient, db_session):
    """POST /articles/{id}/recompile schedules a recompile job for source articles."""
    source = Source(
        id=str(uuid.uuid4()),
        source_type="text",
        title="Test Source",
        file_path="/tmp/test.txt",
        status="compiled",
    )
    db_session.add(source)
    article = Article(
        slug="test-article",
        title="Test Article",
        file_path="/tmp/wiki/test-article.md",
        page_type=PageType.SOURCE,
        source_ids=f'["{source.id}"]',
    )
    db_session.add(article)
    await db_session.commit()
    await db_session.refresh(article)

    resp = await client.post(f"/articles/{article.id}/recompile")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "scheduled"
    assert "job_id" in data


@pytest.mark.asyncio
async def test_recompile_missing_article(client: AsyncClient):
    """POST /articles/{id}/recompile returns 404 for non-existent article."""
    resp = await client.post(f"/articles/{uuid.uuid4()}/recompile")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_recompile_concept_article(client: AsyncClient, db_session):
    """POST /articles/{id}/recompile schedules concept re-synthesis for concept pages."""
    article = Article(
        slug="concept-test",
        title="Test Concept",
        file_path="/tmp/wiki/concept-test.md",
        page_type=PageType.CONCEPT,
        concept_ids='["test-concept"]',
    )
    db_session.add(article)
    await db_session.commit()
    await db_session.refresh(article)

    resp = await client.post(f"/articles/{article.id}/recompile")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "scheduled"


@pytest.mark.asyncio
async def test_recompile_explicit_mode(client: AsyncClient, db_session):
    """POST /articles/{id}/recompile?mode=source forces source recompile."""
    article = Article(
        slug="test-explicit",
        title="Test Explicit",
        file_path="/tmp/wiki/test-explicit.md",
        page_type=PageType.SOURCE,
    )
    db_session.add(article)
    await db_session.commit()
    await db_session.refresh(article)

    resp = await client.post(f"/articles/{article.id}/recompile?mode=source")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_recompile_invalid_mode(client: AsyncClient, db_session):
    """POST /articles/{id}/recompile?mode=invalid returns 422."""
    article = Article(
        slug="test-invalid-mode",
        title="Test Invalid Mode",
        file_path="/tmp/wiki/test-invalid.md",
        page_type=PageType.SOURCE,
    )
    db_session.add(article)
    await db_session.commit()
    await db_session.refresh(article)

    resp = await client.post(f"/articles/{article.id}/recompile?mode=invalid")
    assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/mg/mg-work/manav/work/ai-experiments/wikimind && python -m pytest tests/unit/test_recompile.py -v`

Expected: FAIL — endpoint does not exist yet.

- [ ] **Step 3: Add WebSocket emit function for article.recompiled**

In `src/wikimind/api/routes/ws.py`, add (after the existing `emit_linter_alert` function):

```python
async def emit_article_recompiled(article_id: str, page_type: str, status: str = "complete") -> None:
    """Broadcast article.recompiled event to all connected WebSocket clients."""
    await _broadcast(
        {
            "event": "article.recompiled",
            "article_id": article_id,
            "page_type": page_type,
            "status": status,
        }
    )
```

- [ ] **Step 4: Add recompile endpoint to wiki routes**

In `src/wikimind/api/routes/wiki.py`, add after the resolve endpoint (after line 178):

```python
@router.post("/articles/{article_id}/recompile")
async def recompile_article(
    article_id: str,
    mode: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    """Schedule recompilation of an article.

    Mode is inferred from page_type if not specified:
    - source → re-run source compiler on raw file
    - concept → re-synthesize concept page
    """
    from wikimind.models import Job, JobStatus, JobType

    _VALID_MODES = {"source", "concept"}
    if mode is not None and mode not in _VALID_MODES:
        raise HTTPException(status_code=422, detail=f"mode must be one of {sorted(_VALID_MODES)}")

    result = await session.execute(select(Article).where(Article.id == article_id))
    article = result.scalars().first()
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")

    effective_mode = mode or article.page_type
    if effective_mode not in _VALID_MODES:
        effective_mode = "source"

    job = Job(
        job_type=JobType.RECOMPILE_ARTICLE,
        status=JobStatus.QUEUED,
        source_id=article_id,
        result_summary=f"mode={effective_mode}",
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    from wikimind.jobs.background import get_background_compiler
    bg = get_background_compiler()
    await bg.schedule_job("recompile_article", article_id, effective_mode, _job_id=job.id)

    return {"status": "scheduled", "job_id": job.id}
```

- [ ] **Step 5: Add recompile_article job function to worker**

In `src/wikimind/jobs/worker.py`, add after the `lint_wiki` function (after line 202):

```python
async def recompile_article(ctx: dict, article_id: str, mode: str = "source", _job_id: str | None = None) -> None:
    """Re-compile a single article (source recompile or concept re-synthesis)."""
    from wikimind.api.routes.ws import emit_article_recompiled
    from wikimind.database import async_session_factory
    from wikimind.engine.concept_compiler import ConceptCompiler
    from wikimind.engine.compiler import Compiler
    from wikimind.models import Article, Concept, Job, JobStatus, PageType, Source

    async with async_session_factory() as session:
        job: Job | None = None
        if _job_id:
            result = await session.execute(select(Job).where(Job.id == _job_id))
            job = result.scalars().first()
            if job:
                job.status = JobStatus.RUNNING
                job.started_at = utcnow_naive()
                session.add(job)
                await session.flush()

        try:
            result = await session.execute(select(Article).where(Article.id == article_id))
            article = result.scalars().first()
            if article is None:
                raise ValueError(f"Article {article_id} not found")

            if mode == "concept":
                concept_name = None
                if article.concept_ids:
                    import json as _json
                    ids = _json.loads(article.concept_ids)
                    if ids:
                        concept_name = ids[0]
                if concept_name:
                    from slugify import slugify
                    concept_result = await session.execute(
                        select(Concept).where(Concept.name == concept_name)
                    )
                    concept = concept_result.scalars().first()
                    if concept:
                        compiler = ConceptCompiler()
                        await compiler.compile_concept_page(concept, session)
            else:
                # Source recompile: find the source, re-run compiler
                import json as _json
                source_ids = []
                if article.source_ids:
                    source_ids = _json.loads(article.source_ids)
                source_id = source_ids[0] if source_ids else None
                if source_id:
                    source_result = await session.execute(
                        select(Source).where(Source.id == source_id)
                    )
                    source = source_result.scalars().first()
                    if source:
                        compiler = Compiler()
                        from wikimind.services.ingest import NormalizedDocument
                        from pathlib import Path
                        raw_text = Path(source.file_path).read_text(encoding="utf-8")
                        doc = NormalizedDocument(
                            source_id=source.id,
                            title=source.title or article.title,
                            body=raw_text,
                            source_type=source.source_type,
                            source_url=source.source_url,
                        )
                        result_obj = await compiler.compile(doc, session)
                        if result_obj:
                            await compiler.save_article(result_obj, source, session)

            if job:
                job.status = JobStatus.COMPLETE
                job.completed_at = utcnow_naive()
                job.result_summary = f"Recompiled ({mode})"
                session.add(job)

            await session.commit()
            await emit_article_recompiled(article_id, mode, "complete")

        except Exception as e:
            log.error("Recompile failed", article_id=article_id, error=str(e), exc_info=True)
            if job:
                job.status = JobStatus.FAILED
                job.error = str(e)[:500]
                job.completed_at = utcnow_naive()
                session.add(job)
                await session.commit()
            await emit_article_recompiled(article_id, mode, "failed")
```

Also add `recompile_article` to the `WorkerSettings.functions` list at the bottom of worker.py.

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /Users/mg/mg-work/manav/work/ai-experiments/wikimind && python -m pytest tests/unit/test_recompile.py -v`

Expected: All 5 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add src/wikimind/api/routes/wiki.py src/wikimind/api/routes/ws.py src/wikimind/jobs/worker.py tests/unit/test_recompile.py
git commit -s -m "feat(wiki): add POST /articles/{id}/recompile endpoint and job

Closes the act step of the detect-surface-act loop. Supports both
source recompile and concept re-synthesis modes. Always async via
BackgroundCompiler, emits article.recompiled WebSocket event."
```

### Task 3: Add frontend API functions for recompile and resolve

**Files:**
- Modify: `apps/web/src/api/lint.ts`
- Modify: `apps/web/src/types/api.ts`

- [ ] **Step 1: Add article.recompiled to WSEvent type**

In `apps/web/src/types/api.ts`, add to the `WSEvent` union:

```typescript
  | { event: "article.recompiled"; article_id: string; page_type: string; status: string };
```

- [ ] **Step 2: Add recompileArticle and resolveContradiction API functions**

In `apps/web/src/api/lint.ts`, add after the `dismissFinding` function:

```typescript
export async function recompileArticle(
  articleId: string,
  mode?: "source" | "concept",
): Promise<{ status: string; job_id: string }> {
  const params = mode ? `?mode=${mode}` : "";
  return apiFetch(`/articles/${articleId}/recompile${params}`, {
    method: "POST",
  });
}

export async function resolveContradiction(
  sourceId: string,
  targetId: string,
  resolution: string,
  note?: string,
): Promise<{ resolved: boolean }> {
  return apiFetch(
    `/wiki/backlinks/${sourceId}/${targetId}/resolve`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ resolution, resolution_note: note }),
    },
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/api/lint.ts apps/web/src/types/api.ts
git commit -s -m "feat(web): add recompileArticle and resolveContradiction API functions"
```

### Task 4: Add action buttons to FindingCard

**Files:**
- Modify: `apps/web/src/components/health/FindingCard.tsx`

- [ ] **Step 1: Add action buttons to contradiction findings**

Replace the entire `FindingCard.tsx` with the updated version that includes View Articles, Resolve, and Recompile buttons. The key changes are:

1. Import `Link` from `react-router-dom` and the new API functions
2. Add a `ResolveDropdown` component for contradiction resolution
3. Add "View Articles" links for both articles in a contradiction
4. Add "Recompile" button with optimistic loading state
5. Add "View Article" link and "Recompile" for orphan findings

```typescript
import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type {
  LintFinding,
  LintContradictionFinding,
  LintOrphanFinding,
} from "../../api/lint";
import {
  dismissFinding,
  recompileArticle,
  resolveContradiction,
} from "../../api/lint";

function SeverityBadge({ severity }: { severity: string }) {
  const color =
    severity === "error"
      ? "bg-red-100 text-red-700"
      : "bg-amber-100 text-amber-700";
  return (
    <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${color}`}>
      {severity}
    </span>
  );
}

function ContradictionDetail({
  finding,
}: {
  finding: LintContradictionFinding;
}) {
  return (
    <div className="mt-2 space-y-2 text-sm">
      <div className="rounded border border-red-100 bg-red-50 p-2">
        <p className="text-xs font-semibold text-red-600">Article A claim:</p>
        <p className="text-slate-700">{finding.article_a_claim}</p>
      </div>
      <div className="rounded border border-red-100 bg-red-50 p-2">
        <p className="text-xs font-semibold text-red-600">Article B claim:</p>
        <p className="text-slate-700">{finding.article_b_claim}</p>
      </div>
      <p className="text-xs text-slate-500">
        LLM confidence: {finding.llm_confidence}
      </p>
    </div>
  );
}

function ResolveDropdown({
  finding,
}: {
  finding: LintContradictionFinding;
}) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [resolved, setResolved] = useState(false);
  const qc = useQueryClient();

  const resolve = useMutation({
    mutationFn: ({
      resolution,
      note: n,
    }: {
      resolution: string;
      note?: string;
    }) =>
      resolveContradiction(
        finding.article_a_id,
        finding.article_b_id,
        resolution,
        n,
      ),
    onSuccess: () => {
      setResolved(true);
      setOpen(false);
      qc.invalidateQueries({ queryKey: ["lint-report-latest"] });
    },
  });

  if (resolved) {
    return (
      <span className="rounded bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700">
        Resolved
      </span>
    );
  }

  const options = [
    { value: "source_a_wins", label: "Source A wins" },
    { value: "source_b_wins", label: "Source B wins" },
    { value: "both_valid", label: "Both valid" },
    { value: "superseded", label: "Superseded" },
  ];

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50"
      >
        Resolve
      </button>
      {open && (
        <div className="absolute right-0 z-10 mt-1 w-56 rounded-md border border-slate-200 bg-white p-2 shadow-lg">
          {options.map((opt) => (
            <button
              key={opt.value}
              onClick={() => resolve.mutate({ resolution: opt.value, note })}
              disabled={resolve.isPending}
              className="block w-full rounded px-2 py-1 text-left text-xs text-slate-700 hover:bg-slate-100"
            >
              {opt.label}
            </button>
          ))}
          <input
            type="text"
            placeholder="Optional note..."
            value={note}
            onChange={(e) => setNote(e.target.value)}
            className="mt-1 w-full rounded border border-slate-200 px-2 py-1 text-xs"
          />
        </div>
      )}
    </div>
  );
}

function RecompileButton({ articleId }: { articleId: string }) {
  const qc = useQueryClient();
  const recompile = useMutation({
    mutationFn: () => recompileArticle(articleId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["lint-report-latest"] });
    },
  });

  return (
    <button
      onClick={() => recompile.mutate()}
      disabled={recompile.isPending}
      className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-700 hover:bg-slate-50 disabled:opacity-50"
    >
      {recompile.isPending ? "Recompiling..." : "Recompile"}
    </button>
  );
}

function OrphanDetail({ finding }: { finding: LintOrphanFinding }) {
  return (
    <p className="mt-2 text-sm text-slate-600">
      <strong>{finding.article_title}</strong> has no backlinks to or from other
      articles.
    </p>
  );
}

export function FindingCard({ finding }: { finding: LintFinding }) {
  const dismiss = useMutation({
    mutationFn: () => dismissFinding(finding.kind, finding.id),
  });

  if (finding.dismissed) {
    return (
      <div className="rounded-md border border-slate-100 bg-slate-50 p-4 opacity-60">
        <span className="text-xs text-slate-400">Dismissed</span>
      </div>
    );
  }

  const isContradiction = finding.kind === "contradiction";
  const cf = finding as LintContradictionFinding;
  const of = finding as LintOrphanFinding;

  return (
    <div className="rounded-md border border-slate-200 bg-white p-4">
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <div className="mb-1 flex items-center gap-2">
            <SeverityBadge severity={finding.severity} />
          </div>
          <p className="text-sm text-slate-700">{finding.description}</p>
        </div>
      </div>

      {isContradiction ? (
        <>
          <ContradictionDetail finding={cf} />
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Link
              to={`/wiki/${cf.article_a_id}`}
              className="rounded border border-sky-300 px-2 py-1 text-xs text-sky-700 hover:bg-sky-50"
            >
              View Article A
            </Link>
            <Link
              to={`/wiki/${cf.article_b_id}`}
              className="rounded border border-sky-300 px-2 py-1 text-xs text-sky-700 hover:bg-sky-50"
            >
              View Article B
            </Link>
            <ResolveDropdown finding={cf} />
            <RecompileButton articleId={cf.article_a_id} />
          </div>
        </>
      ) : (
        <>
          <OrphanDetail finding={of} />
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Link
              to={`/wiki/${of.article_id}`}
              className="rounded border border-sky-300 px-2 py-1 text-xs text-sky-700 hover:bg-sky-50"
            >
              View Article
            </Link>
            <RecompileButton articleId={of.article_id} />
          </div>
        </>
      )}

      <div className="mt-2 flex justify-end">
        <button
          onClick={() => dismiss.mutate()}
          disabled={dismiss.isPending}
          className="text-xs text-slate-400 hover:text-slate-600"
        >
          {dismiss.isPending ? "Dismissing..." : "Dismiss"}
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify the dev server builds without errors**

Run: `cd /Users/mg/mg-work/manav/work/ai-experiments/wikimind/apps/web && npx tsc --noEmit`

Expected: No type errors.

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/components/health/FindingCard.tsx
git commit -s -m "feat(web): add View Articles, Resolve, Recompile actions to FindingCard

Contradiction findings: View Article A/B links, Resolve dropdown
(source_a_wins/source_b_wins/both_valid/superseded with optional note),
Recompile button with optimistic loading state.

Orphan findings: View Article link, Recompile button."
```

### Task 5: Write ADR-016 and update ADR-009

**Files:**
- Create: `docs/adr/adr-016-article-recompilation.md`
- Modify: `docs/adr/adr-009-decoupled-ingest-compilation.md`

- [ ] **Step 1: Write ADR-016**

Create `docs/adr/adr-016-article-recompilation.md`:

```markdown
# ADR-016: Article recompilation as a first-class action

## Status

Accepted

## Context

The Health Dashboard surfaces contradictions and orphans, but the only action
was "Dismiss." The detect-surface loop lacked the "act" step. Users needed to
manually find and re-ingest articles when the linter flagged issues.

Recompilation is needed in two forms:

1. **Source recompile** — re-read the raw file from disk, call the source
   compiler again. Picks up prompt improvements, schema changes, or source
   file updates.
2. **Concept re-synthesis** — re-run the concept compiler for a concept page.
   Incorporates new sources, contradiction resolutions, or updated source
   articles.

## Decision

Add `POST /articles/{article_id}/recompile` as a first-class API endpoint.
Recompilation is always asynchronous via BackgroundCompiler (extending
ADR-009's decoupled pattern). The endpoint:

1. Infers mode from the article's `page_type` (source vs concept) unless
   explicitly overridden via `?mode=source|concept`.
2. Creates a `Job` record with `job_type=RECOMPILE_ARTICLE`.
3. Schedules the job via `BackgroundCompiler` (dev: asyncio.create_task,
   prod: ARQ).
4. Returns `{"status": "scheduled", "job_id": "..."}` immediately.
5. Emits `article.recompiled` WebSocket event on completion.

The frontend shows an optimistic "Recompiling..." spinner and auto-refreshes
when the WebSocket event fires.

## Alternatives Considered

**Synchronous recompile.** Source recompiles take 10-30s (LLM call). Blocking
the API would make the UI unresponsive, inconsistent with the async pattern
established by ADR-009.

**Separate endpoints per mode.** Two endpoints (`/recompile-source`,
`/recompile-concept`) would be redundant. A single endpoint with mode
inference is simpler and handles the common case (infer from page_type)
without requiring the caller to know the distinction.

## Consequences

- Users can trigger recompilation directly from the Health Dashboard
- The detect-surface-act loop is closed
- Same async pattern as ingest compilation (ADR-009)
- Frontend gets optimistic UI via WebSocket events
```

- [ ] **Step 2: Add revision note to ADR-009**

In `docs/adr/adr-009-decoupled-ingest-compilation.md`, add before the `## Consequences` section:

```markdown
## Revision (2026-04-15)

Recompilation is now a first-class action triggered via API, not just at
ingest time. See ADR-016 for details. The same `BackgroundCompiler` class
handles both initial compilation and recompilation jobs.
```

- [ ] **Step 3: Commit**

```bash
git add docs/adr/adr-016-article-recompilation.md docs/adr/adr-009-decoupled-ingest-compilation.md
git commit -s -m "docs: add ADR-016 (article recompilation), update ADR-009 with revision"
```

### Task 6: Run full pre-commit and push PR 1

- [ ] **Step 1: Run pre-commit checks**

```bash
cd /Users/mg/mg-work/manav/work/ai-experiments/wikimind && make pre-commit
```

Fix any issues found.

- [ ] **Step 2: Run mypy on changed files**

```bash
cd /Users/mg/mg-work/manav/work/ai-experiments/wikimind && python -m mypy src/wikimind/api/routes/wiki.py src/wikimind/jobs/worker.py --ignore-missing-imports
```

- [ ] **Step 3: Run full test suite**

```bash
cd /Users/mg/mg-work/manav/work/ai-experiments/wikimind && python -m pytest tests/ -x -q
```

- [ ] **Step 4: Push and create PR**

```bash
git push origin HEAD
gh pr create --title "feat(health): finding actions — view, resolve, recompile (#137)" --body "$(cat <<'EOF'
## Summary
- Add `POST /articles/{id}/recompile` endpoint (async via BackgroundCompiler)
- FindingCard: View Articles links, Resolve dropdown, Recompile button
- ADR-016: article recompilation as first-class action
- ADR-009: revision noting recompile extends the decoupled pattern

Closes #137
EOF
)"
```

---

## PR 2: Backlink Enforcer Integration

### Task 7: Add STRUCTURAL finding kind and StructuralFinding model

**Files:**
- Modify: `src/wikimind/models.py`

- [ ] **Step 1: Add STRUCTURAL to LintFindingKind**

In `src/wikimind/models.py`, update `LintFindingKind` (~line 490):

```python
class LintFindingKind(StrEnum):
    """Kind of lint finding — maps 1:1 to a detection function AND a table."""
    CONTRADICTION = "contradiction"
    ORPHAN = "orphan"
    STRUCTURAL = "structural"
```

- [ ] **Step 2: Add StructuralFinding model**

After `OrphanFinding` (~line 559), add:

```python
class StructuralFinding(_LintFindingBase, table=True):
    """A structural integrity violation detected by the backlink enforcer."""
    kind: LintFindingKind = Field(default=LintFindingKind.STRUCTURAL)
    article_id: str = Field(foreign_key="article.id", index=True)
    violation_type: str  # source_no_concepts | concept_insufficient_synthesizes | missing_inverse_link
    auto_repaired: bool = False
    detail: str = ""
```

- [ ] **Step 3: Add structural_count and checked_articles to LintReport**

In the `LintReport` model (~line 509), add:

```python
    structural_count: int = 0
    checked_articles: int | None = None
```

- [ ] **Step 4: Add structurals to LintReportDetail**

In `LintReportDetail` (~line 570), add:

```python
class LintReportDetail(BaseModel):
    """API response shape for a single report with all findings."""
    report: LintReport
    contradictions: list[ContradictionFinding]
    orphans: list[OrphanFinding]
    structurals: list[StructuralFinding] = []
```

- [ ] **Step 5: Commit**

```bash
git add src/wikimind/models.py
git commit -s -m "feat(models): add STRUCTURAL finding kind, StructuralFinding model, report fields"
```

### Task 8: Update backlink_enforcer to return structured results

**Files:**
- Modify: `src/wikimind/engine/backlink_enforcer.py`

- [ ] **Step 1: Add EnforcerResult dataclass**

At the top of `backlink_enforcer.py`, after imports, add:

```python
from dataclasses import dataclass, field


@dataclass
class EnforcerViolation:
    """A single structural violation found by the enforcer."""
    article_id: str
    article_title: str
    violation_type: str  # source_no_concepts | concept_insufficient_synthesizes | missing_inverse_link
    detail: str
    auto_repaired: bool = False


@dataclass
class EnforcerResult:
    """Result of running enforce_backlinks on a single article."""
    violations: list[EnforcerViolation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)  # backward compat
```

- [ ] **Step 2: Update enforce_backlinks to return EnforcerResult**

Update the function signature and body to populate `EnforcerResult` instead of just `list[str]`. Keep the `list[str]` backward-compatible via `result.warnings`:

```python
async def enforce_backlinks(article_id: str, session: AsyncSession) -> EnforcerResult:
    """Run structural integrity checks on an article's backlinks.

    Returns an EnforcerResult with structured violations and backward-compatible warnings.
    """
    result = EnforcerResult()

    # Load the article
    stmt = select(Article).where(Article.id == article_id)
    row = await session.execute(stmt)
    article = row.scalars().first()
    if article is None:
        result.warnings.append(f"Article {article_id} not found")
        return result

    # ---- Check 1: source pages need >= 1 concept ----
    if article.page_type == "source":
        concept_ids: list[str] = []
        if article.concept_ids:
            with contextlib.suppress(TypeError, ValueError):
                concept_ids = json.loads(article.concept_ids)
        if not concept_ids:
            msg = f"Source page '{article.title}' has no concepts in concept_ids"
            result.warnings.append(msg)
            result.violations.append(EnforcerViolation(
                article_id=article.id,
                article_title=article.title,
                violation_type="source_no_concepts",
                detail=msg,
            ))

    # ---- Check 2: concept pages need >= 2 synthesizes links ----
    if article.page_type == "concept":
        synth_result = await session.execute(
            select(Backlink).where(
                Backlink.source_article_id == article_id,
                Backlink.relation_type == RelationType.SYNTHESIZES,
            )
        )
        synth_count = len(list(synth_result.scalars().all()))
        if synth_count < 2:
            msg = f"Concept page '{article.title}' has {synth_count} synthesizes links (need >= 2)"
            result.warnings.append(msg)
            result.violations.append(EnforcerViolation(
                article_id=article.id,
                article_title=article.title,
                violation_type="concept_insufficient_synthesizes",
                detail=msg,
            ))

    # ---- Check 3: bidirectional enforcement for symmetric types ----
    out_result = await session.execute(select(Backlink).where(Backlink.source_article_id == article_id))
    outbound = list(out_result.scalars().all())

    in_result = await session.execute(select(Backlink).where(Backlink.target_article_id == article_id))
    inbound = list(in_result.scalars().all())

    all_links = outbound + inbound
    for bl in all_links:
        created = await ensure_bidirectional(bl, session)
        if created:
            msg = f"Auto-created inverse {bl.relation_type} link: {bl.target_article_id} → {bl.source_article_id}"
            result.warnings.append(msg)
            result.violations.append(EnforcerViolation(
                article_id=article.id,
                article_title=article.title,
                violation_type="missing_inverse_link",
                detail=msg,
                auto_repaired=True,
            ))

    return result
```

Note: orphan check removed from enforcer per spec (stays in `detect_orphans()`).

- [ ] **Step 3: Commit**

```bash
git add src/wikimind/engine/backlink_enforcer.py
git commit -s -m "refactor(enforcer): return structured EnforcerResult instead of list[str]"
```

### Task 9: Wire enforcer into linter runner as Phase 3

**Files:**
- Modify: `src/wikimind/engine/linter/runner.py`
- Modify: `src/wikimind/services/linter.py`
- Test: `tests/unit/test_enforcer_integration.py`

- [ ] **Step 1: Write failing test for enforcer integration**

Create `tests/unit/test_enforcer_integration.py`:

```python
"""Tests for backlink enforcer integration into lint pipeline."""

from __future__ import annotations

import json
import uuid

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.engine.linter.runner import run_lint
from wikimind.models import Article, LintReportStatus, PageType, StructuralFinding


@pytest.mark.asyncio
async def test_lint_run_includes_structural_findings(db_session: AsyncSession, mock_llm_router):
    """A full lint run should include structural findings from the enforcer."""
    # Source article with no concepts → structural violation
    article = Article(
        id=str(uuid.uuid4()),
        slug="no-concepts",
        title="No Concepts Article",
        file_path="/tmp/wiki/no-concepts.md",
        page_type=PageType.SOURCE,
        concept_ids="[]",
    )
    db_session.add(article)
    await db_session.commit()

    report = await run_lint(db_session)

    assert report.status == LintReportStatus.COMPLETE
    assert report.structural_count >= 1

    # Check structural findings persisted
    from sqlmodel import select
    result = await db_session.execute(
        select(StructuralFinding).where(StructuralFinding.report_id == report.id)
    )
    structurals = list(result.scalars().all())
    assert len(structurals) >= 1
    assert any(s.violation_type == "source_no_concepts" for s in structurals)


@pytest.mark.asyncio
async def test_lint_run_auto_repairs_missing_inverse(db_session: AsyncSession, mock_llm_router):
    """Enforcer auto-creates inverse links and reports them as auto_repaired."""
    from wikimind.models import Backlink, RelationType

    a1 = Article(id=str(uuid.uuid4()), slug="a1", title="A1", file_path="/tmp/a1.md", page_type=PageType.SOURCE, concept_ids='["test"]')
    a2 = Article(id=str(uuid.uuid4()), slug="a2", title="A2", file_path="/tmp/a2.md", page_type=PageType.SOURCE, concept_ids='["test"]')
    db_session.add_all([a1, a2])
    # Add one-directional contradicts link (missing inverse)
    bl = Backlink(source_article_id=a1.id, target_article_id=a2.id, relation_type=RelationType.CONTRADICTS, context="test")
    db_session.add(bl)
    await db_session.commit()

    report = await run_lint(db_session)

    from sqlmodel import select
    result = await db_session.execute(
        select(StructuralFinding).where(
            StructuralFinding.report_id == report.id,
            StructuralFinding.auto_repaired == True,
        )
    )
    repaired = list(result.scalars().all())
    assert len(repaired) >= 1
    assert repaired[0].violation_type == "missing_inverse_link"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/mg/mg-work/manav/work/ai-experiments/wikimind && python -m pytest tests/unit/test_enforcer_integration.py -v`

Expected: FAIL — `run_enforcer_checks` not called in runner, `StructuralFinding` not persisted.

- [ ] **Step 3: Add run_enforcer_checks to runner.py**

In `src/wikimind/engine/linter/runner.py`, add import at top:

```python
from wikimind.engine.backlink_enforcer import enforce_backlinks, EnforcerResult
from wikimind.models import StructuralFinding
```

Add the `run_enforcer_checks` function before `run_lint`:

```python
async def run_enforcer_checks(
    session: AsyncSession,
    report: LintReport,
) -> list[StructuralFinding]:
    """Phase 3: Run backlink enforcer on all articles, return structural findings."""
    import hashlib
    from wikimind.models import LintFindingKind, LintSeverity

    result = await session.execute(select(Article))
    articles = list(result.scalars().all())

    findings: list[StructuralFinding] = []
    checked = 0

    for article in articles:
        enforcer_result = await enforce_backlinks(article.id, session)
        for violation in enforcer_result.violations:
            content_hash = hashlib.sha256(
                f"{LintFindingKind.STRUCTURAL}|{violation.article_id}|{violation.violation_type}".encode()
            ).hexdigest()
            findings.append(StructuralFinding(
                report_id=report.id,
                severity=LintSeverity.WARN,
                description=violation.detail,
                content_hash=content_hash,
                article_id=violation.article_id,
                violation_type=violation.violation_type,
                auto_repaired=violation.auto_repaired,
                detail=violation.detail,
            ))
        checked += 1
        report.checked_articles = checked
        session.add(report)
        await session.flush()

    return findings
```

- [ ] **Step 4: Wire Phase 3 into run_lint**

In `run_lint()`, after the orphan detection and before dismiss suppression, add:

```python
        # Phase 3: structural enforcement
        structurals = await run_enforcer_checks(session, report)
```

Update `_apply_dismiss_suppression` to include structurals:

```python
        await _apply_dismiss_suppression(session, contradictions, orphans, structurals)
```

Update the `_apply_dismiss_suppression` signature to accept structurals:

```python
async def _apply_dismiss_suppression(
    session: AsyncSession,
    contradictions: list[ContradictionFinding],
    orphans: list[OrphanFinding],
    structurals: list[StructuralFinding] | None = None,
) -> None:
    all_findings: list[ContradictionFinding | OrphanFinding | StructuralFinding] = [
        *contradictions,
        *orphans,
        *(structurals or []),
    ]
```

Add persistence and counting for structurals in `run_lint`:

```python
        for sf in structurals:
            session.add(sf)

        active_structurals = [s for s in structurals if not s.dismissed]
        dismissed += len(structurals) - len(active_structurals)

        report.structural_count = len(active_structurals)
        report.total_findings = len(active_contradictions) + len(active_orphans) + len(active_structurals)
```

- [ ] **Step 5: Update linter service to include structurals in report queries**

In `src/wikimind/services/linter.py`, update `get_report()` and `get_latest()` to query and return `StructuralFinding` rows:

Add to imports:

```python
from wikimind.models import StructuralFinding
```

In the report query methods, after fetching contradictions and orphans, add:

```python
        structural_result = await session.execute(
            select(StructuralFinding)
            .where(StructuralFinding.report_id == report.id)
            .where(StructuralFinding.dismissed == include_dismissed if not include_dismissed else True)
        )
        structurals = list(structural_result.scalars().all())
```

And include in the return:

```python
        return LintReportDetail(report=report, contradictions=contradictions, orphans=orphans, structurals=structurals)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /Users/mg/mg-work/manav/work/ai-experiments/wikimind && python -m pytest tests/unit/test_enforcer_integration.py -v`

Expected: All tests PASS.

- [ ] **Step 7: Commit**

```bash
git add src/wikimind/engine/linter/runner.py src/wikimind/services/linter.py tests/unit/test_enforcer_integration.py
git commit -s -m "feat(linter): wire backlink enforcer into lint pipeline as Phase 3

Enforcer runs after contradictions and orphans. Auto-repairs missing
inverse links (auto_repaired=True). Structural findings persisted and
included in LintReportDetail."
```

### Task 10: Add frontend Structural tab and finding card

**Files:**
- Modify: `apps/web/src/api/lint.ts`
- Modify: `apps/web/src/components/health/FindingsByKindTabs.tsx`
- Modify: `apps/web/src/components/health/FindingCard.tsx`

- [ ] **Step 1: Add LintStructuralFinding type to lint.ts**

In `apps/web/src/api/lint.ts`, update `LintFindingKind`:

```typescript
export type LintFindingKind = "contradiction" | "orphan" | "structural";
```

Add the structural finding type:

```typescript
export interface LintStructuralFinding extends LintFindingBase {
  kind: "structural";
  article_id: string;
  violation_type: string;
  auto_repaired: boolean;
  detail: string;
}
```

Update `LintFinding` union:

```typescript
export type LintFinding =
  | LintContradictionFinding
  | LintOrphanFinding
  | LintStructuralFinding;
```

Update `LintReportDetail`:

```typescript
export interface LintReportDetail {
  report: LintReport;
  contradictions: LintContradictionFinding[];
  orphans: LintOrphanFinding[];
  structurals: LintStructuralFinding[];
}
```

- [ ] **Step 2: Add Structural tab to FindingsByKindTabs.tsx**

Update `FindingsByKindTabs.tsx` to include a third tab for structural findings:

```typescript
import { useState } from "react";
import type { LintReportDetail } from "../../api/lint";
import { FindingCard } from "./FindingCard";

type Tab = "contradictions" | "orphans" | "structurals";

export function FindingsByKindTabs({ detail }: { detail: LintReportDetail }) {
  const [active, setActive] = useState<Tab>("contradictions");

  const tabs: { key: Tab; label: string; count: number }[] = [
    { key: "contradictions", label: "Contradictions", count: detail.contradictions.length },
    { key: "orphans", label: "Orphans", count: detail.orphans.length },
    { key: "structurals", label: "Structural", count: (detail.structurals ?? []).length },
  ];

  const findings =
    active === "contradictions"
      ? detail.contradictions
      : active === "orphans"
        ? detail.orphans
        : (detail.structurals ?? []);

  return (
    <div>
      <div className="flex gap-1 border-b border-slate-200">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActive(tab.key)}
            className={`px-3 py-2 text-sm font-medium ${
              active === tab.key
                ? "border-b-2 border-brand-600 text-brand-700"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            {tab.label}
            {tab.count > 0 && (
              <span className="ml-1.5 rounded-full bg-slate-100 px-1.5 py-0.5 text-xs">
                {tab.count}
              </span>
            )}
          </button>
        ))}
      </div>

      <div className="mt-4 space-y-3">
        {findings.length === 0 ? (
          <p className="py-8 text-center text-sm text-slate-400">
            No {active} findings.
          </p>
        ) : (
          findings.map((f) => <FindingCard key={f.id} finding={f} />)
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Add structural finding rendering to FindingCard.tsx**

Add a `StructuralDetail` component and render it in FindingCard. Add this before the `FindingCard` export:

```typescript
function StructuralDetail({
  finding,
}: {
  finding: LintStructuralFinding;
}) {
  const typeColors: Record<string, string> = {
    source_no_concepts: "bg-red-100 text-red-700",
    concept_insufficient_synthesizes: "bg-amber-100 text-amber-700",
    missing_inverse_link: "bg-blue-100 text-blue-700",
  };
  const color = typeColors[finding.violation_type] ?? "bg-slate-100 text-slate-700";

  return (
    <div className="mt-2 space-y-1 text-sm">
      <div className="flex items-center gap-2">
        <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${color}`}>
          {finding.violation_type.replace(/_/g, " ")}
        </span>
        {finding.auto_repaired && (
          <span className="rounded bg-green-100 px-1.5 py-0.5 text-xs font-medium text-green-700">
            Auto-fixed
          </span>
        )}
      </div>
      <p className="text-slate-600">{finding.detail}</p>
    </div>
  );
}
```

In the `FindingCard` component body, add a third branch for structural findings:

```typescript
      {finding.kind === "structural" && (
        <>
          <StructuralDetail finding={finding as LintStructuralFinding} />
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Link
              to={`/wiki/${(finding as LintStructuralFinding).article_id}`}
              className="rounded border border-sky-300 px-2 py-1 text-xs text-sky-700 hover:bg-sky-50"
            >
              View Article
            </Link>
            {!(finding as LintStructuralFinding).auto_repaired && (
              <RecompileButton articleId={(finding as LintStructuralFinding).article_id} />
            )}
          </div>
        </>
      )}
```

Add `LintStructuralFinding` to the import from `../../api/lint`.

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd /Users/mg/mg-work/manav/work/ai-experiments/wikimind/apps/web && npx tsc --noEmit`

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/api/lint.ts apps/web/src/components/health/FindingsByKindTabs.tsx apps/web/src/components/health/FindingCard.tsx
git commit -s -m "feat(web): add Structural tab and finding cards for enforcer violations"
```

### Task 11: Write ADR-017 and update ADR-012

**Files:**
- Create: `docs/adr/adr-017-backlink-enforcer-lint-phase.md`
- Modify: `docs/adr/adr-012-knowledge-graph-architecture.md`

- [ ] **Step 1: Write ADR-017**

Create `docs/adr/adr-017-backlink-enforcer-lint-phase.md`:

```markdown
# ADR-017: Backlink enforcer as lint phase with auto-repair

## Status

Accepted

## Context

The backlink enforcer (`backlink_enforcer.py`) implements four structural
integrity checks on the knowledge graph: source pages must have concepts,
concept pages must have sufficient synthesizes links, orphan detection, and
bidirectional enforcement for symmetric relation types. The function was
complete and tested but not wired into any production code path.

Lint runs detected contradictions and orphans but missed structural invariant
violations. The enforcer's auto-repair capability (creating missing inverse
links for `contradicts` and `related_to` edges) needed a decision: should
lint runs have write side-effects?

## Decision

Wire the enforcer into the lint pipeline as Phase 3 (after contradictions
and orphans). The enforcer runs on every article during each lint pass.

When the enforcer finds auto-repairable issues (missing inverse links for
symmetric relation types), it creates the missing link AND reports it as a
`StructuralFinding` with `auto_repaired=True`. Lint runs have write
side-effects, but only when:

1. The fix is deterministic (symmetric link → inverse always exists)
2. The fix is safe (creating a link never deletes data)
3. The fix is the only correct action (there is no judgment call)

Violations requiring human judgment (source missing concepts, concept page
with insufficient synthesizes links) are reported without auto-repair.

Orphan detection stays in the existing `detect_orphans()` Phase 2. The
enforcer focuses on structural invariants that orphan detection does not
cover.

## Alternatives Considered

**Report only, never auto-fix.** Rejected. Missing inverse links for
symmetric types are always wrong and have exactly one correct fix. Reporting
without fixing creates busywork for the user with zero ambiguity.

**Auto-fix silently (no finding).** Rejected. Users should know when the
system modifies their knowledge graph. Transparency builds trust, and the
finding provides an audit trail.

**Run enforcer at compile time instead of lint time.** Considered but
insufficient. The enforcer catches issues that arise from multiple
compilations interacting (e.g., source A creates a contradicts link to B
but B's compilation didn't create the inverse). These cross-article issues
only emerge at lint time.

## Consequences

- Lint runs now include structural findings alongside contradictions and orphans
- Missing inverse links are auto-repaired during lint, maintaining graph consistency
- New `StructuralFinding` model and `STRUCTURAL` finding kind in the schema
- Health Dashboard gains a "Structural" tab showing enforcer violations
- Auto-repaired findings show "Auto-fixed" badge — informational, no action needed
```

- [ ] **Step 2: Update ADR-012 status**

In `docs/adr/adr-012-knowledge-graph-architecture.md`, change:

```markdown
## Status

Proposed
```

to:

```markdown
## Status

Accepted

_Revised 2026-04-15: Backlink enforcer (ADR-017) now auto-repairs structural
issues in the graph during lint runs._
```

- [ ] **Step 3: Commit**

```bash
git add docs/adr/adr-017-backlink-enforcer-lint-phase.md docs/adr/adr-012-knowledge-graph-architecture.md
git commit -s -m "docs: add ADR-017 (enforcer lint phase), update ADR-012 status to Accepted"
```

### Task 12: Run full pre-commit and push PR 2

- [ ] **Step 1: Run pre-commit and tests**

```bash
cd /Users/mg/mg-work/manav/work/ai-experiments/wikimind && make pre-commit && python -m pytest tests/ -x -q
```

- [ ] **Step 2: Push and create PR**

```bash
git push origin HEAD
gh pr create --title "feat(linter): backlink enforcer integration with auto-repair" --body "$(cat <<'EOF'
## Summary
- Wire `enforce_backlinks()` into lint pipeline as Phase 3
- New `STRUCTURAL` finding kind and `StructuralFinding` model
- Auto-repair missing inverse links, report as `auto_repaired=True`
- Frontend: Structural tab in Health Dashboard
- ADR-017: enforcer as lint phase with auto-repair
- ADR-012: updated status to Accepted

Depends on PR 1 (Finding Actions).
EOF
)"
```

---

## PR 3: Batch LLM Calls (#138)

### Task 13: Add batch config fields

**Files:**
- Modify: `src/wikimind/config.py`
- Modify: `.env.example`

- [ ] **Step 1: Add batch config to LinterConfig**

In `src/wikimind/config.py`, add to `LinterConfig` (~line 145):

```python
class LinterConfig(BaseModel):
    """Wiki linter configuration."""

    enable_orphan_detection: bool = True
    max_concepts_per_run: int = 25
    max_contradiction_pairs_per_concept: int = 10
    contradiction_llm_max_tokens: int = 1024
    contradiction_llm_temperature: float = 0.2
    enable_pair_cache: bool = True
    contradiction_batch_enabled: bool = True
    contradiction_batch_size: int = 4
```

- [ ] **Step 2: Add env vars to .env.example**

In `.env.example`, add after the existing linter section:

```bash
# Batch multiple article pairs into a single LLM call (reduces API calls ~4x)
# WIKIMIND_LINTER__CONTRADICTION_BATCH_ENABLED=true
# WIKIMIND_LINTER__CONTRADICTION_BATCH_SIZE=4
```

- [ ] **Step 3: Commit**

```bash
git add src/wikimind/config.py .env.example
git commit -s -m "feat(config): add contradiction batch size and enabled settings"
```

### Task 14: Add batch prompt templates

**Files:**
- Modify: `src/wikimind/engine/linter/prompts.py`

- [ ] **Step 1: Add batch templates**

In `src/wikimind/engine/linter/prompts.py`, add after the existing templates:

```python
CONTRADICTION_BATCH_SYSTEM = (
    "You are a wiki health auditor. Given multiple pairs of wiki articles "
    "about the same topic, identify contradictory assertions between each pair's "
    "key claims. Return strict JSON: an array of objects, one per pair_index."
)

CONTRADICTION_BATCH_USER = """Compare the following {pair_count} article pairs for contradictions.

{pair_sections}

For each pair, return an object with this shape:
{{
  "pair_index": <int>,
  "contradictions": [
    {{
      "description": "one-sentence summary of the contradiction",
      "article_a_claim": "the specific claim from A",
      "article_b_claim": "the specific claim from B",
      "confidence": "high" | "medium" | "low"
    }}
  ]
}}

Return a JSON array of exactly {pair_count} objects. If a pair has no contradictions, return an empty contradictions array for that pair.
Example: [{{"pair_index": 0, "contradictions": []}}, {{"pair_index": 1, "contradictions": [...]}}]"""


def format_batch_pair_section(index: int, title_a: str, claims_a: str, title_b: str, claims_b: str) -> str:
    """Format a single pair section for the batch prompt."""
    return f"""--- Pair {index} ---
Article A: "{title_a}"
Key claims:
{claims_a}

Article B: "{title_b}"
Key claims:
{claims_b}"""
```

- [ ] **Step 2: Commit**

```bash
git add src/wikimind/engine/linter/prompts.py
git commit -s -m "feat(linter): add batch prompt templates for contradiction detection"
```

### Task 15: Implement batching logic with retry/fallback

**Files:**
- Modify: `src/wikimind/engine/linter/contradictions.py`
- Test: `tests/unit/test_batch_contradictions.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_batch_contradictions.py`:

```python
"""Tests for batched contradiction detection."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wikimind.engine.linter.contradictions import _build_batch_prompt, _parse_batch_response, _run_batch
from wikimind.models import Article, PageType


def _make_article(title: str) -> Article:
    return Article(
        id=str(uuid.uuid4()),
        slug=title.lower().replace(" ", "-"),
        title=title,
        file_path=f"/tmp/{title}.md",
        page_type=PageType.SOURCE,
    )


def test_build_batch_prompt_formats_pairs():
    """Batch prompt includes all pair sections with correct indices."""
    pairs = [
        (_make_article("A1"), _make_article("A2"), ["claim1"], ["claim2"]),
        (_make_article("B1"), _make_article("B2"), ["claim3"], ["claim4"]),
    ]
    system, user = _build_batch_prompt(pairs)
    assert "2 article pairs" in user
    assert "Pair 0" in user
    assert "Pair 1" in user
    assert "claim1" in user
    assert "claim4" in user


def test_parse_batch_response_maps_by_index():
    """Batch response is correctly mapped to pairs by pair_index."""
    response_data = [
        {"pair_index": 0, "contradictions": [{"description": "d1", "article_a_claim": "a", "article_b_claim": "b", "confidence": "high"}]},
        {"pair_index": 1, "contradictions": []},
    ]
    result = _parse_batch_response(response_data, 2)
    assert len(result[0]) == 1
    assert len(result[1]) == 0


def test_parse_batch_response_handles_missing_index():
    """Missing pair_index in response returns empty for that pair."""
    response_data = [
        {"pair_index": 0, "contradictions": []},
        # pair_index 1 missing
    ]
    result = _parse_batch_response(response_data, 2)
    assert len(result[0]) == 0
    assert len(result[1]) == 0


@pytest.mark.asyncio
async def test_run_batch_retries_then_falls_back():
    """On batch failure, retry once, then fall back to per-pair calls."""
    mock_router = MagicMock()
    mock_router.complete = AsyncMock(side_effect=Exception("LLM error"))
    mock_router.parse_json_response = MagicMock()

    pairs_with_claims = [
        (_make_article("A"), _make_article("B"), ["c1"], ["c2"]),
    ]

    with patch("wikimind.engine.linter.contradictions._compare_article_pair", new_callable=AsyncMock) as mock_single:
        mock_single.return_value = []
        results = await _run_batch(pairs_with_claims, mock_router, MagicMock(), "report-id", None, None)

    # Should have tried batch twice (initial + retry), then fallen back to single
    assert mock_router.complete.await_count == 2
    assert mock_single.await_count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/mg/mg-work/manav/work/ai-experiments/wikimind && python -m pytest tests/unit/test_batch_contradictions.py -v`

Expected: FAIL — `_build_batch_prompt`, `_parse_batch_response`, `_run_batch` don't exist.

- [ ] **Step 3: Add batch helper functions to contradictions.py**

In `src/wikimind/engine/linter/contradictions.py`, add imports at top:

```python
from wikimind.engine.linter.prompts import (
    CONTRADICTION_BATCH_SYSTEM,
    CONTRADICTION_BATCH_USER,
    CONTRADICTION_SYSTEM_PROMPT,
    CONTRADICTION_USER_TEMPLATE,
    format_batch_pair_section,
)
```

Add batch helper functions before `detect_contradictions`:

```python
def _build_batch_prompt(
    pairs_with_claims: list[tuple[Article, Article, list[str], list[str]]],
) -> tuple[str, str]:
    """Build system and user prompts for a batch of article pairs."""
    _MAX_TITLE = 200
    _MAX_CLAIM = 500
    _MAX_CLAIMS_TEXT = 2000

    sections: list[str] = []
    for i, (article_a, article_b, claims_a, claims_b) in enumerate(pairs_with_claims):
        claims_a_text = "\n".join(f"- {c[:_MAX_CLAIM]}" for c in claims_a)[:_MAX_CLAIMS_TEXT]
        claims_b_text = "\n".join(f"- {c[:_MAX_CLAIM]}" for c in claims_b)[:_MAX_CLAIMS_TEXT]
        sections.append(format_batch_pair_section(
            i, article_a.title[:_MAX_TITLE], claims_a_text,
            article_b.title[:_MAX_TITLE], claims_b_text,
        ))

    user = CONTRADICTION_BATCH_USER.format(
        pair_count=len(pairs_with_claims),
        pair_sections="\n\n".join(sections),
    )
    return CONTRADICTION_BATCH_SYSTEM, user


def _parse_batch_response(
    response_data: list[dict],
    expected_count: int,
) -> dict[int, list[dict]]:
    """Parse batch LLM response into per-pair contradiction lists keyed by pair_index."""
    result: dict[int, list[dict]] = {i: [] for i in range(expected_count)}
    for item in response_data:
        idx = item.get("pair_index")
        if idx is not None and 0 <= idx < expected_count:
            result[idx] = item.get("contradictions", [])
    return result


async def _run_batch(
    pairs_with_claims: list[tuple[Article, Article, list[str], list[str]]],
    router: LLMRouter,
    settings: Settings,
    report_id: str,
    concept_id: str | None,
    session: AsyncSession | None,
) -> list[ContradictionFinding]:
    """Run a batch of pairs through the LLM. Retry once on failure, then fall back to per-pair."""
    cfg = settings.linter
    system_prompt, user_msg = _build_batch_prompt(pairs_with_claims)

    request = CompletionRequest(
        system=system_prompt,
        messages=[{"role": "user", "content": user_msg}],
        max_tokens=cfg.contradiction_llm_max_tokens * len(pairs_with_claims),
        temperature=cfg.contradiction_llm_temperature,
        response_format="json",
        task_type=TaskType.LINT,
    )

    for attempt in range(2):  # initial + 1 retry
        try:
            response = await router.complete(request, session=None)
            data = router.parse_json_response(response)
            if isinstance(data, dict):
                data = data.get("results", data.get("pairs", []))
            if not isinstance(data, list):
                raise ValueError(f"Expected list, got {type(data)}")
            break
        except Exception:
            log.warning(
                "Batch LLM call failed",
                attempt=attempt + 1,
                pairs=len(pairs_with_claims),
                exc_info=True,
            )
            if attempt == 1:
                # Fall back to individual per-pair calls
                log.info("Falling back to per-pair contradiction checks", pairs=len(pairs_with_claims))
                all_findings: list[ContradictionFinding] = []
                for article_a, article_b, _, _ in pairs_with_claims:
                    findings = await _compare_article_pair(
                        article_a, article_b, concept_id, router, settings, report_id, session
                    )
                    all_findings.extend(findings)
                return all_findings
    else:
        return []

    per_pair = _parse_batch_response(data, len(pairs_with_claims))
    findings: list[ContradictionFinding] = []

    for i, (article_a, article_b, _, _) in enumerate(pairs_with_claims):
        for c in per_pair.get(i, []):
            claim_a = c.get("article_a_claim", "")
            claim_b = c.get("article_b_claim", "")
            findings.append(ContradictionFinding(
                report_id=report_id,
                severity=LintSeverity.WARN,
                description=c.get("description", "Contradiction detected"),
                content_hash=_content_hash(article_a.id, article_b.id),
                article_a_id=article_a.id,
                article_b_id=article_b.id,
                article_a_claim=claim_a,
                article_b_claim=claim_b,
                llm_confidence=c.get("confidence", "medium"),
                shared_concept_id=concept_id,
            ))
            if session is not None:
                ctx = f"{claim_a} vs {claim_b}"
                await _create_contradiction_backlink(session, article_a.id, article_b.id, ctx)

    return findings
```

- [ ] **Step 4: Update detect_contradictions to use batching**

In the main loop of `detect_contradictions`, replace the per-pair processing with batch-aware logic. After collecting uncached pairs, group them into batches:

```python
            # Collect uncached pairs with their claims
            uncached_pairs: list[tuple[Article, Article, list[str], list[str]]] = []

            for article_a, article_b in pairs:
                if cfg.enable_pair_cache:
                    cached = await _check_pair_cache(session, article_a, article_b)
                    if cached is not None:
                        # ... existing cache-hit logic (unchanged) ...
                        checked += 1
                        report.checked_pairs = checked
                        session.add(report)
                        await session.flush()
                        continue

                claims_a = _extract_claims(article_a)
                claims_b = _extract_claims(article_b)
                if claims_a and claims_b:
                    uncached_pairs.append((article_a, article_b, claims_a, claims_b))
                else:
                    checked += 1
                    report.checked_pairs = checked
                    session.add(report)
                    await session.flush()

            # Process uncached pairs (batched or individual)
            if cfg.contradiction_batch_enabled and len(uncached_pairs) > 1:
                batch_size = cfg.contradiction_batch_size
                for batch_start in range(0, len(uncached_pairs), batch_size):
                    batch = uncached_pairs[batch_start:batch_start + batch_size]
                    batch_findings = await _run_batch(batch, router, settings, report.id, concept_id, session)
                    findings.extend(batch_findings)

                    # Save per-pair cache and update progress
                    for article_a, article_b, _, _ in batch:
                        if cfg.enable_pair_cache:
                            pair_findings = [f for f in batch_findings
                                           if f.article_a_id == article_a.id and f.article_b_id == article_b.id]
                            cache_data = [{"description": f.description, "article_a_claim": f.article_a_claim,
                                         "article_b_claim": f.article_b_claim, "confidence": f.llm_confidence}
                                         for f in pair_findings]
                            await _save_pair_cache(session, article_a, article_b, cache_data)
                        checked += 1
                        report.checked_pairs = checked
                        session.add(report)
                        await session.flush()
            else:
                # Fall back to per-pair for single pairs or when batching disabled
                for article_a, article_b, _, _ in uncached_pairs:
                    new_findings = await _compare_article_pair(
                        article_a, article_b, concept_id, router, settings, report.id, session
                    )
                    findings.extend(new_findings)
                    if cfg.enable_pair_cache:
                        cache_data = [{"description": f.description, "article_a_claim": f.article_a_claim,
                                     "article_b_claim": f.article_b_claim, "confidence": f.llm_confidence}
                                     for f in new_findings]
                        await _save_pair_cache(session, article_a, article_b, cache_data)
                    checked += 1
                    report.checked_pairs = checked
                    session.add(report)
                    await session.flush()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/mg/mg-work/manav/work/ai-experiments/wikimind && python -m pytest tests/unit/test_batch_contradictions.py -v`

Expected: All 4 tests PASS.

- [ ] **Step 6: Run existing linter tests to verify no regression**

Run: `cd /Users/mg/mg-work/manav/work/ai-experiments/wikimind && python -m pytest tests/unit/test_linter.py -v`

Expected: All existing tests PASS.

- [ ] **Step 7: Commit**

```bash
git add src/wikimind/engine/linter/contradictions.py tests/unit/test_batch_contradictions.py
git commit -s -m "feat(linter): batch LLM calls for contradiction detection (#138)

Groups uncached article pairs into batches of N (default 4) per LLM call.
Retry once on failure, then fall back to individual per-pair calls.
Per-pair cache granularity preserved. ~4x fewer API calls on cold runs."
```

### Task 16: Write ADR-018

**Files:**
- Create: `docs/adr/adr-018-batched-contradiction-detection.md`

- [ ] **Step 1: Write ADR-018**

Create `docs/adr/adr-018-batched-contradiction-detection.md`:

```markdown
# ADR-018: Batched LLM calls for contradiction detection

## Status

Accepted

## Context

The contradiction linter makes one LLM call per article pair, iterating
sequentially. For a concept with 10 pairs, that is 10 API calls at ~3-7s
each. A real run with 23 articles across 4 concepts took ~90s and ~$0.09.

## Decision

Group uncached article pairs into batches of N (configurable via
`WIKIMIND_LINTER__CONTRADICTION_BATCH_SIZE`, default 4) per LLM call. The
batch prompt includes all pairs with explicit `pair_index` identifiers. The
LLM returns a JSON array with one entry per pair.

**Failure handling:** Retry the batch once on failure. On second failure,
fall back to individual per-pair calls for that batch. This guarantees
progress even when the batch prompt exceeds the LLM's ability to parse
correctly.

**Cache interaction:** Per-pair cache granularity is preserved. Before
batching, cached pairs are filtered out. After a successful batch response,
results are saved per-pair so future runs with different batch compositions
still get cache hits.

**Progress tracking:** `report.checked_pairs` is incremented per-pair within
each batch, keeping the frontend progress bar smooth.

## Alternatives Considered

**Fixed batch size with no fallback.** Rejected. LLMs sometimes fail to
parse complex multi-pair prompts. Without fallback, failed batches would
silently skip pairs.

**Batch-level cache (cache the entire batch result).** Rejected. Batch
composition changes when articles are added or modified. Per-pair cache is
resilient to composition changes.

**Concurrent batches across concepts via asyncio.gather.** Deferred. Would
add parallelism across concepts on top of batching within concepts. Can be
added later without changing the batch design.

## Consequences

- ~4x fewer LLM API calls for cold contradiction runs
- ~3x faster wall time for large concept buckets
- Per-pair cache continues to work unchanged
- Batch size is configurable for tuning cost/speed tradeoff
- Fallback to per-pair ensures no silent coverage loss
```

- [ ] **Step 2: Commit**

```bash
git add docs/adr/adr-018-batched-contradiction-detection.md
git commit -s -m "docs: add ADR-018 (batched contradiction detection)"
```

### Task 17: Run full pre-commit and push PR 3

- [ ] **Step 1: Run pre-commit and tests**

```bash
cd /Users/mg/mg-work/manav/work/ai-experiments/wikimind && make pre-commit && python -m pytest tests/ -x -q
```

- [ ] **Step 2: Push and create PR**

```bash
git push origin HEAD
gh pr create --title "feat(linter): batch LLM calls for contradiction detection (#138)" --body "$(cat <<'EOF'
## Summary
- Batch uncached article pairs into groups of N (default 4) per LLM call
- Retry once on failure, fall back to individual per-pair calls
- Per-pair cache granularity preserved
- Config: `WIKIMIND_LINTER__CONTRADICTION_BATCH_SIZE`, `WIKIMIND_LINTER__CONTRADICTION_BATCH_ENABLED`
- ADR-018: batched contradiction detection design

Closes #138
EOF
)"
```

---

## Verification Checklist

After all three PRs are merged:

- [ ] Ingest 2+ sources for the same concept
- [ ] Run lint from Health Dashboard
- [ ] Verify contradiction findings show View Articles, Resolve, and Recompile buttons
- [ ] Click "View Article A" — navigates to the article page
- [ ] Click "Resolve" → "Source A wins" — finding shows "Resolved" badge
- [ ] Click "Recompile" on an orphan — shows "Recompiling..." then refreshes
- [ ] Verify Structural tab appears with enforcer findings
- [ ] Verify auto-repaired findings show "Auto-fixed" badge
- [ ] Verify batch LLM calls are logged (check `checked_pairs` progress during lint)
- [ ] Run `make pre-commit` — all checks pass
- [ ] Run `python -m pytest tests/ -x` — all tests pass
