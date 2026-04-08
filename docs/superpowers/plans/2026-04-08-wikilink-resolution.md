# Wikilink Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve `[[wikilinks]]` at compile time (not render time), produce real `Backlink` rows in the database, and close issues #95 and #96 in a single PR. Sets the table for Epic 3 (knowledge graph view) by populating the `Backlink` table for the first time.

**Architecture:** One PR. Adds a deterministic title-normalization module, a pure resolution helper, a compiler post-processing step, a superset article lookup (ID-or-slug), and a frontend simplification that deletes the local slugifier. The spec lives at `docs/superpowers/specs/2026-04-08-wikilink-resolution-design.md` — read it before starting.

**Tech Stack:** FastAPI + SQLModel + SQLite (backend); React 18 + Vite + TypeScript + Tailwind + react-markdown (frontend); pytest with hermetic fixtures (backend tests).

---

## Spec coverage

This plan implements the full spec except the backfill step, which is explicitly deferred to a user decision (see Task 8 — STOP HERE).

| Decision | Source |
|---|---|
| Two-stage deterministic resolution (exact → normalized), no fuzzy | Spec § Resolution algorithm |
| `Backlink` model reused as-is (composite PK already exists) | Spec § Current state |
| `Backlink` rows created at compile time, not render time | Spec § Compiler post-processing pipeline |
| Markdown uses `[text](/wiki/<id>)` for resolved, `[[text]]` for unresolved (Option B) | Spec § Markdown generation |
| Article lookup accepts ID or slug (ID first, slug fallback) | Spec § Backend: article lookup accepts ID or slug |
| Frontend deletes its local slugifier — single normalizer in one module | Spec § The single normalizer — drift prevention |
| Unresolved candidates NOT persisted — the markdown body is the record (Option C) | Spec § Storage — where do resolution results live? |
| Prompt contract is UNCHANGED — only post-processing of LLM output changes | Spec § Goals |
| Backfill strategy is a user decision — plan STOPS before backfill work | Spec § Backfill strategy, Task 8 below |

## Conventions for the implementing engineer

Read `CLAUDE.md` at the repo root before making any change. Key rules:

- **Conventional commits.** Use `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`. One logical change per commit.
- **`make verify` must be green** before any push. Runs ruff lint + format + mypy + pytest with an 80% coverage floor.
- **No magic numbers.** Tunable values go in `Settings`, not as inline constants. (None expected for this work — the algorithm is parameter-free.)
- **No silent failures.** Errors raise; fallback paths log and re-raise. Don't add try/except just to swallow.
- **Hermetic tests.** Mock the LLM router boundary, never make real API calls. Use existing fixtures in `tests/conftest.py`.
- **Doc-sync.** If you change a route, the pre-commit hook re-generates `docs/openapi.yaml` for you. The wiki route's path parameter is renamed in Task 5 — OpenAPI will reflect that automatically.
- **TDD.** Write the failing test → run it to confirm it fails → write minimal implementation → run it to confirm it passes → commit. The steps below are written this way; follow them.
- **Don't expand scope.** Anything not in this plan or the spec is out of scope. If you find yourself wanting to "also fix" something, file an issue instead.

---

# File Structure

## Files to create

| Path | Responsibility |
|---|---|
| `src/wikimind/engine/title_normalizer.py` | Single-source-of-truth `normalize_title(s: str) -> str`. The only title normalizer in the entire codebase. |
| `src/wikimind/engine/wikilink_resolver.py` | `ResolvedBacklink` dataclass and `resolve_backlink_candidates(candidates, session, exclude_article_id)` pure-function helper. |
| `tests/unit/test_title_normalizer.py` | Edge-case tests for the normalizer (unicode, underscores, apostrophes, punctuation, long titles). |
| `tests/unit/test_wikilink_resolver.py` | Unit tests for the two-stage resolution algorithm. |
| `tests/integration/test_wikilink_resolution_integration.py` | End-to-end test: compile an article referencing an existing one → verify `Backlink` row → verify rendered markdown has a real link → GET by ID returns the article. |

## Files to modify

| Path | What changes |
|---|---|
| `src/wikimind/engine/compiler.py` | Import the resolver. Split `_write_article_file` so the "Related" section accepts resolved + unresolved lists. Update `_create_article` and `_replace_article_in_place` to call `resolve_backlink_candidates` and emit `Backlink` rows. |
| `src/wikimind/services/wiki.py` | `get_article(slug)` → `get_article(id_or_slug)`: try ID first, fall back to slug. Rename the parameter; preserve behaviour for existing slug callers. |
| `src/wikimind/api/routes/wiki.py` | Rename the path parameter on `GET /wiki/articles/{slug}` → `/wiki/articles/{id_or_slug}`. |
| `apps/web/src/components/wiki/ArticleReader.tsx` | Delete the local `slugify()` helper. Delete the `data-wikilink` hack. Add a preprocessor that converts remaining `[[...]]` (unresolved) to a dimmed span. Simplify the anchor renderer to use `<Link>` for internal `/wiki/...` hrefs and `<a target="_blank">` for external. |
| `apps/web/src/index.css` (or equivalent Tailwind config) | Add a `.wikilink-unresolved` style rule — dim color, dotted underline, `cursor: help`. |
| `tests/unit/test_compiler.py` (if it exists; if not, extend `tests/unit/test_misc.py`) | Add tests for the compiler's new resolution-aware save path. |

---

# Tasks

**Branch:** `claude/wikilink-resolution` (or whatever the implementing agent chooses — single PR, single branch)

**Definition of done:** Tasks 1–7 complete, `make verify` green, integration test passing, commit history tells the TDD story. Task 8 is a STOP marker — do NOT implement the backfill step; file an issue instead.

## Task 1: Verify the Backlink model is sufficient

**Files:**
- Read-only: `src/wikimind/models.py`

The spec claims `Backlink` already exists with `source_article_id`, `target_article_id`, and optional `context`. Verify before touching anything.

- [ ] **Step 1: Confirm the Backlink model**

Read `src/wikimind/models.py` around line 157. Confirm the shape matches the spec:

```python
class Backlink(SQLModel, table=True):
    """Directed link between two wiki articles."""

    source_article_id: str = Field(foreign_key="article.id", primary_key=True)
    target_article_id: str = Field(foreign_key="article.id", primary_key=True)
    context: str | None = None  # Sentence where link appears
```

**If the model matches:** this task is complete, no code change. Proceed to Task 2.

**If the model is different or missing:** stop and report. The plan assumes the composite PK `(source_article_id, target_article_id)`. If the model has a surrogate `id` column instead, tasks 3 and 4 need to be adjusted (the resolver returns target IDs; the save path needs a different duplicate-handling strategy).

- [ ] **Step 2: Confirm no existing code writes Backlink rows**

```bash
grep -rn "Backlink(" /Users/mg/mg-work/manav/work/ai-experiments/wikimind/src/wikimind/
```

Expected: references appear in `models.py` and `services/wiki.py` (for reading), but NO construction calls like `Backlink(source_article_id=...)`. If there is a construction call, add a note to the commit message — the plan assumes a green field.

- [ ] **Step 3: No commit**

This task is verification only. Nothing to commit.

## Task 2: Add the title normalizer

**Files:**
- Create: `src/wikimind/engine/title_normalizer.py`
- Create: `tests/unit/test_title_normalizer.py`

The single normalizer is the entire #96 fix. It must be pure (no I/O, no state), deterministic, and small.

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_title_normalizer.py`:

```python
"""Tests for the single shared title normalizer."""

import pytest

from wikimind.engine.title_normalizer import normalize_title


@pytest.mark.parametrize(
    "raw, expected",
    [
        # Baseline
        ("Machine Learning", "machine-learning"),
        ("machine learning", "machine-learning"),
        ("MACHINE LEARNING", "machine-learning"),
        # Whitespace variants collapse
        ("Machine   Learning", "machine-learning"),
        ("  Machine Learning  ", "machine-learning"),
        ("Machine\tLearning", "machine-learning"),
        ("Machine\nLearning", "machine-learning"),
        # Underscores become hyphens
        ("machine_learning", "machine-learning"),
        ("Machine_Learning_Ops", "machine-learning-ops"),
        # Punctuation stripped
        ("Machine Learning!", "machine-learning"),
        ("Machine Learning?", "machine-learning"),
        ("Machine Learning.", "machine-learning"),
        ("Machine, Learning", "machine-learning"),
        # Apostrophes stripped, not preserved as hyphens
        ("Karpathy's wiki pattern", "karpathys-wiki-pattern"),
        ("it's", "its"),
        # Unicode NFKD + ASCII strip
        ("Café", "cafe"),
        ("naïve", "naive"),
        ("Zürich", "zurich"),
        # Hyphens preserved
        ("state-of-the-art", "state-of-the-art"),
        # Multiple consecutive separators collapse
        ("foo   ---   bar", "foo-bar"),
        ("foo___bar", "foo-bar"),
        # Long titles are not truncated (the resolver does not care about length)
        ("a" * 200, "a" * 200),
        # Numbers preserved
        ("GPT-4o", "gpt-4o"),
        ("Article 1", "article-1"),
        # Empty and whitespace-only
        ("", ""),
        ("   ", ""),
        # Symbols dropped
        ("C++", "c"),
        ("C#", "c"),
    ],
)
def test_normalize_title(raw: str, expected: str) -> None:
    assert normalize_title(raw) == expected


def test_normalize_title_is_idempotent() -> None:
    """Normalizing an already-normalized string is a no-op."""
    once = normalize_title("Machine Learning Operations")
    twice = normalize_title(once)
    assert once == twice


def test_normalize_title_deterministic() -> None:
    """Two calls with the same input produce identical output."""
    a = normalize_title("Karpathy's LLM Wiki Pattern")
    b = normalize_title("Karpathy's LLM Wiki Pattern")
    assert a == b
```

- [ ] **Step 2: Run the tests, verify they fail**

```bash
.venv/bin/pytest tests/unit/test_title_normalizer.py -v
```

Expected: FAIL with `ModuleNotFoundError: wikimind.engine.title_normalizer`.

- [ ] **Step 3: Implement the normalizer**

Create `src/wikimind/engine/title_normalizer.py`:

```python
"""Single source of truth for title normalization.

This is the only title normalizer in the entire WikiMind codebase. Any
code that needs to compare article titles — the wikilink resolver, the
knowledge graph builder, future search features — MUST import
``normalize_title`` from this module. Do NOT add a second normalizer
anywhere else. Doing so will reintroduce the slug-divergence bug tracked
in issue #96.

The algorithm is intentionally simple:
    1. Unicode NFKD decomposition + ASCII strip (so "Café" → "Cafe").
    2. Lowercase.
    3. Replace every run of non-alphanumeric characters (except hyphens)
       with a single hyphen. Underscores count as non-alphanumeric.
    4. Strip leading and trailing hyphens.
    5. Collapse consecutive hyphens to one.

The output is suitable for exact-match comparison: two strings produce
the same output iff they normalize to the same canonical form.
"""

from __future__ import annotations

import re
import unicodedata

_NON_ALNUM_HYPHEN = re.compile(r"[^a-z0-9-]+")
_MULTI_HYPHEN = re.compile(r"-{2,}")


def normalize_title(s: str) -> str:
    """Canonicalize a title for wikilink resolution.

    Args:
        s: Raw title string. May be empty, contain unicode, contain
           punctuation, contain mixed whitespace.

    Returns:
        A lowercase ASCII string containing only ``[a-z0-9-]``. Empty
        input yields an empty string.
    """
    # 1. Unicode → ASCII
    ascii_form = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    # 2. Lowercase
    lower = ascii_form.lower()
    # 3. Replace runs of non-alnum-non-hyphen with a single hyphen
    hyphenated = _NON_ALNUM_HYPHEN.sub("-", lower)
    # 4. Strip leading/trailing hyphens
    stripped = hyphenated.strip("-")
    # 5. Collapse consecutive hyphens
    return _MULTI_HYPHEN.sub("-", stripped)
```

- [ ] **Step 4: Run the tests, verify they pass**

```bash
.venv/bin/pytest tests/unit/test_title_normalizer.py -v
```

Expected: all tests PASS. If a specific parametrize case fails, adjust the regex — the table above is the contract, not the implementation.

- [ ] **Step 5: Lint + typecheck**

```bash
.venv/bin/ruff check src/wikimind/engine/title_normalizer.py tests/unit/test_title_normalizer.py
.venv/bin/mypy src/wikimind/engine/title_normalizer.py
```

Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/wikimind/engine/title_normalizer.py tests/unit/test_title_normalizer.py
git commit -m "feat(engine): add single-source-of-truth title normalizer (#96)"
```

## Task 3: Add the wikilink resolver

**Files:**
- Create: `src/wikimind/engine/wikilink_resolver.py`
- Create: `tests/unit/test_wikilink_resolver.py`

The resolver is a pure function (given the DB session): `list[str] → (list[ResolvedBacklink], list[str])`. It runs the two-stage algorithm and returns resolved + unresolved candidate lists.

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_wikilink_resolver.py`:

```python
"""Tests for the two-stage wikilink resolution algorithm."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.engine.wikilink_resolver import (
    ResolvedBacklink,
    resolve_backlink_candidates,
)
from wikimind.models import Article, ConfidenceLevel


async def _make_article(
    session: AsyncSession,
    title: str,
    slug: str | None = None,
    created_at: datetime | None = None,
) -> Article:
    article = Article(
        id=str(uuid.uuid4()),
        slug=slug or title.lower().replace(" ", "-"),
        title=title,
        file_path=f"/tmp/{slug or title}.md",
        confidence=ConfidenceLevel.SOURCED,
        created_at=created_at or datetime.utcnow(),
    )
    session.add(article)
    await session.commit()
    await session.refresh(article)
    return article


@pytest.mark.asyncio
async def test_exact_match_resolves(async_session: AsyncSession) -> None:
    existing = await _make_article(async_session, "Machine Learning")
    resolved, unresolved = await resolve_backlink_candidates(
        ["Machine Learning"], async_session
    )
    assert len(resolved) == 1
    assert resolved[0].target_id == existing.id
    assert resolved[0].candidate_text == "Machine Learning"
    assert resolved[0].target_title == "Machine Learning"
    assert unresolved == []


@pytest.mark.asyncio
async def test_case_insensitive_exact_match_resolves(async_session: AsyncSession) -> None:
    existing = await _make_article(async_session, "Machine Learning")
    resolved, unresolved = await resolve_backlink_candidates(
        ["machine learning"], async_session
    )
    assert len(resolved) == 1
    assert resolved[0].target_id == existing.id
    assert unresolved == []


@pytest.mark.asyncio
async def test_normalized_match_resolves(async_session: AsyncSession) -> None:
    """Stage 2: candidate differs from title by punctuation only."""
    existing = await _make_article(async_session, "Karpathy's Wiki Pattern")
    resolved, unresolved = await resolve_backlink_candidates(
        ["Karpathys Wiki Pattern"], async_session
    )
    assert len(resolved) == 1
    assert resolved[0].target_id == existing.id
    assert unresolved == []


@pytest.mark.asyncio
async def test_underscore_to_space_resolves_via_normalizer(async_session: AsyncSession) -> None:
    existing = await _make_article(async_session, "Machine Learning Ops")
    resolved, unresolved = await resolve_backlink_candidates(
        ["machine_learning_ops"], async_session
    )
    assert len(resolved) == 1
    assert resolved[0].target_id == existing.id


@pytest.mark.asyncio
async def test_no_match_stays_unresolved(async_session: AsyncSession) -> None:
    await _make_article(async_session, "Machine Learning")
    resolved, unresolved = await resolve_backlink_candidates(
        ["Quantum Computing"], async_session
    )
    assert resolved == []
    assert unresolved == ["Quantum Computing"]


@pytest.mark.asyncio
async def test_similar_but_distinct_does_not_match(async_session: AsyncSession) -> None:
    """"Machine Learning Ops" must NOT match "Machine Learning" — no fuzzy."""
    await _make_article(async_session, "Machine Learning")
    resolved, unresolved = await resolve_backlink_candidates(
        ["Machine Learning Ops"], async_session
    )
    assert resolved == []
    assert unresolved == ["Machine Learning Ops"]


@pytest.mark.asyncio
async def test_mixed_resolved_and_unresolved(async_session: AsyncSession) -> None:
    await _make_article(async_session, "React")
    await _make_article(async_session, "TypeScript")
    resolved, unresolved = await resolve_backlink_candidates(
        ["React", "Redux", "TypeScript", "Zustand"], async_session
    )
    assert len(resolved) == 2
    assert sorted(unresolved) == ["Redux", "Zustand"]
    resolved_titles = sorted(r.target_title for r in resolved)
    assert resolved_titles == ["React", "TypeScript"]


@pytest.mark.asyncio
async def test_duplicate_candidates_deduped_in_resolved(async_session: AsyncSession) -> None:
    """Two candidates resolving to the same target produce ONE ResolvedBacklink."""
    await _make_article(async_session, "React")
    resolved, unresolved = await resolve_backlink_candidates(
        ["React", "react"], async_session
    )
    assert len(resolved) == 1
    assert unresolved == []


@pytest.mark.asyncio
async def test_ambiguous_normalized_match_picks_earliest(async_session: AsyncSession) -> None:
    """Two articles with the same normalized form → pick the earliest created_at."""
    older = await _make_article(
        async_session, "Machine Learning", created_at=datetime(2026, 1, 1)
    )
    await _make_article(
        async_session, "machine-learning", created_at=datetime(2026, 2, 1)
    )
    resolved, _ = await resolve_backlink_candidates(["Machine Learning"], async_session)
    assert len(resolved) == 1
    assert resolved[0].target_id == older.id


@pytest.mark.asyncio
async def test_exclude_self_reference(async_session: AsyncSession) -> None:
    """A candidate that matches the article currently being compiled is excluded."""
    self_article = await _make_article(async_session, "Self Article")
    other = await _make_article(async_session, "Other Article")
    resolved, unresolved = await resolve_backlink_candidates(
        ["Self Article", "Other Article"],
        async_session,
        exclude_article_id=self_article.id,
    )
    assert len(resolved) == 1
    assert resolved[0].target_id == other.id
    assert unresolved == ["Self Article"]


@pytest.mark.asyncio
async def test_empty_candidate_list(async_session: AsyncSession) -> None:
    resolved, unresolved = await resolve_backlink_candidates([], async_session)
    assert resolved == []
    assert unresolved == []


@pytest.mark.asyncio
async def test_empty_string_candidate_is_unresolved(async_session: AsyncSession) -> None:
    resolved, unresolved = await resolve_backlink_candidates(["", "   "], async_session)
    assert resolved == []
    # Empty strings are dropped, not passed through as unresolved
    assert unresolved == []
```

The tests assume a fixture `async_session` exists in `tests/conftest.py`. If not, check the existing test file in `tests/unit/test_misc.py` or similar to see what the project's DB fixture is named and adjust accordingly.

- [ ] **Step 2: Run the tests, verify they fail**

```bash
.venv/bin/pytest tests/unit/test_wikilink_resolver.py -v
```

Expected: FAIL with `ModuleNotFoundError` (module doesn't exist yet).

- [ ] **Step 3: Implement the resolver**

Create `src/wikimind/engine/wikilink_resolver.py`:

```python
"""Resolve LLM-suggested wikilink candidates against the Article table.

Given a list of candidate title strings (as produced by the compiler
LLM in ``CompilationResult.backlink_suggestions``) and an async DB
session, return two lists:

    - ``resolved``: :class:`ResolvedBacklink` rows, each pointing at a
      real :class:`Article` by ID.
    - ``unresolved``: candidate strings that matched no article.

The algorithm is deterministic and has exactly two stages:

    1. Exact case-insensitive match against ``Article.title``.
    2. Normalized match using :func:`normalize_title` on both sides.

There is NO fuzzy matching. See the design spec for rationale
(docs/superpowers/specs/2026-04-08-wikilink-resolution-design.md).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.engine.title_normalizer import normalize_title
from wikimind.models import Article


@dataclass(frozen=True)
class ResolvedBacklink:
    """A successfully resolved wikilink candidate.

    Attributes:
        candidate_text: The raw string the LLM produced. Preserved
            verbatim so the rendered markdown can show the LLM's
            wording if it differs from the canonical title.
        target_id: The :class:`Article.id` this candidate resolved to.
        target_title: The canonical :class:`Article.title` of the
            resolved article. Used by the compiler's markdown writer.
    """

    candidate_text: str
    target_id: str
    target_title: str


async def resolve_backlink_candidates(
    candidates: list[str],
    session: AsyncSession,
    exclude_article_id: str | None = None,
) -> tuple[list[ResolvedBacklink], list[str]]:
    """Resolve wikilink candidates against the Article table.

    Args:
        candidates: Raw title strings from
            :attr:`CompilationResult.backlink_suggestions`. Empty
            strings and whitespace-only strings are silently dropped.
        session: Async DB session.
        exclude_article_id: If set, any candidate that would resolve
            to this article ID is treated as unresolved. Used by the
            compiler to prevent self-references when an article is
            suggested to link to itself.

    Returns:
        A tuple ``(resolved, unresolved)``. Resolved contains one
        :class:`ResolvedBacklink` per unique target article (so two
        candidates pointing at the same article produce one row).
        Unresolved is the list of candidate strings that matched no
        article, in input order.
    """
    # Drop empty / whitespace-only candidates up front.
    cleaned = [c.strip() for c in candidates if c and c.strip()]
    if not cleaned:
        return [], []

    # Load every Article once. For a single-user personal wiki this is
    # fine — we expect O(hundreds) of articles at most. If this ever
    # becomes a bottleneck, narrow the SELECT to (id, title, created_at).
    result = await session.execute(select(Article).order_by(Article.created_at))
    all_articles: list[Article] = list(result.scalars().all())
    if exclude_article_id is not None:
        all_articles = [a for a in all_articles if a.id != exclude_article_id]

    # Build lookup dicts once per call. Both map canonical form → first article.
    by_lower: dict[str, Article] = {}
    by_normalized: dict[str, Article] = {}
    for article in all_articles:
        lower_key = article.title.lower()
        if lower_key not in by_lower:
            by_lower[lower_key] = article
        norm_key = normalize_title(article.title)
        if norm_key and norm_key not in by_normalized:
            by_normalized[norm_key] = article

    resolved_by_target: dict[str, ResolvedBacklink] = {}
    unresolved: list[str] = []
    for candidate in cleaned:
        target = by_lower.get(candidate.lower())
        if target is None:
            norm = normalize_title(candidate)
            if norm:
                target = by_normalized.get(norm)
        if target is None:
            unresolved.append(candidate)
            continue
        # Dedup: two candidates resolving to the same target → one entry.
        if target.id not in resolved_by_target:
            resolved_by_target[target.id] = ResolvedBacklink(
                candidate_text=candidate,
                target_id=target.id,
                target_title=target.title,
            )

    return list(resolved_by_target.values()), unresolved
```

- [ ] **Step 4: Run the tests, verify they pass**

```bash
.venv/bin/pytest tests/unit/test_wikilink_resolver.py -v
```

Expected: all tests PASS. If `async_session` fixture doesn't exist, check `tests/conftest.py` for the project's DB fixture name and update the test file accordingly.

- [ ] **Step 5: Lint + typecheck**

```bash
.venv/bin/ruff check src/wikimind/engine/wikilink_resolver.py tests/unit/test_wikilink_resolver.py
.venv/bin/mypy src/wikimind/engine/wikilink_resolver.py
```

Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/wikimind/engine/wikilink_resolver.py tests/unit/test_wikilink_resolver.py
git commit -m "feat(engine): add two-stage wikilink resolver (#95)"
```

## Task 4: Update the compiler's save path to call the resolver and emit Backlink rows

**Files:**
- Modify: `src/wikimind/engine/compiler.py`
- Modify / extend: `tests/unit/test_compiler.py` (or `tests/unit/test_misc.py` if the compiler test file does not exist)

This is the main surgical change. `_write_article_file` gains two new parameters (resolved + unresolved lists). `_create_article` and `_replace_article_in_place` call the resolver first and then pass the results into the writer. After the article commit, they add `Backlink` rows for each resolved target.

- [ ] **Step 1: Write a failing test asserting the save path creates Backlink rows**

Add to `tests/unit/test_compiler.py` (or create it). The test uses a direct call to the save methods with a mock `CompilationResult`, so it does not need the LLM router.

```python
"""Tests for the compiler's resolution-aware save path."""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.engine.compiler import Compiler
from wikimind.models import (
    Article,
    Backlink,
    CompilationResult,
    CompiledClaim,
    ConfidenceLevel,
    IngestStatus,
    Source,
    SourceType,
)


def _make_result(
    title: str,
    backlink_suggestions: list[str] | None = None,
) -> CompilationResult:
    return CompilationResult(
        title=title,
        summary="A two-sentence summary. For testing.",
        key_claims=[
            CompiledClaim(claim="test claim", confidence=ConfidenceLevel.SOURCED),
        ],
        concepts=["test-concept"],
        backlink_suggestions=backlink_suggestions or [],
        open_questions=["test question?"],
        article_body="## Body\n\nTest body content sufficient length.",
    )


async def _make_source(session: AsyncSession) -> Source:
    source = Source(
        id=str(uuid.uuid4()),
        source_type=SourceType.TEXT,
        title="Test Source",
        status=IngestStatus.NORMALIZED,
        ingested_at=datetime.utcnow(),
    )
    session.add(source)
    await session.commit()
    await session.refresh(source)
    return source


@pytest.mark.asyncio
async def test_save_creates_backlink_rows_for_resolved_candidates(
    async_session: AsyncSession, tmp_path
) -> None:
    # Seed an existing article that a future candidate will resolve to.
    target = Article(
        id=str(uuid.uuid4()),
        slug="existing-article",
        title="Existing Article",
        file_path=str(tmp_path / "existing.md"),
        confidence=ConfidenceLevel.SOURCED,
    )
    async_session.add(target)
    await async_session.commit()

    compiler = Compiler()
    compiler.settings.data_dir = str(tmp_path)  # write wiki files under tmp
    source = await _make_source(async_session)
    result = _make_result(
        "New Article",
        backlink_suggestions=["Existing Article", "Nonexistent Topic"],
    )
    article = await compiler.save_article(result, source, async_session)

    # Backlink row exists for the resolved candidate
    bl_result = await async_session.execute(
        select(Backlink).where(Backlink.source_article_id == article.id)
    )
    backlinks = list(bl_result.scalars().all())
    assert len(backlinks) == 1
    assert backlinks[0].target_article_id == target.id
    assert backlinks[0].context == "Existing Article"


@pytest.mark.asyncio
async def test_save_markdown_has_resolved_link_and_unresolved_bracket(
    async_session: AsyncSession, tmp_path
) -> None:
    target = Article(
        id=str(uuid.uuid4()),
        slug="existing-article",
        title="Existing Article",
        file_path=str(tmp_path / "existing.md"),
        confidence=ConfidenceLevel.SOURCED,
    )
    async_session.add(target)
    await async_session.commit()

    compiler = Compiler()
    compiler.settings.data_dir = str(tmp_path)
    source = await _make_source(async_session)
    result = _make_result(
        "New Article",
        backlink_suggestions=["Existing Article", "Nonexistent Topic"],
    )
    article = await compiler.save_article(result, source, async_session)

    from pathlib import Path
    content = Path(article.file_path).read_text()
    # Resolved link uses the article ID
    assert f"[Existing Article](/wiki/{target.id})" in content
    # Unresolved candidate stays as Obsidian brackets
    assert "[[Nonexistent Topic]]" in content
    # The old-style "- [[Existing Article]]" format is gone for the resolved one
    assert "- [[Existing Article]]" not in content


@pytest.mark.asyncio
async def test_save_handles_duplicate_candidates_without_integrity_error(
    async_session: AsyncSession, tmp_path
) -> None:
    """Two candidates resolving to the same target → one Backlink row, no IntegrityError."""
    target = Article(
        id=str(uuid.uuid4()),
        slug="react",
        title="React",
        file_path=str(tmp_path / "react.md"),
        confidence=ConfidenceLevel.SOURCED,
    )
    async_session.add(target)
    await async_session.commit()

    compiler = Compiler()
    compiler.settings.data_dir = str(tmp_path)
    source = await _make_source(async_session)
    result = _make_result("New Article", backlink_suggestions=["React", "react"])
    article = await compiler.save_article(result, source, async_session)

    bl_result = await async_session.execute(
        select(Backlink).where(Backlink.source_article_id == article.id)
    )
    backlinks = list(bl_result.scalars().all())
    assert len(backlinks) == 1


@pytest.mark.asyncio
async def test_save_skips_backlinks_when_no_candidates(
    async_session: AsyncSession, tmp_path
) -> None:
    compiler = Compiler()
    compiler.settings.data_dir = str(tmp_path)
    source = await _make_source(async_session)
    result = _make_result("Solo Article", backlink_suggestions=[])
    article = await compiler.save_article(result, source, async_session)

    bl_result = await async_session.execute(
        select(Backlink).where(Backlink.source_article_id == article.id)
    )
    assert list(bl_result.scalars().all()) == []
```

- [ ] **Step 2: Run the tests, verify they fail**

```bash
.venv/bin/pytest tests/unit/test_compiler.py -v
```

Expected: FAIL. The current `_create_article` does not call the resolver and does not write `Backlink` rows. The markdown assertion about `[Existing Article](/wiki/<id>)` also fails because the current writer emits `[[Existing Article]]`.

- [ ] **Step 3: Update the compiler**

In `src/wikimind/engine/compiler.py`:

**3a. Add imports at the top** (after the existing imports, keeping the import order — stdlib → third-party → local):

```python
from sqlalchemy.exc import IntegrityError

from wikimind.engine.wikilink_resolver import (
    ResolvedBacklink,
    resolve_backlink_candidates,
)
```

**3b. Modify `_create_article`** (currently at `compiler.py:235`). Add a resolution step before writing the file, and a Backlink-creation step after the article is committed:

```python
async def _create_article(
    self,
    result: CompilationResult,
    source: Source,
    session: AsyncSession,
    provider: Provider | None,
) -> Article:
    """Create a brand-new article (no existing same-provider article)."""
    slug = self._generate_unique_slug(result.title)

    # Resolve wikilink candidates BEFORE writing the file so the markdown
    # knows which links are real and which are dimmed unresolved.
    resolved, unresolved = await resolve_backlink_candidates(
        result.backlink_suggestions, session
    )

    file_path = self._write_article_file(result, source, slug, resolved, unresolved)

    article = Article(
        slug=slug,
        title=result.title,
        file_path=str(file_path),
        confidence=self._overall_confidence(result),
        summary=result.summary,
        source_ids=f'["{source.id}"]',
        concept_ids=f'["{chr(34).join(result.concepts)}"]',
        provider=provider,
    )
    session.add(article)

    source.status = IngestStatus.COMPILED
    source.compiled_at = utcnow_naive()
    session.add(source)

    await session.commit()
    await session.refresh(article)

    # Create Backlink rows for each resolved candidate. Duplicates are
    # guarded by the composite PK — catch IntegrityError and skip.
    await self._persist_backlinks(article.id, resolved, session)

    log.info(
        "Article saved",
        slug=slug,
        title=result.title,
        provider=provider,
        resolved_backlinks=len(resolved),
        unresolved_backlinks=len(unresolved),
    )
    return article
```

**3c. Modify `_replace_article_in_place`** (currently at `compiler.py:268`). Same pattern — resolve, rewrite file, refresh Backlink rows. For the replace path, we also need to clear the old Backlink rows for this source article before inserting the new ones, since the set of resolved candidates may have changed across re-compiles:

```python
async def _replace_article_in_place(
    self,
    existing: Article,
    result: CompilationResult,
    source: Source,
    session: AsyncSession,
) -> Article:
    """Replace an existing same-source same-provider article in place."""
    old_path = Path(existing.file_path)
    old_path.unlink(missing_ok=True)

    # Resolve candidates against the current wiki, excluding self.
    resolved, unresolved = await resolve_backlink_candidates(
        result.backlink_suggestions, session, exclude_article_id=existing.id
    )

    new_path = self._write_article_file(result, source, existing.slug, resolved, unresolved)

    existing.title = result.title
    existing.summary = result.summary
    existing.confidence = self._overall_confidence(result)
    existing.file_path = str(new_path)
    existing.concept_ids = f'["{chr(34).join(result.concepts)}"]'
    existing.updated_at = utcnow_naive()
    session.add(existing)

    source.status = IngestStatus.COMPILED
    source.compiled_at = utcnow_naive()
    session.add(source)

    # Clear stale Backlink rows from the previous compile before inserting
    # the fresh resolved set. Only the source side is cleared.
    old_bl = await session.execute(
        select(Backlink).where(Backlink.source_article_id == existing.id)
    )
    for row in old_bl.scalars().all():
        await session.delete(row)

    await session.commit()
    await session.refresh(existing)

    await self._persist_backlinks(existing.id, resolved, session)

    log.info(
        "Article replaced in place",
        slug=existing.slug,
        title=result.title,
        provider=existing.provider,
        resolved_backlinks=len(resolved),
        unresolved_backlinks=len(unresolved),
    )
    return existing
```

**3d. Add the `_persist_backlinks` helper** as a new method on `Compiler`:

```python
async def _persist_backlinks(
    self,
    source_article_id: str,
    resolved: list[ResolvedBacklink],
    session: AsyncSession,
) -> None:
    """Insert one Backlink row per resolved candidate.

    The composite primary key ``(source_article_id, target_article_id)``
    on :class:`Backlink` rejects duplicates automatically. We catch
    IntegrityError per-row so one duplicate does not abort the batch.
    """
    for rb in resolved:
        bl = Backlink(
            source_article_id=source_article_id,
            target_article_id=rb.target_id,
            context=rb.candidate_text,
        )
        session.add(bl)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            log.debug(
                "Skipped duplicate backlink",
                source=source_article_id,
                target=rb.target_id,
            )
```

**3e. Modify `_write_article_file`** signature and body. Current signature is `(result, source, slug)`; new signature is `(result, source, slug, resolved, unresolved)`. The "Related" section block changes:

```python
def _write_article_file(
    self,
    result: CompilationResult,
    source: Source,
    slug: str,
    resolved: list[ResolvedBacklink],
    unresolved: list[str],
) -> Path:
    """Write .md file to wiki directory.

    The "Related" section emits standard markdown links for resolved
    wikilinks (``[Text](/wiki/<article_id>)``) and Obsidian-style
    brackets only for unresolved candidates (``[[Text]]``). The
    frontend's ArticleReader distinguishes the two at render time:
    resolved become React Router links, unresolved become dimmed spans.
    """
    wiki_dir = Path(self.settings.data_dir) / "wiki"

    concept = result.concepts[0] if result.concepts else "general"
    concept_dir = wiki_dir / slugify(concept)
    concept_dir.mkdir(parents=True, exist_ok=True)

    file_path = concept_dir / f"{slug}.md"

    # Build the "Related" section: resolved links go through standard
    # markdown; unresolved candidates keep Obsidian brackets so the
    # frontend can style them as dead links.
    related_lines: list[str] = []
    for rb in resolved:
        related_lines.append(f"- [{rb.candidate_text}](/wiki/{rb.target_id})")
    for text in unresolved:
        related_lines.append(f"- [[{text}]]")
    backlinks = "\n".join(related_lines)

    claims = "\n".join(
        [f"- **{c.claim}** *({c.confidence})*" + (f' — "{c.quote}"' if c.quote else "") for c in result.key_claims]
    )
    questions = "\n".join([f"- {q}" for q in result.open_questions])
    concepts_str = ", ".join(result.concepts)

    content = f"""---
title: "{result.title}"
slug: {slug}
source_url: {source.source_url or ""}
source_type: {source.source_type}
compiled: {utcnow_naive().isoformat()}
concepts: [{concepts_str}]
confidence: {self._overall_confidence(result)}
---

## Summary

{result.summary}

## Key Claims

{claims}

## Analysis

{result.article_body}

## Open Questions

{questions}

## Related

{backlinks}

## Sources

- {source.title or source.source_url or "Uploaded document"} (ingested {source.ingested_at.strftime("%Y-%m-%d")})
"""

    file_path.write_text(content, encoding="utf-8")
    return file_path
```

- [ ] **Step 4: Run the tests, verify they pass**

```bash
.venv/bin/pytest tests/unit/test_compiler.py -v
```

Expected: all four new tests PASS. If the project does not have an `async_session` fixture, check the existing `tests/conftest.py` and adapt the test imports to the available fixture.

- [ ] **Step 5: Run the broader test suite to catch any downstream breakage**

```bash
.venv/bin/pytest tests/ -x -v
```

Expected: all existing tests still pass. If an existing test was calling `_write_article_file(result, source, slug)` with the old three-argument signature, update it to pass empty `[]` for resolved and unresolved.

- [ ] **Step 6: Lint + typecheck**

```bash
.venv/bin/ruff check src/wikimind/engine/compiler.py tests/unit/test_compiler.py
.venv/bin/mypy src/wikimind/engine/compiler.py
```

Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/wikimind/engine/compiler.py tests/unit/test_compiler.py
git commit -m "feat(compiler): resolve wikilinks and emit Backlink rows at save time (#95)"
```

## Task 5: Update backend article lookup to accept ID or slug

**Files:**
- Modify: `src/wikimind/services/wiki.py`
- Modify: `src/wikimind/api/routes/wiki.py`
- Extend: existing test for `get_article` (in `tests/unit/test_wiki_service.py` or similar — check first)

The lookup currently resolves by slug only. The frontend's resolved wikilinks arrive with article IDs in their URLs, so the backend must accept IDs. Slug lookup remains as a fallback for external bookmarks.

- [ ] **Step 1: Find the existing get_article test**

```bash
grep -rn "get_article\|/wiki/articles/" /Users/mg/mg-work/manav/work/ai-experiments/wikimind/tests/
```

Note the filename. You will extend it in Step 2.

- [ ] **Step 2: Write failing tests for the new behaviour**

Add two tests to whichever file exercises `get_article`. If none exists, add them to `tests/unit/test_misc.py`:

```python
@pytest.mark.asyncio
async def test_get_article_by_id_returns_article(async_session: AsyncSession, tmp_path) -> None:
    """Fetching an article by its UUID id returns it."""
    from wikimind.models import Article, ConfidenceLevel
    from wikimind.services.wiki import WikiService

    article = Article(
        slug="my-article",
        title="My Article",
        file_path=str(tmp_path / "my-article.md"),
        confidence=ConfidenceLevel.SOURCED,
    )
    async_session.add(article)
    await async_session.commit()
    await async_session.refresh(article)

    service = WikiService()
    result = await service.get_article(article.id, async_session)
    assert result.id == article.id
    assert result.slug == "my-article"


@pytest.mark.asyncio
async def test_get_article_by_slug_still_works(async_session: AsyncSession, tmp_path) -> None:
    """Backward compat: slug lookup continues to work after the ID-first rewrite."""
    from wikimind.models import Article, ConfidenceLevel
    from wikimind.services.wiki import WikiService

    article = Article(
        slug="legacy-bookmark",
        title="Legacy Bookmark",
        file_path=str(tmp_path / "legacy.md"),
        confidence=ConfidenceLevel.SOURCED,
    )
    async_session.add(article)
    await async_session.commit()
    await async_session.refresh(article)

    service = WikiService()
    result = await service.get_article("legacy-bookmark", async_session)
    assert result.slug == "legacy-bookmark"
```

- [ ] **Step 3: Run the tests, verify they fail**

```bash
.venv/bin/pytest tests/unit/test_misc.py::test_get_article_by_id_returns_article -v
```

Expected: FAIL (current implementation only looks up by slug, so the UUID lookup returns 404).

- [ ] **Step 4: Update the service**

In `src/wikimind/services/wiki.py`, modify `WikiService.get_article` (currently at line 177). Rename the parameter and try ID first:

```python
async def get_article(self, id_or_slug: str, session: AsyncSession) -> ArticleResponse:
    """Retrieve a full article by ID or slug.

    Tries the article's UUID first (resolved wikilinks travel by ID
    via the ``[text](/wiki/<id>)`` markdown format). Falls back to
    slug lookup for backward compatibility with external bookmarks
    and the human-facing URL bar.

    Args:
        id_or_slug: Either an ``Article.id`` UUID or an ``Article.slug``.
        session: Async database session.

    Returns:
        :class:`ArticleResponse` with content, backlink, and source data.

    Raises:
        HTTPException: If no article matches either lookup.
    """
    # Try ID first
    result = await session.execute(select(Article).where(Article.id == id_or_slug))
    article = result.scalar_one_or_none()
    if article is None:
        # Fall back to slug
        result = await session.execute(select(Article).where(Article.slug == id_or_slug))
        article = result.scalar_one_or_none()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    bl_in = await session.execute(select(Backlink).where(Backlink.target_article_id == article.id))
    bl_out = await session.execute(select(Backlink).where(Backlink.source_article_id == article.id))

    source_ids = _parse_source_ids(article.source_ids)
    sources = await _fetch_sources(session, source_ids)

    return ArticleResponse(
        id=article.id,
        slug=article.slug,
        title=article.title,
        summary=article.summary,
        confidence=article.confidence,
        linter_score=article.linter_score,
        concepts=[],
        backlinks_in=[b.source_article_id for b in bl_in.scalars().all()],
        backlinks_out=[b.target_article_id for b in bl_out.scalars().all()],
        content=_read_article_content(article.file_path),
        sources=[_to_source_response(s) for s in sources],
        created_at=article.created_at,
        updated_at=article.updated_at,
    )
```

- [ ] **Step 5: Update the route**

In `src/wikimind/api/routes/wiki.py`, rename the path parameter:

```python
@router.get("/articles/{id_or_slug}", response_model=ArticleResponse)
async def get_article(
    id_or_slug: str,
    session: AsyncSession = Depends(get_session),
    service: WikiService = Depends(get_wiki_service),
):
    """Get full article by ID or slug, with content, backlinks, and sources."""
    return await service.get_article(id_or_slug, session)
```

Nothing else in the route file changes.

- [ ] **Step 6: Run the tests, verify they pass**

```bash
.venv/bin/pytest tests/unit/test_misc.py::test_get_article_by_id_returns_article tests/unit/test_misc.py::test_get_article_by_slug_still_works -v
```

Expected: PASS.

- [ ] **Step 7: Regenerate OpenAPI (handled automatically by the pre-commit hook, but you can do it manually to see the diff)**

```bash
make export-openapi
```

Expected: `docs/openapi.yaml` gets a small diff renaming the path parameter from `slug` to `id_or_slug`. Review and keep.

- [ ] **Step 8: Commit**

```bash
git add src/wikimind/services/wiki.py src/wikimind/api/routes/wiki.py tests/unit/test_misc.py docs/openapi.yaml
git commit -m "feat(wiki): accept article ID or slug in get_article lookup (#95)"
```

## Task 6: Frontend — remove client-side slugify, render unresolved brackets as dimmed spans

**Files:**
- Modify: `apps/web/src/components/wiki/ArticleReader.tsx`
- Modify: `apps/web/src/index.css` (or whichever global stylesheet is imported by the app — verify via grep first)

This is the client-side counterpart to the backend fix. The frontend no longer slugifies anything. Resolved wikilinks arrive as standard markdown links (`[text](/wiki/<id>)`), handled natively by react-markdown. Unresolved wikilinks stay as `[[text]]` in the markdown body and are replaced with a dimmed span before react-markdown ever sees them.

- [ ] **Step 1: Find the global stylesheet**

```bash
grep -rn 'import.*\.css"' /Users/mg/mg-web/manav/work/ai-experiments/wikimind/apps/web/src/main.tsx /Users/mg/mg-web/manav/work/ai-experiments/wikimind/apps/web/src/App.tsx 2>&1 || true
```

Note the CSS file path. The `.wikilink-unresolved` rule goes there. If the project uses pure Tailwind utility classes (no global rules), use inline Tailwind classes in the preprocessor instead — see Step 3 alternative.

- [ ] **Step 2: Rewrite ArticleReader.tsx**

Open `apps/web/src/components/wiki/ArticleReader.tsx`. Replace its current content with the simplified version below. Key changes:

1. Delete the local `slugify()` helper (lines 19-25 in the current file).
2. Replace the `preprocessMarkdown` wikilink branch — unresolved brackets become a dimmed span; resolved links pass through as standard markdown.
3. Simplify the anchor renderer: internal links (`/wiki/...`) use React Router `<Link>`; external links get `target="_blank"`.

```tsx
import { useMemo } from "react";
import { Link } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";
import type { ArticleResponse, ConfidenceLevel } from "../../types/api";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { Badge } from "../shared/Badge";

interface ArticleReaderProps {
  article: ArticleResponse;
}

const CONFIDENCE_TAG_REGEX = /\[(sourced|mixed|inferred|opinion)\]/gi;
const WIKILINK_REGEX = /\[\[([^\]]+)\]\]/g;
// Match a YAML frontmatter block at the very start of the document.
const FRONTMATTER_REGEX = /^---\r?\n[\s\S]*?\r?\n---\r?\n?/;

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// Pre-process the markdown to:
//   1. Strip the YAML frontmatter block emitted by the compiler.
//   2. Convert unresolved [[wikilinks]] — which is all the compiler
//      emits for links it could NOT resolve against the article table —
//      into a dimmed span. Resolved wikilinks arrive as standard
//      markdown links [text](/wiki/<id>) and need no preprocessing.
function preprocessMarkdown(content: string): string {
  return content
    .replace(FRONTMATTER_REGEX, "")
    .replace(WIKILINK_REGEX, (_, target: string) => {
      const safe = escapeHtml(target.trim());
      return `<span class="wikilink-unresolved" title="Article not yet in wiki">${safe}</span>`;
    });
}

export function ArticleReader({ article }: ArticleReaderProps) {
  const processed = useMemo(
    () => preprocessMarkdown(article.content ?? ""),
    [article.content],
  );

  return (
    <article className="mx-auto max-w-3xl p-8">
      <header className="mb-6 border-b border-slate-200 pb-5">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          {article.confidence ? (
            <ConfidenceBadge level={article.confidence as ConfidenceLevel} />
          ) : null}
          {typeof article.linter_score === "number" ? (
            <Badge tone="info">
              Linter {(article.linter_score * 100).toFixed(0)}%
            </Badge>
          ) : null}
          {article.concepts.slice(0, 3).map((concept) => (
            <Badge key={concept} tone="brand">
              {concept}
            </Badge>
          ))}
        </div>
        <h1 className="text-3xl font-bold text-slate-900">{article.title}</h1>
        {article.summary ? (
          <p className="mt-2 text-base text-slate-600">{article.summary}</p>
        ) : null}
      </header>

      <div className="prose prose-slate max-w-none prose-headings:font-semibold prose-a:text-brand-700">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          rehypePlugins={[rehypeRaw]}
          components={{
            a: ({ node: _node, href, children, ...props }) => {
              // Internal wiki links — resolved wikilinks arrive here from
              // the compiler's [text](/wiki/<id>) markdown. Use React
              // Router so navigation stays client-side.
              if (href?.startsWith("/wiki/")) {
                return (
                  <Link
                    to={href}
                    className="text-brand-700 underline decoration-dotted underline-offset-2 hover:text-brand-900"
                  >
                    {children}
                  </Link>
                );
              }
              // External link — open in a new tab.
              return (
                <a
                  href={href}
                  target="_blank"
                  rel="noreferrer"
                  className="text-brand-700 underline"
                  {...props}
                >
                  {children}
                </a>
              );
            },
            li: ({ children }) => (
              <li>{decorateConfidence(children)}</li>
            ),
            p: ({ children }) => <p>{decorateConfidence(children)}</p>,
          }}
        >
          {processed}
        </ReactMarkdown>
      </div>
    </article>
  );
}

// Walk text children and replace [sourced]/[inferred]/[opinion]/[mixed]
// markers with inline confidence badges. Non-string children are passed through.
function decorateConfidence(children: React.ReactNode): React.ReactNode {
  if (typeof children === "string") {
    return splitConfidence(children);
  }
  if (Array.isArray(children)) {
    return children.map((child, idx) => {
      if (typeof child === "string") {
        return <span key={idx}>{splitConfidence(child)}</span>;
      }
      return child;
    });
  }
  return children;
}

function splitConfidence(text: string): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  CONFIDENCE_TAG_REGEX.lastIndex = 0;
  while ((match = CONFIDENCE_TAG_REGEX.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    const level = match[1].toLowerCase() as ConfidenceLevel;
    parts.push(
      <span key={`${match.index}-${level}`} className="ml-1 align-middle">
        <ConfidenceBadge level={level} />
      </span>,
    );
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }
  return parts.length > 0 ? parts : [text];
}
```

- [ ] **Step 3: Add the `.wikilink-unresolved` style**

If the project uses a global CSS file (from Step 1), add this rule:

```css
.wikilink-unresolved {
  color: rgb(148 163 184); /* slate-400 */
  text-decoration: underline dotted rgb(148 163 184);
  text-underline-offset: 2px;
  cursor: help;
}
```

If the project uses pure Tailwind utility classes with no global rules, update the preprocessor span class instead:

```typescript
return `<span class="text-slate-400 underline decoration-dotted underline-offset-2 cursor-help" title="Article not yet in wiki">${safe}</span>`;
```

Pick whichever matches the existing project style.

- [ ] **Step 4: Frontend lint + typecheck + build**

```bash
cd apps/web && pnpm lint && pnpm typecheck && pnpm build
```

Expected: all three clean. If the build fails on an import that was previously used (e.g. the old `slugify` helper was imported somewhere else), remove the stale import.

- [ ] **Step 5: Manual smoke check (optional but recommended)**

```bash
cd apps/web && pnpm dev
```

Open an article in the browser. Verify:
- The "Related" section renders. Resolved items are underlined brand-color links that navigate on click. Unresolved items are dim slate-400 text with a dotted underline and a "not yet in wiki" tooltip on hover.
- Clicking a resolved link navigates client-side (no full page reload) to the target article.

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/components/wiki/ArticleReader.tsx apps/web/src/index.css
git commit -m "fix(web): remove client-side slugify, render unresolved wikilinks as dimmed spans (#95, #96)"
```

## Task 7: Integration test — end-to-end resolution proof

**Files:**
- Create: `tests/integration/test_wikilink_resolution_integration.py`

This is the single most important test in the whole plan. If it passes, the fix works end-to-end from compile → DB → markdown → route lookup.

- [ ] **Step 1: Write the integration test**

Create `tests/integration/test_wikilink_resolution_integration.py`:

```python
"""End-to-end wikilink resolution proof (issue #95).

Steps:
    1. Seed an existing article "Existing Target".
    2. Drive the compiler's save path with a mock CompilationResult
       whose backlink_suggestions includes "Existing Target" (should
       resolve) and "Nonexistent Topic" (should stay unresolved).
    3. Assert a Backlink row exists pointing new → target.
    4. Assert the rendered markdown has [Existing Target](/wiki/<id>).
    5. Assert the /wiki/articles/{id} route returns the new article
       (verifies the ID-first lookup works end-to-end).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlmodel import select

from wikimind.engine.compiler import Compiler
from wikimind.main import app
from wikimind.models import (
    Article,
    Backlink,
    CompilationResult,
    CompiledClaim,
    ConfidenceLevel,
    IngestStatus,
    Source,
    SourceType,
)


@pytest.mark.asyncio
async def test_wikilink_resolution_end_to_end(async_session, tmp_path, monkeypatch) -> None:
    # 1. Seed an existing target article
    target = Article(
        id=str(uuid.uuid4()),
        slug="existing-target",
        title="Existing Target",
        file_path=str(tmp_path / "existing-target.md"),
        confidence=ConfidenceLevel.SOURCED,
    )
    async_session.add(target)

    # Seed a Source the compiler will mark as COMPILED
    source = Source(
        id=str(uuid.uuid4()),
        source_type=SourceType.TEXT,
        title="Test Source",
        status=IngestStatus.NORMALIZED,
        ingested_at=datetime.utcnow(),
    )
    async_session.add(source)
    await async_session.commit()

    # 2. Drive the save path with a mock CompilationResult
    compiler = Compiler()
    compiler.settings.data_dir = str(tmp_path)
    result = CompilationResult(
        title="New Compiled Article",
        summary="Two sentence summary. For integration test.",
        key_claims=[
            CompiledClaim(claim="test claim", confidence=ConfidenceLevel.SOURCED)
        ],
        concepts=["test"],
        backlink_suggestions=["Existing Target", "Nonexistent Topic"],
        open_questions=["test?"],
        article_body="## Body\n\nTest body content with enough text to be non-trivial.",
    )
    article = await compiler.save_article(result, source, async_session)

    # 3. Backlink row exists
    bl_result = await async_session.execute(
        select(Backlink).where(Backlink.source_article_id == article.id)
    )
    backlinks = list(bl_result.scalars().all())
    assert len(backlinks) == 1
    assert backlinks[0].target_article_id == target.id

    # 4. Markdown has the resolved link by ID and the unresolved bracket
    content = Path(article.file_path).read_text()
    assert f"[Existing Target](/wiki/{target.id})" in content
    assert "[[Nonexistent Topic]]" in content

    # 5. ID-first lookup via the HTTP route returns the new article
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/wiki/articles/{article.id}")
        assert response.status_code == 200
        payload = response.json()
        assert payload["id"] == article.id
        assert payload["title"] == "New Compiled Article"

        # Also verify the resolved link text appears in the content
        assert f"[Existing Target](/wiki/{target.id})" in payload["content"]

        # Slug-based lookup still works (backward compat)
        response_by_slug = await client.get(f"/wiki/articles/{article.slug}")
        assert response_by_slug.status_code == 200
        assert response_by_slug.json()["id"] == article.id
```

- [ ] **Step 2: Run the integration test**

```bash
.venv/bin/pytest tests/integration/test_wikilink_resolution_integration.py -v
```

Expected: PASS. If the test is skipped due to a missing fixture (`async_session` or the ASGI transport pattern is different in this project), check `tests/integration/test_qa_loop_integration.py` for the canonical patterns and adapt.

- [ ] **Step 3: Run `make verify` as the final gate**

```bash
make verify
```

Expected: lint + format + mypy + full test suite green, coverage ≥ 80%.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_wikilink_resolution_integration.py
git commit -m "test(integration): end-to-end wikilink resolution proof (#95)"
```

## Task 8: STOP — migration / backfill decision blocks on user input

**This task is a STOP marker. Do NOT write code.**

Tasks 1–7 implement the forward-only fix: new compiles get real `Backlink` rows and resolved markdown links. Existing articles on disk still contain the old `[[Title]]` text in their "Related" sections — they will render as unresolved (dimmed) spans until the underlying article is re-compiled.

The spec (§ Backfill strategy) flagged three options for what to do about pre-existing articles. Each has different PR-level impact. **The plan explicitly does NOT pick one.**

### The three options — restated for the decision

**Option B1 — Re-compile every existing article on next deploy.**
- Walk every `Article`, re-run the compiler on the original `Source`, let the normal save path produce resolved wikilinks and `Backlink` rows.
- **Pro:** Clean knowledge graph on day one.
- **Con:** LLM cost (every article re-compiled). `updated_at` timestamps change on every row. Provider-based deduplication fingerprints may invalidate. User sees the entire wiki "refresh".
- **PR-level impact:** +1 job module, +1 startup hook or admin endpoint, nontrivial test surface. **Moderate-large change.**

**Option B2 — Forward only.**
- Ship this plan (Tasks 1–7) as-is. New articles get real backlinks. Existing articles keep unresolved `[[Title]]` text until re-ingested.
- **Pro:** Zero disruption. Zero LLM cost. Deterministic. Simplest rollout.
- **Con:** The knowledge graph starts sparse. Existing articles' "Related" sections stay dimmed until the user triggers a recompile.
- **PR-level impact:** **Zero.** This is "do nothing extra" beyond Tasks 1–7. This plan IS B2.

**Option B3 — Incremental resolution sweep job.**
- Add a background job `wikilink_resolution_sweep` that walks existing articles, parses `[[Title]]` tokens from each `.md` file, runs them through the SAME `resolve_backlink_candidates` helper (no LLM call), and — if resolution succeeds now — rewrites the line in the .md file and creates a `Backlink` row.
- **Pro:** Eventually-consistent knowledge graph. No LLM cost. Re-runnable on a timer or after each ingest.
- **Con:** Most code of the three options. New job module, new tests, new scheduling hook, new markdown-round-trip edge cases (idempotency, file lock contention).
- **PR-level impact:** **Moderate.** One new file in `src/wikimind/jobs/`, new tests, a small hook in the ingest-complete signal. Orthogonal to this plan — can ship as a separate follow-up PR.

### What this plan says

**Ship this PR as B2.** Tasks 1–7 close issues #95 and #96 on their own. New articles get the fix. Existing articles fall back to the dimmed-unresolved rendering, which is still strictly better than the current state (404s on every click).

**File a follow-up issue for B3** titled "Incremental wikilink resolution sweep job". Reference this plan and the spec. Do NOT implement it in this PR.

**If the user explicitly chooses B1 during review**, this plan needs a new task (Task 9) that adds the re-compile job — see the spec for rationale and the cost/benefit. That work is out of scope for the current plan.

**Do not proceed past this marker without explicit confirmation from the user on the backfill strategy.**

---

# Final verification checklist

Before opening the PR:

- [ ] All tasks 1–7 committed with TDD-style commit messages
- [ ] `make verify` green locally
- [ ] `docs/openapi.yaml` regenerated (happens automatically via pre-commit; check the diff)
- [ ] Manual smoke check of the Ask → Wiki flow: open an existing article, click a resolved link (should navigate), hover an unresolved span (should show tooltip)
- [ ] PR description references issues #95, #96, and notes the backfill decision ("shipping B2; B3 filed as follow-up issue #<N>")
- [ ] No new files outside the file-structure tables above
- [ ] No changes to the compiler's prompt contract (spec commitment)
- [ ] The single normalizer is the ONLY title normalizer in the codebase (a grep for `unicodedata.normalize` outside `title_normalizer.py` should find only unrelated uses)

# Success criteria

The PR is ready to land when:

1. `make verify` is green.
2. The integration test `test_wikilink_resolution_end_to_end` passes in CI.
3. A fresh compile on a dev wiki produces a `.md` file whose "Related" section has both kinds of links — `[text](/wiki/<id>)` for resolved and `[[text]]` for unresolved — and the `backlink` table gains rows for the resolved entries.
4. Clicking a resolved link in the frontend navigates to the target article without a 404.
5. `WikiService.get_graph` returns a non-empty `edges` list for the first time in the project's history.

When (5) happens, Epic 3 (knowledge graph view) becomes unblocked and can start building on top of real `Backlink` data.
