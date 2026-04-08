# Ask Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the Karpathy loop end-to-end by adding a conversational Ask UI backed by a real `Conversation` data model, plus the integration test that proves filed-back answers are retrievable by future questions.

**Architecture:** Three sequential PRs. PR 1 adds the backend (data model + agent + routes + integration test). PR 2 adds the frontend (Ask UI). PR 3 adds an end-to-end Playwright test that drives the actual UI. Each PR is independently testable. The spec lives at `docs/superpowers/specs/2026-04-08-ask-vertical-slice-design.md` and the architectural decisions are recorded in `docs/adr/adr-011-conversational-qa-thread-model.md` — read both before starting.

**Tech Stack:** FastAPI + SQLModel + SQLite (backend); React 18 + Vite + TypeScript + Tailwind + react-query + react-router (frontend); Playwright (e2e); pytest with hermetic fixtures (backend tests).

---

## Spec coverage

This plan implements the entire spec in three PRs. The brainstormed-and-approved decisions it implements:

| Decision | Source |
|---|---|
| Conversational thread (not single-shot) | Spec § Goals; ADR-011 Decision §1 |
| Per-turn retrieval + conversation context in prompt | Spec § Q&A agent changes; ADR-011 Decision §2 |
| Separate `Conversation` table (not just a column on Query) | Spec § Data model; ADR-011 Decision §1 |
| Thread-level file-back, title = first question, replace on re-save | Spec § File-back changes; ADR-011 Decision §3 |
| Lightweight `_migrate_added_columns` migration (no Alembic) | Spec § Schema additions |
| TurnCard expand/collapse for long answers (per user feedback during brainstorm) | Spec § TurnCard expand/collapse |
| Frontend ships without unit tests; behavioral coverage from PR 3 Playwright | Spec § Frontend tests caveat |

Deferred items (each has a tracking issue): #88 streaming, #89 editing/branching, #90 partial/multi file-back, #91 export, #20 retrieval upgrade, #23/#24/#25 graph, #28 cloud sync.

## Conventions for the implementing engineer

You are implementing in the WikiMind repo. Read `CLAUDE.md` at the repo root before making any change — it documents the project's coding standards, doc-sync protocol, and mandatory pre-merge checks. Key rules:

- **Conventional commits.** Use `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`. Each commit should be one logical change.
- **`make verify` must be green** before any push. It runs ruff lint + format + mypy + pytest with an 80% coverage floor.
- **No magic numbers.** Tunable values go in `Settings` (`src/wikimind/config.py`), not as inline constants.
- **No silent failures.** Errors raise; fallback paths log and re-raise. Don't add try/except just to swallow.
- **Hermetic tests.** Mock the LLM router boundary, never make real API calls. Use the existing fixtures in `tests/conftest.py`.
- **Doc-sync.** If you change a route, the pre-commit hook will re-generate `docs/openapi.yaml` for you. If you add a new architectural decision, add an ADR. The doc-sync co-change rule will fail your PR otherwise.
- **TDD for backend.** Write the failing test, run it to confirm it fails, write minimal implementation, run it to confirm it passes, commit. The plan steps are written this way; follow them.
- **No TDD for frontend** — the project has no frontend test infrastructure today. The spec deliberately defers introducing it. You will run `lint` + `typecheck` + `build` and a manual smoke check via the dev server, then rely on PR 3's Playwright test for behavioral coverage.
- **Don't expand scope.** Anything not in this plan or the spec is out of scope. If you find yourself wanting to "also fix" something, file an issue instead.

---

# File Structure

## PR 1 — Backend

### Files to create

| Path | Responsibility |
|---|---|
| `src/wikimind/engine/conversation_serializer.py` | Single-source-of-truth function `serialize_conversation_to_markdown(conversation, queries)` that converts a thread to the wiki article markdown format. Used by file-back today and the export endpoint (#91) tomorrow. |
| `tests/unit/test_conversation_serializer.py` | Unit tests for the serializer. |

### Files to modify

| Path | What changes |
|---|---|
| `src/wikimind/config.py` | Add `QAConfig` Pydantic submodel with three new fields (`max_prior_turns_in_context`, `prior_answer_truncate_chars`, `conversation_title_max_chars`). Wire it into `Settings` as `qa: QAConfig`. |
| `src/wikimind/models.py` | Add `Conversation` SQLModel table; add `conversation_id` (nullable FK) and `turn_index` (default 0) columns to `Query`; add Pydantic `ConversationResponse`, `ConversationSummary`, `ConversationDetail`, and `AskResponse` schemas. |
| `src/wikimind/database.py` | Extend the `additions` list in `_migrate_added_columns()` with the two new `query` columns. Add `_backfill_conversation_for_legacy_queries()` helper. Call it from `init_db()` after `_migrate_added_columns`. |
| `src/wikimind/engine/qa_agent.py` | Update `QAAgent.answer()` signature to accept optional `conversation_id` and return `tuple[Query, Conversation]`. Add `_load_prior_turns()` helper. Update prompt assembly in `_query_llm()` to include "Conversation so far" block when prior turns exist. Replace `_file_back()` with `_file_back_thread()` that operates on a Conversation. Drop the now-unused per-Query file-back code. |
| `src/wikimind/services/query.py` | Update `ask()` to accept `conversation_id` and return `AskResponse`. Add `list_conversations()`, `get_conversation()`, `file_back_conversation()`. Delete `file_back()` (per-Query). |
| `src/wikimind/api/routes/query.py` | Update `POST /query` request body and response. Delete `POST /query/{id}/file-back`. Add `POST /conversations/{id}/file-back`, `GET /conversations`, `GET /conversations/{id}`. |
| `tests/unit/test_qa_agent.py` | Update existing mocks for the new `(Query, Conversation)` return shape. Add test for `_load_prior_turns()`. Add test for `_file_back_thread()` create-vs-update branching. |
| `tests/integration/test_qa_loop_integration.py` | This file already exists from PR #85 and contains the basic file-back integration test. Add two new tests: `test_multi_turn_conversation_includes_prior_context_in_prompt` and the headline `test_filed_back_conversation_is_retrievable_by_next_query` (the loop closure proof). |
| `.env.example` | Add three new `WIKIMIND_QA__*` env vars matching the new Settings fields. |

## PR 2 — Frontend

### Files to create

| Path | Responsibility |
|---|---|
| `apps/web/src/components/ask/AskView.tsx` | Page container for `/ask` and `/ask/:conversationId`. Two-column layout. |
| `apps/web/src/components/ask/ConversationHistory.tsx` | Sidebar list of conversations from `GET /conversations`. |
| `apps/web/src/components/ask/ConversationThread.tsx` | Renders all turns in order. Hosts the SaveThreadButton at the bottom. |
| `apps/web/src/components/ask/TurnCard.tsx` | One Q+A pair with expand/collapse for long answers. |
| `apps/web/src/components/ask/QueryInput.tsx` | Bottom-anchored input. Submit on Enter. |
| `apps/web/src/components/ask/SaveThreadButton.tsx` | Thread-level file-back trigger with "Save" → "Update" state transition. |

### Files to modify

| Path | What changes |
|---|---|
| `apps/web/src/api/query.ts` | Add `Conversation`, `ConversationSummary`, `ConversationDetail`, `AskRequest`, `AskResponse` types. Add `listConversations`, `getConversation`, `fileBackConversation` functions. Update `askQuestion` return type. |
| `apps/web/src/App.tsx` | Add `/ask` and `/ask/:conversationId` routes. |
| `apps/web/src/components/shared/Layout.tsx` | Add "Ask" nav link between Inbox and Wiki. |
| `README.md` | Update Phase 2 checklist — `[ ]` → `[x]` for "Q&A Agent — complete implementation" (partial). |

## PR 3 — Playwright e2e

### Files to create

| Path | Responsibility |
|---|---|
| `apps/web/playwright.config.ts` | Playwright config; runs against the local Vite dev server with the FastAPI gateway as the backend. |
| `apps/web/tests/e2e/ask-loop.spec.ts` | Single end-to-end test that drives the Ask UI through the full loop. |

### Files to modify

| Path | What changes |
|---|---|
| `apps/web/package.json` | Add `@playwright/test` as a devDependency. Add `e2e` script. |

---

# PR 1 — Backend

**Branch:** `claude/ask-slice-pr1-backend`

**Definition of done for PR 1:** All backend tasks below complete, `make verify` green, both new integration tests passing, ADR-011 already in main (it is — landed with PR #92). PR 1 ships independently of any frontend work.

## Task 1.1: Add QA settings submodel

**Files:**
- Modify: `src/wikimind/config.py`

This task adds three new tunable values via Pydantic Settings. Per the project rule: no magic numbers, all configuration goes through Settings.

- [ ] **Step 1: Add the QAConfig submodel**

In `src/wikimind/config.py`, after the existing `class ServerConfig(BaseModel):` block (around line 109-113), add:

```python
class QAConfig(BaseModel):
    """Q&A agent configuration — controls multi-turn conversation behavior."""

    max_prior_turns_in_context: int = 5
    prior_answer_truncate_chars: int = 500
    conversation_title_max_chars: int = 120
```

- [ ] **Step 2: Wire QAConfig into Settings**

In the same file, find the `Settings` class (around line 125) and add the new field next to the other nested config fields (after `server: ServerConfig = Field(...)`):

```python
    server: ServerConfig = Field(default_factory=ServerConfig)
    qa: QAConfig = Field(default_factory=QAConfig)
```

- [ ] **Step 3: Run lint + typecheck**

```bash
.venv/bin/ruff check src/wikimind/config.py
.venv/bin/mypy src/wikimind/config.py
```

Expected: both clean.

- [ ] **Step 4: Verify existing tests still pass**

```bash
.venv/bin/pytest tests/unit/test_misc.py -k "settings" -v
```

Expected: existing settings tests still pass (no test changes needed — the new field is optional with defaults).

- [ ] **Step 5: Commit**

```bash
git add src/wikimind/config.py
git commit -m "feat(config): add QAConfig submodel with conversation tunables"
```

## Task 1.2: Add Conversation SQLModel and Query column additions

**Files:**
- Modify: `src/wikimind/models.py`

- [ ] **Step 1: Add the Conversation table after the existing Query class**

In `src/wikimind/models.py`, find the `class Query(SQLModel, table=True):` definition (around line 162). Right BEFORE it, add:

```python
class Conversation(SQLModel, table=True):
    """A conversation thread of one or more Q&A turns.

    Conversations group related Q&A turns that share LLM context. The
    first turn's question becomes the conversation's title (truncated).
    Filing a conversation back to the wiki is a per-conversation action,
    not per-turn — see ADR-011.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    title: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    filed_article_id: str | None = Field(default=None, foreign_key="article.id")
```

- [ ] **Step 2: Add new fields to the existing Query class**

In the same file, modify the `Query` class to add two new fields. The existing class has these fields:

```python
class Query(SQLModel, table=True):
    """Q&A history entry."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    question: str
    answer: str
    confidence: str | None = None
    source_article_ids: str | None = None  # JSON array
    related_article_ids: str | None = None  # JSON array
    filed_back: bool = False
    filed_article_id: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

Add two new fields after `created_at`:

```python
    # Conversation grouping (added by ADR-011)
    conversation_id: str | None = Field(
        default=None, foreign_key="conversation.id", index=True
    )
    turn_index: int = 0  # 0 for first turn, 1 for second, etc.
```

`conversation_id` is nullable in the schema (the lightweight migration helper cannot add NOT NULL columns to existing tables) but always populated by app code. The `filed_back` and `filed_article_id` columns stay for back-compat but are no longer the source of truth — leave them in place.

- [ ] **Step 3: Add the new Pydantic response schemas**

In the same file, find the existing `class QueryResponse(BaseModel):` (around line 404 — at the bottom of the file in the Pydantic-only section). After it, add:

```python
class ConversationResponse(BaseModel):
    """Conversation metadata exposed via API."""

    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    filed_article_id: str | None = None


class ConversationSummary(ConversationResponse):
    """Conversation summary for the history sidebar — adds turn count."""

    turn_count: int


class ConversationDetail(BaseModel):
    """Full conversation thread with all queries ordered by turn_index."""

    conversation: ConversationResponse
    queries: list[QueryResponse]


class AskResponse(BaseModel):
    """Response shape for POST /query — wraps both the new query and its parent conversation."""

    query: QueryResponse
    conversation: ConversationResponse
```

- [ ] **Step 4: Add conversation_id to QueryRequest**

Find the existing `class QueryRequest(BaseModel):` (around line 319) and add an optional `conversation_id` field:

```python
class QueryRequest(BaseModel):
    """Request body for POST /query."""

    question: str
    file_back: bool = False  # deprecated; ignored by new conversation-aware code
    conversation_id: str | None = None  # NEW — None means start a new conversation
```

(If the existing class has different field names, preserve them — only ADD `conversation_id`.)

- [ ] **Step 5: Run lint + typecheck**

```bash
.venv/bin/ruff check src/wikimind/models.py
.venv/bin/mypy src/wikimind/models.py
```

Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/wikimind/models.py
git commit -m "feat(models): add Conversation table + Query.conversation_id (ADR-011)"
```

## Task 1.3: Extend the lightweight migration helper

**Files:**
- Modify: `src/wikimind/database.py`

The repo's migration approach is described in `database.py:_migrate_added_columns()` — it inspects each table via `PRAGMA table_info` and runs `ALTER TABLE ... ADD COLUMN` for any column the model declares that isn't already present. We extend the `additions` list with the two new columns on `query`. The new `Conversation` table itself is created automatically by `SQLModel.metadata.create_all()` — no manual SQL needed.

- [ ] **Step 1: Write a test asserting the new columns exist after init_db**

Create or extend `tests/unit/test_misc.py` (which already has migration-related tests). Add this test:

```python
async def test_init_db_adds_conversation_id_and_turn_index_to_query(tmp_path, monkeypatch):
    """The lightweight migration helper adds the new query columns on a fresh DB."""
    import sqlite3

    from wikimind.config import get_settings
    from wikimind.database import close_db, get_db_path, init_db

    # Point at a fresh tmp data dir
    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()

    await init_db()

    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(query)").fetchall()}
    finally:
        conn.close()

    assert "conversation_id" in cols
    assert "turn_index" in cols

    await close_db()
    get_settings.cache_clear()
```

- [ ] **Step 2: Run the test, verify it fails**

```bash
.venv/bin/pytest tests/unit/test_misc.py::test_init_db_adds_conversation_id_and_turn_index_to_query -v
```

Expected: FAIL — the columns don't exist yet because we haven't extended `_migrate_added_columns`.

- [ ] **Step 3: Extend the additions list**

In `src/wikimind/database.py`, find `_migrate_added_columns()` (around line 95). The existing `additions` list looks like:

```python
    additions: list[tuple[str, str, str]] = [
        # (table, column, ALTER fragment)
        ("source", "content_hash", "ALTER TABLE source ADD COLUMN content_hash TEXT"),
        ("article", "provider", "ALTER TABLE article ADD COLUMN provider TEXT"),
    ]
```

Add two entries:

```python
    additions: list[tuple[str, str, str]] = [
        # (table, column, ALTER fragment)
        ("source", "content_hash", "ALTER TABLE source ADD COLUMN content_hash TEXT"),
        ("article", "provider", "ALTER TABLE article ADD COLUMN provider TEXT"),
        # ADR-011 — conversation grouping for Q&A turns
        ("query", "conversation_id", "ALTER TABLE query ADD COLUMN conversation_id TEXT REFERENCES conversation(id)"),
        ("query", "turn_index", "ALTER TABLE query ADD COLUMN turn_index INTEGER NOT NULL DEFAULT 0"),
    ]
```

Also update the function's docstring (lines 96-107) — the "Currently tracks" list at the bottom of the docstring should mention the new columns. Add two lines:

```
    Currently tracks:
        - source.content_hash (issue #67) + index
        - article.provider    (issue #67)
        - query.conversation_id (ADR-011)
        - query.turn_index    (ADR-011)
```

- [ ] **Step 4: Run the test, verify it passes**

```bash
.venv/bin/pytest tests/unit/test_misc.py::test_init_db_adds_conversation_id_and_turn_index_to_query -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/wikimind/database.py tests/unit/test_misc.py
git commit -m "feat(database): add query.conversation_id and turn_index to migration helper"
```

## Task 1.4: Add the legacy-Query backfill helper

**Files:**
- Modify: `src/wikimind/database.py`

Pre-existing `Query` rows (if any) will have `conversation_id IS NULL` after the migration. App code assumes every Query has a conversation, so we must backfill. The backfill is idempotent (re-running finds zero NULL rows and does nothing).

- [ ] **Step 1: Write the test**

Add to `tests/unit/test_misc.py`:

```python
async def test_backfill_creates_conversation_for_legacy_query(tmp_path, monkeypatch):
    """Legacy Query rows with NULL conversation_id get a Conversation row backfilled."""
    import uuid
    from datetime import datetime

    from sqlmodel.ext.asyncio.session import AsyncSession

    from wikimind.config import get_settings
    from wikimind.database import close_db, get_session_factory, init_db
    from wikimind.models import Conversation, Query

    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    await init_db()

    # Insert a Query row directly without conversation_id (simulating a legacy row)
    factory = get_session_factory()
    async with factory() as session:  # type: AsyncSession
        legacy = Query(
            id=str(uuid.uuid4()),
            question="What is the legacy question?",
            answer="Legacy answer.",
            confidence="high",
            created_at=datetime.utcnow(),
        )
        # Bypass conversation_id requirement by inserting raw
        session.add(legacy)
        await session.commit()
        legacy_id = legacy.id

    # Run init_db again — backfill should kick in
    await init_db()

    async with factory() as session:
        result = await session.get(Query, legacy_id)
        assert result is not None
        assert result.conversation_id is not None
        assert result.turn_index == 0

        conv = await session.get(Conversation, result.conversation_id)
        assert conv is not None
        assert conv.title == "What is the legacy question?"

    # Idempotency: a third init_db should be a no-op
    await init_db()
    async with factory() as session:
        result_count = await session.execute(
            __import__("sqlmodel").select(Conversation).where(Conversation.id == result.conversation_id)
        )
        rows = list(result_count.scalars().all())
        assert len(rows) == 1, "backfill is not idempotent — it duplicated the conversation row"

    await close_db()
    get_settings.cache_clear()
```

- [ ] **Step 2: Run the test, verify it fails**

```bash
.venv/bin/pytest tests/unit/test_misc.py::test_backfill_creates_conversation_for_legacy_query -v
```

Expected: FAIL — there's no backfill helper yet.

- [ ] **Step 3: Add the backfill helper**

In `src/wikimind/database.py`, after `_migrate_added_columns()`, add a new function:

```python
async def _backfill_conversation_for_legacy_queries(engine) -> None:
    """Create a Conversation row for any Query that has NULL conversation_id.

    Idempotent: re-running finds zero NULL rows and is a no-op. Each
    legacy Query becomes a single-turn Conversation whose title is the
    question (truncated to qa.conversation_title_max_chars), whose
    timestamps mirror the Query's, and whose filed_article_id mirrors
    the Query's existing filed_article_id (so legacy file-back state
    is preserved).

    See ADR-011.
    """
    import uuid
    from datetime import datetime

    from wikimind.config import get_settings

    settings = get_settings()
    title_max = settings.qa.conversation_title_max_chars

    async with engine.begin() as conn:

        def _select_legacy(sync_conn):
            return sync_conn.exec_driver_sql(
                "SELECT id, question, created_at, filed_article_id FROM query WHERE conversation_id IS NULL"
            ).fetchall()

        legacy_rows = await conn.run_sync(_select_legacy)

        for row in legacy_rows:
            query_id, question, created_at_raw, filed_article_id = row
            conv_id = str(uuid.uuid4())
            title = (question or "")[:title_max]
            # SQLite stores datetimes as strings via SQLModel; reuse the raw value if present
            created_at = created_at_raw or datetime.utcnow().isoformat()

            await conn.exec_driver_sql(
                "INSERT INTO conversation (id, title, created_at, updated_at, filed_article_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (conv_id, title, created_at, created_at, filed_article_id),
            )
            await conn.exec_driver_sql(
                "UPDATE query SET conversation_id = ?, turn_index = 0 WHERE id = ?",
                (conv_id, query_id),
            )
```

- [ ] **Step 4: Wire the backfill into init_db**

Still in `src/wikimind/database.py`, find `init_db()` (around line 79) and call the new helper after `_migrate_added_columns`:

```python
async def init_db():
    """Create all tables and run idempotent column migrations.

    [keep existing docstring]
    """
    engine = get_async_engine()
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    await _migrate_added_columns(engine)
    await _backfill_conversation_for_legacy_queries(engine)
```

- [ ] **Step 5: Run the test, verify it passes**

```bash
.venv/bin/pytest tests/unit/test_misc.py::test_backfill_creates_conversation_for_legacy_query -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/wikimind/database.py tests/unit/test_misc.py
git commit -m "feat(database): backfill Conversation for legacy Query rows"
```

## Task 1.5: Write the conversation serializer

**Files:**
- Create: `src/wikimind/engine/conversation_serializer.py`
- Create: `tests/unit/test_conversation_serializer.py`

The serializer is the **single source of truth** for thread → markdown conversion. The file-back path uses it today; the export endpoint (#91) will use it tomorrow. Same input → identical output, byte-for-byte.

- [ ] **Step 1: Write failing tests for the serializer**

Create `tests/unit/test_conversation_serializer.py`:

```python
"""Unit tests for the conversation → markdown serializer (ADR-011)."""

from datetime import datetime

from wikimind.engine.conversation_serializer import serialize_conversation_to_markdown
from wikimind.models import Conversation, Query


def _conv(title: str = "What is X?") -> Conversation:
    return Conversation(
        id="conv-1",
        title=title,
        created_at=datetime(2026, 4, 8, 12, 0, 0),
        updated_at=datetime(2026, 4, 8, 12, 5, 0),
    )


def _q(question: str, answer: str, turn_index: int = 0, sources: str = "[]") -> Query:
    return Query(
        id=f"q-{turn_index}",
        question=question,
        answer=answer,
        confidence="high",
        source_article_ids=sources,
        conversation_id="conv-1",
        turn_index=turn_index,
        created_at=datetime(2026, 4, 8, 12, 0, turn_index),
    )


def test_serializer_emits_frontmatter_with_required_fields():
    conv = _conv()
    queries = [_q("What is X?", "X is a thing.", turn_index=0)]
    md = serialize_conversation_to_markdown(conv, queries)

    assert md.startswith("---\n")
    assert 'title: "What is X?"' in md
    assert "type: qa-conversation" in md
    assert "turn_count: 1" in md
    assert "created: 2026-04-08T12:00:00" in md
    assert "updated: 2026-04-08T12:05:00" in md


def test_serializer_emits_one_section_per_turn_in_order():
    conv = _conv()
    queries = [
        _q("What is X?", "X is a thing.", turn_index=0),
        _q("How does it work?", "It works by Y.", turn_index=1),
        _q("Any limitations?", "Yes — Z.", turn_index=2),
    ]
    md = serialize_conversation_to_markdown(conv, queries)

    # All three questions appear, in order
    pos_q1 = md.find("Q1: What is X?")
    pos_q2 = md.find("Q2: How does it work?")
    pos_q3 = md.find("Q3: Any limitations?")
    assert 0 < pos_q1 < pos_q2 < pos_q3


def test_serializer_renders_sources_as_wikilinks():
    conv = _conv()
    queries = [_q("Q?", "A.", turn_index=0, sources='["Article One", "Article Two"]')]
    md = serialize_conversation_to_markdown(conv, queries)

    assert "[[Article One]]" in md
    assert "[[Article Two]]" in md


def test_serializer_handles_empty_sources():
    conv = _conv()
    queries = [_q("Q?", "A.", turn_index=0, sources='[]')]
    md = serialize_conversation_to_markdown(conv, queries)

    # Sources block is omitted when empty (or shown empty — either is fine, just must not crash)
    assert "Q1: Q?" in md
    assert "A." in md


def test_serializer_uses_conversation_title_as_h1():
    conv = _conv(title="My exploration")
    queries = [_q("First question", "First answer", turn_index=0)]
    md = serialize_conversation_to_markdown(conv, queries)

    assert "# My exploration" in md


def test_serializer_byte_identical_for_same_input():
    """Two calls with the same input must produce byte-identical output."""
    conv = _conv()
    queries = [_q("Q1", "A1", turn_index=0), _q("Q2", "A2", turn_index=1)]

    a = serialize_conversation_to_markdown(conv, queries)
    b = serialize_conversation_to_markdown(conv, queries)

    assert a == b
```

- [ ] **Step 2: Run the tests, verify they fail**

```bash
.venv/bin/pytest tests/unit/test_conversation_serializer.py -v
```

Expected: FAIL with `ModuleNotFoundError` because the serializer doesn't exist yet.

- [ ] **Step 3: Implement the serializer**

Create `src/wikimind/engine/conversation_serializer.py`:

```python
"""Serialize a Q&A conversation to wiki article markdown.

Single source of truth for thread → markdown conversion. Used by the
file-back path (which writes the result to disk and creates an Article
row) and by the upcoming conversation-export endpoint (#91, which
returns it directly without persisting). The two paths MUST produce
byte-identical output for the same input.

See ADR-011.
"""

from __future__ import annotations

import json

from slugify import slugify

from wikimind.models import Conversation, Query


def serialize_conversation_to_markdown(
    conversation: Conversation,
    queries: list[Query],
) -> str:
    """Serialize a conversation and its turns into wiki article markdown.

    Args:
        conversation: The Conversation row.
        queries: All Query rows for the conversation, ordered by turn_index.

    Returns:
        Markdown string with frontmatter and one section per turn.
    """
    slug = slugify(conversation.title or "untitled-conversation")[:80]
    turn_count = len(queries)

    lines: list[str] = []
    lines.append("---")
    lines.append(f'title: "{conversation.title}"')
    lines.append(f"slug: {slug}")
    lines.append("type: qa-conversation")
    lines.append(f"created: {conversation.created_at.isoformat()}")
    lines.append(f"updated: {conversation.updated_at.isoformat()}")
    lines.append(f"turn_count: {turn_count}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {conversation.title}")
    lines.append("")

    for query in queries:
        turn_number = query.turn_index + 1  # 1-indexed in the document
        lines.append(f"## Q{turn_number}: {query.question}")
        lines.append("")
        lines.append(query.answer)
        lines.append("")

        # Sources block — omitted if no sources
        sources = _parse_sources(query.source_article_ids)
        if sources:
            lines.append("**Sources:** " + ", ".join(f"[[{s}]]" for s in sources))
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _parse_sources(raw: str | None) -> list[str]:
    """Parse the JSON-encoded source_article_ids field into a list of titles."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if item]
```

- [ ] **Step 4: Run the tests, verify they pass**

```bash
.venv/bin/pytest tests/unit/test_conversation_serializer.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/wikimind/engine/conversation_serializer.py tests/unit/test_conversation_serializer.py
git commit -m "feat(engine): add conversation_serializer for thread → markdown"
```

## Task 1.6: Add _load_prior_turns to QAAgent

**Files:**
- Modify: `src/wikimind/engine/qa_agent.py`
- Modify: `tests/unit/test_qa_agent.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_qa_agent.py`:

```python
async def test_load_prior_turns_returns_in_order_capped_at_max(test_session):
    """_load_prior_turns returns at most qa.max_prior_turns_in_context, ordered by turn_index."""
    from datetime import datetime

    from wikimind.engine.qa_agent import QAAgent
    from wikimind.models import Conversation, Query

    conv = Conversation(id="conv-x", title="t", created_at=datetime.utcnow(), updated_at=datetime.utcnow())
    test_session.add(conv)

    # Insert 7 turns; cap is 5
    for i in range(7):
        test_session.add(
            Query(
                id=f"q-{i}",
                question=f"q{i}",
                answer=f"a{i}",
                conversation_id="conv-x",
                turn_index=i,
            )
        )
    await test_session.commit()

    agent = QAAgent()
    prior = await agent._load_prior_turns("conv-x", up_to_turn_index=7, session=test_session)

    # Returns the 5 most recent prior turns (turns 2, 3, 4, 5, 6) in turn_index order
    assert len(prior) == 5
    assert [q.turn_index for q in prior] == [2, 3, 4, 5, 6]
```

(`test_session` is the existing async session fixture from `tests/conftest.py`. If it doesn't exist by that name, use whatever the conftest provides.)

- [ ] **Step 2: Run the test, verify it fails**

```bash
.venv/bin/pytest tests/unit/test_qa_agent.py::test_load_prior_turns_returns_in_order_capped_at_max -v
```

Expected: FAIL — `_load_prior_turns` doesn't exist.

- [ ] **Step 3: Implement _load_prior_turns**

In `src/wikimind/engine/qa_agent.py`, add a new method to the `QAAgent` class:

```python
    async def _load_prior_turns(
        self,
        conversation_id: str,
        up_to_turn_index: int,
        session: AsyncSession,
    ) -> list[Query]:
        """Load up to qa.max_prior_turns_in_context turns from a conversation.

        Returns the most recent N prior turns (where N = the configured cap),
        ordered ascending by turn_index so they can be formatted into the
        prompt in conversational order.

        Args:
            conversation_id: The conversation to load turns from.
            up_to_turn_index: Only return turns whose turn_index is strictly
                less than this value (i.e. turns BEFORE the one being asked).
            session: Async database session.

        Returns:
            List of Query rows ordered by turn_index ascending.
        """
        cap = self.settings.qa.max_prior_turns_in_context
        result = await session.execute(
            select(Query)
            .where(Query.conversation_id == conversation_id)
            .where(Query.turn_index < up_to_turn_index)
            .order_by(Query.turn_index.desc())  # type: ignore[attr-defined]
            .limit(cap)
        )
        rows = list(result.scalars().all())
        rows.sort(key=lambda q: q.turn_index)  # back to ascending for prompt order
        return rows
```

- [ ] **Step 4: Run the test, verify it passes**

```bash
.venv/bin/pytest tests/unit/test_qa_agent.py::test_load_prior_turns_returns_in_order_capped_at_max -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/wikimind/engine/qa_agent.py tests/unit/test_qa_agent.py
git commit -m "feat(qa_agent): add _load_prior_turns helper"
```

## Task 1.7: Update QAAgent.answer signature for conversation awareness

**Files:**
- Modify: `src/wikimind/engine/qa_agent.py`
- Modify: `tests/unit/test_qa_agent.py`

This is the central change. `answer()` becomes conversation-aware: if no `conversation_id` is supplied, it creates a new Conversation; if one is supplied, it appends a new turn to that conversation. It returns both the new Query and the (possibly newly created) Conversation.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_qa_agent.py`:

```python
async def test_answer_creates_new_conversation_when_id_missing(test_session, mock_llm_router):
    """answer() with no conversation_id creates a new Conversation and returns turn 0."""
    from wikimind.engine.qa_agent import QAAgent
    from wikimind.models import QueryRequest, Conversation, Query

    agent = QAAgent()
    req = QueryRequest(question="What is the meaning of life?")

    query, conversation = await agent.answer(req, test_session)

    assert isinstance(conversation, Conversation)
    assert conversation.title == "What is the meaning of life?"
    assert query.conversation_id == conversation.id
    assert query.turn_index == 0


async def test_answer_appends_to_existing_conversation(test_session, mock_llm_router):
    """answer() with a conversation_id appends a new turn with the next turn_index."""
    from datetime import datetime

    from wikimind.engine.qa_agent import QAAgent
    from wikimind.models import Conversation, Query, QueryRequest

    conv = Conversation(
        id="conv-existing",
        title="prior question",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    test_session.add(conv)
    test_session.add(
        Query(
            id="q-prior",
            question="prior question",
            answer="prior answer",
            conversation_id="conv-existing",
            turn_index=0,
        )
    )
    await test_session.commit()

    agent = QAAgent()
    req = QueryRequest(question="follow-up question", conversation_id="conv-existing")

    query, conversation = await agent.answer(req, test_session)

    assert conversation.id == "conv-existing"
    assert query.conversation_id == "conv-existing"
    assert query.turn_index == 1
```

(`mock_llm_router` is a fixture in `tests/conftest.py`. If it has a different name, use whichever fixture mocks the LLM router boundary in existing tests like `test_answer_with_context_and_file_back`.)

- [ ] **Step 2: Run the tests, verify they fail**

```bash
.venv/bin/pytest tests/unit/test_qa_agent.py::test_answer_creates_new_conversation_when_id_missing tests/unit/test_qa_agent.py::test_answer_appends_to_existing_conversation -v
```

Expected: FAIL — `answer()` doesn't yet accept conversation_id and doesn't return a tuple.

- [ ] **Step 3: Update QAAgent.answer**

In `src/wikimind/engine/qa_agent.py`, replace the existing `answer()` method with:

```python
    async def answer(
        self,
        request: QueryRequest,
        session: AsyncSession,
    ) -> tuple[Query, Conversation]:
        """Answer a question against the wiki.

        Conversation-aware: if request.conversation_id is None a new
        Conversation is created with this question's text as its title.
        Otherwise the turn is appended to the existing conversation and
        the prompt is augmented with the prior N turns as context.

        Args:
            request: The QueryRequest with question and optional conversation_id.
            session: Async database session.

        Returns:
            Tuple of (the new Query row, the parent Conversation).
        """
        log.info("Q&A query", question=request.question[:100])

        # Resolve or create the conversation
        conversation = await self._get_or_create_conversation(request, session)

        # Load prior turns BEFORE persisting the new one (so the new turn
        # doesn't appear in its own context)
        prior_turns: list[Query] = []
        if request.conversation_id is not None:
            next_turn_index = await self._next_turn_index(conversation.id, session)
            prior_turns = await self._load_prior_turns(
                conversation.id, up_to_turn_index=next_turn_index, session=session
            )
        else:
            next_turn_index = 0

        # Retrieve wiki context (unchanged from prior implementation)
        context = await self._retrieve_context(request.question, session)

        if not context:
            result = QueryResult(
                answer="No relevant articles found in your wiki for this question. Consider ingesting sources on this topic.",
                confidence="low",
                sources=[],
                related_articles=[],
                follow_up_questions=[f"What sources cover {request.question}?"],
            )
        else:
            result = await self._query_llm(request.question, context, prior_turns, session)

        # Persist the new Query row
        query_record = Query(
            question=request.question,
            answer=result.answer,
            confidence=result.confidence,
            source_article_ids=json.dumps(result.sources),
            related_article_ids=json.dumps(result.related_articles),
            conversation_id=conversation.id,
            turn_index=next_turn_index,
        )
        session.add(query_record)

        # Touch the conversation's updated_at
        from datetime import datetime
        conversation.updated_at = datetime.utcnow()
        session.add(conversation)

        await session.commit()
        await session.refresh(query_record)
        await session.refresh(conversation)

        return query_record, conversation
```

- [ ] **Step 4: Add the helper methods**

In the same class, add these helpers (place them right after `_load_prior_turns` from Task 1.6):

```python
    async def _get_or_create_conversation(
        self,
        request: QueryRequest,
        session: AsyncSession,
    ) -> Conversation:
        """Resolve an existing conversation or create a new one for this question."""
        if request.conversation_id is not None:
            existing = await session.get(Conversation, request.conversation_id)
            if existing is None:
                from fastapi import HTTPException

                raise HTTPException(status_code=404, detail="Conversation not found")
            return existing

        title_max = self.settings.qa.conversation_title_max_chars
        new_conv = Conversation(
            title=request.question[:title_max],
        )
        session.add(new_conv)
        await session.flush()  # populate new_conv.id without committing
        return new_conv

    async def _next_turn_index(self, conversation_id: str, session: AsyncSession) -> int:
        """Return the next turn_index for a conversation (max + 1, or 0 if empty)."""
        result = await session.execute(
            select(Query)
            .where(Query.conversation_id == conversation_id)
            .order_by(Query.turn_index.desc())  # type: ignore[attr-defined]
            .limit(1)
        )
        last = result.scalars().first()
        return (last.turn_index + 1) if last is not None else 0
```

- [ ] **Step 5: Update _query_llm to accept prior_turns**

In `src/wikimind/engine/qa_agent.py`, update the `_query_llm` method signature and prompt assembly. Replace the existing method with:

```python
    async def _query_llm(
        self,
        question: str,
        context: list[dict],
        prior_turns: list[Query],
        session: AsyncSession,
    ) -> QueryResult:
        """Build the LLM prompt (with optional conversation context) and call the router."""
        # Wiki context block (unchanged)
        context_text = "\n\n---\n\n".join([f"## {c['title']}\n\n{c['content']}" for c in context])

        # Conversation context block — only present when there are prior turns
        conv_block = ""
        if prior_turns:
            truncate_chars = self.settings.qa.prior_answer_truncate_chars
            conv_lines: list[str] = ["", "---", "", "Conversation so far:"]
            for prior in prior_turns:
                turn_n = prior.turn_index + 1
                truncated = prior.answer[:truncate_chars]
                conv_lines.append(f"Q{turn_n}: {prior.question}")
                conv_lines.append(f"A{turn_n}: {truncated}")
            conv_block = "\n".join(conv_lines)

        user_message = f"""Wiki context:

{context_text}{conv_block}

---

Current question: {question}

Answer based on the wiki context above. Use the conversation history
to disambiguate references like "it" or "that approach". If the
conversation context contradicts the wiki, prefer the wiki."""

        request_obj = CompletionRequest(
            system=QA_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            max_tokens=2048,
            temperature=0.3,
            response_format="json",
            task_type=TaskType.QA,
        )

        response = await self.router.complete(request_obj, session=session)

        try:
            data = self.router.parse_json_response(response)
            return QueryResult(**data)
        except Exception as e:
            log.error("Failed to parse QA response", error=str(e))
            return QueryResult(
                answer="Error processing answer. Please try again.",
                confidence="low",
                sources=[],
                related_articles=[],
            )
```

(Note: the existing `_query_llm` doesn't take a `prior_turns` arg. The above replaces the whole method. The system prompt `QA_SYSTEM_PROMPT` is unchanged — the conversation block goes in the user message, preserving the strict-JSON contract from ADR-007.)

- [ ] **Step 6: Add the Conversation import**

At the top of `src/wikimind/engine/qa_agent.py`, the existing import line for models:

```python
from wikimind.models import Article, CompletionRequest, ConfidenceLevel, Query, QueryRequest, QueryResult, TaskType
```

Update it to include `Conversation` and remove `ConfidenceLevel` (already removed by PR #85):

```python
from wikimind.models import Article, CompletionRequest, Conversation, Query, QueryRequest, QueryResult, TaskType
```

- [ ] **Step 7: Run the tests, verify they pass**

```bash
.venv/bin/pytest tests/unit/test_qa_agent.py::test_answer_creates_new_conversation_when_id_missing tests/unit/test_qa_agent.py::test_answer_appends_to_existing_conversation -v
```

Expected: PASS.

- [ ] **Step 8: Run the full unit test file to catch fallout**

```bash
.venv/bin/pytest tests/unit/test_qa_agent.py -v
```

Expected: existing tests may fail because they expected the old `answer()` return shape. Update them in the next task.

- [ ] **Step 9: Commit**

```bash
git add src/wikimind/engine/qa_agent.py tests/unit/test_qa_agent.py
git commit -m "feat(qa_agent): make answer() conversation-aware (ADR-011)"
```

## Task 1.8: Update existing QAAgent unit tests for the new return shape

**Files:**
- Modify: `tests/unit/test_qa_agent.py`

The existing tests in `test_qa_agent.py` expected `answer()` to return a single `Query`. Now it returns a tuple `(Query, Conversation)`. This task updates each existing test to unpack the tuple correctly. The test bodies otherwise stay the same.

- [ ] **Step 1: Identify the failing existing tests**

```bash
.venv/bin/pytest tests/unit/test_qa_agent.py -v 2>&1 | grep -E "FAIL|ERROR"
```

Note which tests fail. Likely candidates: `test_answer_with_context`, `test_answer_with_context_and_file_back`, `test_answer_no_context`, anything that calls `agent.answer(...)`.

- [ ] **Step 2: Update each failing test to unpack the tuple**

For each affected test, find the line that looks like:

```python
result = await agent.answer(req, session)
```

Replace with:

```python
result, _conversation = await agent.answer(req, session)
```

(The tests don't need to assert on the conversation; just unpacking it is enough to keep the original assertion logic working.)

If the test relies on `result.conversation_id` being NULL (legacy expectation), update it to assert `result.conversation_id is not None` instead, since every Query now belongs to a conversation.

- [ ] **Step 3: Run the file again, verify all tests pass**

```bash
.venv/bin/pytest tests/unit/test_qa_agent.py -v
```

Expected: all tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_qa_agent.py
git commit -m "test(qa_agent): update existing tests for (Query, Conversation) tuple return"
```

## Task 1.9: Replace per-Query file_back with thread file-back

**Files:**
- Modify: `src/wikimind/engine/qa_agent.py`
- Modify: `tests/unit/test_qa_agent.py`

The existing `_file_back(question, result, session)` is per-Query. Replace it with `_file_back_thread(conversation, queries, session)` that uses the serializer and respects `Conversation.filed_article_id` for create-vs-update.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_qa_agent.py`:

```python
async def test_file_back_thread_creates_article_when_first_save(test_session, tmp_path, monkeypatch):
    """First file-back creates a new Article and sets Conversation.filed_article_id."""
    from datetime import datetime

    from wikimind.config import get_settings
    from wikimind.engine.qa_agent import QAAgent
    from wikimind.models import Conversation, Query

    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()

    conv = Conversation(id="c1", title="What is X?", created_at=datetime.utcnow(), updated_at=datetime.utcnow())
    test_session.add(conv)
    test_session.add(Query(id="q1", question="What is X?", answer="X is Y.", confidence="high", conversation_id="c1", turn_index=0))
    await test_session.commit()

    agent = QAAgent()
    article, was_update = await agent._file_back_thread("c1", test_session)

    assert was_update is False
    assert article.id is not None

    # Conversation.filed_article_id is now set
    refreshed = await test_session.get(Conversation, "c1")
    assert refreshed.filed_article_id == article.id

    # The .md file exists on disk
    from pathlib import Path
    assert Path(article.file_path).exists()


async def test_file_back_thread_updates_in_place_on_second_save(test_session, tmp_path, monkeypatch):
    """Second file-back overwrites the existing Article in place and returns was_update=True."""
    from datetime import datetime

    from wikimind.config import get_settings
    from wikimind.engine.qa_agent import QAAgent
    from wikimind.models import Conversation, Query

    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()

    conv = Conversation(id="c2", title="What is Y?", created_at=datetime.utcnow(), updated_at=datetime.utcnow())
    test_session.add(conv)
    test_session.add(Query(id="q1", question="What is Y?", answer="Y is Z.", confidence="high", conversation_id="c2", turn_index=0))
    await test_session.commit()

    agent = QAAgent()
    first_article, _ = await agent._file_back_thread("c2", test_session)
    first_id = first_article.id
    first_path = first_article.file_path

    # Add another turn
    test_session.add(Query(id="q2", question="follow-up", answer="more.", confidence="high", conversation_id="c2", turn_index=1))
    await test_session.commit()

    second_article, was_update = await agent._file_back_thread("c2", test_session)

    assert was_update is True
    assert second_article.id == first_id  # same article
    assert second_article.file_path == first_path  # same file path

    # The file content now reflects both turns
    from pathlib import Path
    content = Path(first_path).read_text()
    assert "Q1: What is Y?" in content
    assert "Q2: follow-up" in content
```

- [ ] **Step 2: Run the tests, verify they fail**

```bash
.venv/bin/pytest tests/unit/test_qa_agent.py::test_file_back_thread_creates_article_when_first_save tests/unit/test_qa_agent.py::test_file_back_thread_updates_in_place_on_second_save -v
```

Expected: FAIL — the method doesn't exist.

- [ ] **Step 3: Replace _file_back with _file_back_thread**

In `src/wikimind/engine/qa_agent.py`, find the existing `_file_back` method (currently at the bottom of the class). DELETE the entire method. Replace it with:

```python
    async def _file_back_thread(
        self,
        conversation_id: str,
        session: AsyncSession,
    ) -> tuple[Article, bool]:
        """File a whole conversation back to the wiki as a single article.

        If the conversation has not been filed back before, creates a new
        Article. If it has, overwrites the existing Article's .md file in
        place and returns was_update=True. The article id, slug, and
        file_path stay stable across re-saves.

        See ADR-011 for the rationale on per-conversation (not per-turn)
        file-back.

        Args:
            conversation_id: The conversation to file back.
            session: Async database session.

        Returns:
            Tuple of (article, was_update). was_update is True when an
            existing article was overwritten.
        """
        from datetime import datetime

        from sqlmodel import select

        from wikimind.engine.conversation_serializer import serialize_conversation_to_markdown

        conversation = await session.get(Conversation, conversation_id)
        if conversation is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Conversation not found")

        # Load all turns ordered by turn_index
        result = await session.execute(
            select(Query)
            .where(Query.conversation_id == conversation_id)
            .order_by(Query.turn_index.asc())  # type: ignore[attr-defined]
        )
        queries = list(result.scalars().all())

        markdown = serialize_conversation_to_markdown(conversation, queries)

        if conversation.filed_article_id is None:
            # First save — create a new Article
            wiki_dir = Path(self.settings.data_dir) / "wiki" / "qa-answers"
            wiki_dir.mkdir(parents=True, exist_ok=True)

            slug = slugify(conversation.title)[:80]
            file_path = wiki_dir / f"{slug}.md"
            file_path.write_text(markdown, encoding="utf-8")

            article = Article(
                slug=slug,
                title=conversation.title,
                file_path=str(file_path),
                summary=(queries[0].answer[:200] if queries else None),
                confidence=None,  # per #84 / Option 2 — Q&A confidence is on Query, not Article
            )
            session.add(article)
            await session.flush()  # populate article.id

            conversation.filed_article_id = article.id
            conversation.updated_at = datetime.utcnow()
            session.add(conversation)
            await session.commit()
            await session.refresh(article)

            log.info("Conversation filed back to wiki (created)", conversation_id=conversation_id, article_id=article.id)
            return article, False

        # Second-or-later save — update in place
        article = await session.get(Article, conversation.filed_article_id)
        if article is None:
            # Defensive: filed_article_id pointed at a missing row. Treat as first save.
            log.warning("Conversation.filed_article_id pointed at missing Article — recreating", conversation_id=conversation_id)
            conversation.filed_article_id = None
            await session.commit()
            return await self._file_back_thread(conversation_id, session)

        Path(article.file_path).write_text(markdown, encoding="utf-8")
        article.updated_at = datetime.utcnow()
        conversation.updated_at = datetime.utcnow()
        session.add(article)
        session.add(conversation)
        await session.commit()
        await session.refresh(article)

        log.info("Conversation filed back to wiki (updated)", conversation_id=conversation_id, article_id=article.id)
        return article, True
```

- [ ] **Step 4: Run the tests, verify they pass**

```bash
.venv/bin/pytest tests/unit/test_qa_agent.py::test_file_back_thread_creates_article_when_first_save tests/unit/test_qa_agent.py::test_file_back_thread_updates_in_place_on_second_save -v
```

Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add src/wikimind/engine/qa_agent.py tests/unit/test_qa_agent.py
git commit -m "feat(qa_agent): replace per-Query file_back with thread file-back"
```

## Task 1.10: Update QueryService for the conversation-aware contract

**Files:**
- Modify: `src/wikimind/services/query.py`

This task updates the service layer to:
1. Accept `conversation_id` in `ask()` and return an `AskResponse`
2. Add `list_conversations()`, `get_conversation()`, `file_back_conversation()`
3. Delete the old per-Query `file_back()` method

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_services.py`:

```python
async def test_query_service_ask_returns_ask_response_with_conversation(test_session, mock_llm_router):
    """ask() now returns AskResponse with both query and conversation."""
    from wikimind.models import AskResponse, QueryRequest
    from wikimind.services.query import QueryService

    service = QueryService()
    request = QueryRequest(question="What is the loop?")

    response = await service.ask(request, test_session)

    assert isinstance(response, AskResponse)
    assert response.query.question == "What is the loop?"
    assert response.conversation.title == "What is the loop?"
    assert response.query.id is not None


async def test_query_service_list_conversations_orders_by_updated_at_desc(test_session):
    """list_conversations returns most-recently-updated first with turn_count populated."""
    from datetime import datetime, timedelta

    from wikimind.models import Conversation, Query
    from wikimind.services.query import QueryService

    now = datetime.utcnow()

    # Create three conversations with different updated_at and different turn counts
    test_session.add(Conversation(id="c1", title="oldest", created_at=now - timedelta(hours=3), updated_at=now - timedelta(hours=3)))
    test_session.add(Conversation(id="c2", title="newest", created_at=now - timedelta(hours=1), updated_at=now))
    test_session.add(Conversation(id="c3", title="middle", created_at=now - timedelta(hours=2), updated_at=now - timedelta(hours=1)))
    test_session.add(Query(id="q1", question="q", answer="a", conversation_id="c1", turn_index=0))
    test_session.add(Query(id="q2a", question="q", answer="a", conversation_id="c2", turn_index=0))
    test_session.add(Query(id="q2b", question="q", answer="a", conversation_id="c2", turn_index=1))
    test_session.add(Query(id="q3", question="q", answer="a", conversation_id="c3", turn_index=0))
    await test_session.commit()

    service = QueryService()
    summaries = await service.list_conversations(test_session, limit=10)

    assert [s.id for s in summaries] == ["c2", "c3", "c1"]
    assert summaries[0].turn_count == 2
    assert summaries[1].turn_count == 1
    assert summaries[2].turn_count == 1


async def test_query_service_get_conversation_returns_ordered_turns(test_session):
    """get_conversation returns the conversation plus its queries ordered by turn_index."""
    from datetime import datetime

    from wikimind.models import Conversation, Query
    from wikimind.services.query import QueryService

    test_session.add(Conversation(id="c1", title="t", created_at=datetime.utcnow(), updated_at=datetime.utcnow()))
    test_session.add(Query(id="q-late", question="late", answer="a", conversation_id="c1", turn_index=2))
    test_session.add(Query(id="q-early", question="early", answer="a", conversation_id="c1", turn_index=0))
    test_session.add(Query(id="q-mid", question="mid", answer="a", conversation_id="c1", turn_index=1))
    await test_session.commit()

    service = QueryService()
    detail = await service.get_conversation("c1", test_session)

    assert detail.conversation.id == "c1"
    assert [q.question for q in detail.queries] == ["early", "mid", "late"]
```

- [ ] **Step 2: Run the tests, verify they fail**

```bash
.venv/bin/pytest tests/unit/test_services.py -v -k "query_service"
```

Expected: FAIL — methods don't exist or return shapes don't match.

- [ ] **Step 3: Update the QueryService class**

In `src/wikimind/services/query.py`:

(a) Update the imports at the top:

```python
import json

import structlog
from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.engine.qa_agent import QAAgent
from wikimind.models import (
    Article,
    AskResponse,
    CitationArticleRef,
    CitationResponse,
    Conversation,
    ConversationDetail,
    ConversationResponse,
    ConversationSummary,
    Query,
    QueryRequest,
    QueryResponse,
    QueryResult,
    Source,
    SourceResponse,
)
```

(b) Replace the `ask()` method:

```python
    async def ask(self, request: QueryRequest, session: AsyncSession) -> AskResponse:
        """Ask a question against the wiki and persist the result.

        Conversation-aware: passes request.conversation_id to the agent.
        Returns both the new query (with full citation chain) and the
        parent conversation.
        """
        query, conversation = await self._qa_agent.answer(request, session)
        citations = await _build_citations(query, session)
        return AskResponse(
            query=_to_query_response(query, citations),
            conversation=_to_conversation_response(conversation),
        )
```

(c) Add the new service methods at the end of the class (after `query_history`):

```python
    async def list_conversations(
        self,
        session: AsyncSession,
        limit: int = 50,
    ) -> list[ConversationSummary]:
        """List conversations ordered by most-recently-updated first.

        Each summary includes turn_count for the sidebar UI.
        """
        result = await session.execute(
            select(Conversation)
            .order_by(Conversation.updated_at.desc())  # type: ignore[attr-defined]
            .limit(limit)
        )
        conversations = list(result.scalars().all())

        # Compute turn counts in one query
        if not conversations:
            return []
        ids = [c.id for c in conversations]
        count_rows = await session.execute(
            select(Query.conversation_id, Query.id)  # type: ignore[arg-type]
            .where(Query.conversation_id.in_(ids))  # type: ignore[attr-defined]
        )
        counts: dict[str, int] = {}
        for conv_id, _qid in count_rows.all():
            counts[conv_id] = counts.get(conv_id, 0) + 1

        return [
            ConversationSummary(
                id=c.id,
                title=c.title,
                created_at=c.created_at,
                updated_at=c.updated_at,
                filed_article_id=c.filed_article_id,
                turn_count=counts.get(c.id, 0),
            )
            for c in conversations
        ]

    async def get_conversation(
        self,
        conversation_id: str,
        session: AsyncSession,
    ) -> ConversationDetail:
        """Return a single conversation with all its queries ordered by turn_index."""
        conversation = await session.get(Conversation, conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

        result = await session.execute(
            select(Query)
            .where(Query.conversation_id == conversation_id)
            .order_by(Query.turn_index.asc())  # type: ignore[attr-defined]
        )
        queries = list(result.scalars().all())

        # Build full QueryResponse for each turn (with citations)
        query_responses: list[QueryResponse] = []
        for q in queries:
            citations = await _build_citations(q, session)
            query_responses.append(_to_query_response(q, citations))

        return ConversationDetail(
            conversation=_to_conversation_response(conversation),
            queries=query_responses,
        )

    async def file_back_conversation(
        self,
        conversation_id: str,
        session: AsyncSession,
    ) -> dict[str, object]:
        """File a whole conversation back to the wiki.

        Delegates to QAAgent._file_back_thread which handles create-vs-update
        based on Conversation.filed_article_id.
        """
        article, was_update = await self._qa_agent._file_back_thread(conversation_id, session)
        return {
            "article": {"id": article.id, "slug": article.slug, "title": article.title},
            "was_update": was_update,
        }
```

(d) DELETE the old `file_back(self, query_id, session)` method entirely.

(e) Add the helper at module level (after the existing `_to_query_response` function):

```python
def _to_conversation_response(conversation: Conversation) -> ConversationResponse:
    """Project a Conversation row into the API response shape."""
    return ConversationResponse(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        filed_article_id=conversation.filed_article_id,
    )
```

- [ ] **Step 4: Run the tests, verify they pass**

```bash
.venv/bin/pytest tests/unit/test_services.py -v -k "query_service or conversation"
```

Expected: PASS.

- [ ] **Step 5: Run the full services test file to catch fallout**

```bash
.venv/bin/pytest tests/unit/test_services.py -v
```

Expected: existing tests that called the old `file_back()` method may fail. Update them to use `file_back_conversation()` with a conversation_id, OR delete them if they're testing behavior that no longer exists. Use judgment per test.

- [ ] **Step 6: Commit**

```bash
git add src/wikimind/services/query.py tests/unit/test_services.py
git commit -m "feat(services): conversation-aware QueryService.ask + list/get/file_back conversations"
```

## Task 1.11: Update the routes layer

**Files:**
- Modify: `src/wikimind/api/routes/query.py`

The route file gains new endpoints and loses one. Per the spec, the deleted endpoint is `POST /query/{id}/file-back`.

- [ ] **Step 1: Replace the routes file**

Replace the entire contents of `src/wikimind/api/routes/query.py` with:

```python
"""Endpoints for asking questions, browsing conversations, and filing answers back."""

from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.database import get_session
from wikimind.models import (
    AskResponse,
    ConversationDetail,
    ConversationSummary,
    QueryRequest,
)
from wikimind.services.query import QueryService, get_query_service

router = APIRouter()


@router.post("", response_model=AskResponse)
async def ask(
    request: QueryRequest,
    session: AsyncSession = Depends(get_session),
    service: QueryService = Depends(get_query_service),
):
    """Ask a question against the wiki and receive an answer with citations.

    If request.conversation_id is None, a new conversation is created.
    Otherwise the question is appended as a new turn in the existing
    conversation.
    """
    return await service.ask(request, session)


@router.get("/history")
async def query_history(
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
    service: QueryService = Depends(get_query_service),
):
    """List past queries (legacy endpoint — UI uses /conversations instead)."""
    return await service.query_history(session, limit=limit)


@router.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations(
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
    service: QueryService = Depends(get_query_service),
):
    """List conversations ordered by most recently updated first."""
    return await service.list_conversations(session, limit=limit)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: str,
    session: AsyncSession = Depends(get_session),
    service: QueryService = Depends(get_query_service),
):
    """Return a single conversation with all its turns."""
    return await service.get_conversation(conversation_id, session)


@router.post("/conversations/{conversation_id}/file-back")
async def file_back_conversation(
    conversation_id: str,
    session: AsyncSession = Depends(get_session),
    service: QueryService = Depends(get_query_service),
):
    """File the entire conversation back to the wiki as a single article."""
    return await service.file_back_conversation(conversation_id, session)
```

Note: the spec says these conversation routes could live in a new `conversations.py` router OR in the existing `query.py` router. This task puts them in `query.py` (under the `/query` URL prefix) because the routes are conceptually about Q&A and the existing router prefix already exists. Routes are exposed as:

- `POST /query` (ask)
- `GET /query/history` (legacy list)
- `GET /query/conversations` (list conversations)
- `GET /query/conversations/{id}` (get one)
- `POST /query/conversations/{id}/file-back` (file back)

If you prefer URL-symmetry (e.g. `POST /conversations/{id}/file-back` directly under `/conversations`), create a new `src/wikimind/api/routes/conversations.py` router and register it in `main.py`. Either is acceptable per the spec — pick whichever feels cleaner during review.

- [ ] **Step 2: Run lint + typecheck**

```bash
.venv/bin/ruff check src/wikimind/api/routes/query.py
.venv/bin/mypy src/wikimind/api/routes/query.py
```

Expected: clean.

- [ ] **Step 3: Run the integration tests for the query routes**

```bash
.venv/bin/pytest tests/integration/test_qa_loop_integration.py -v
```

Expected: The existing test from PR #85 (`test_filed_back_conversation_compatible_with_pr85_path` or similar — whatever it's called) may fail because the route shape changed. We will fix the integration tests in Task 1.12. For now this is expected.

- [ ] **Step 4: Commit**

```bash
git add src/wikimind/api/routes/query.py
git commit -m "feat(routes): conversation-aware /query + new /query/conversations endpoints"
```

## Task 1.12: Update the existing integration test for the new contract

**Files:**
- Modify: `tests/integration/test_qa_loop_integration.py`

The existing test from PR #85 expected the old return shape and the old file-back endpoint. Update it for the new shape.

- [ ] **Step 1: Read the existing test**

```bash
cat tests/integration/test_qa_loop_integration.py
```

Note the existing test names and what they assert. The PR #85 test should be checking that filing back doesn't crash on the ConfidenceLevel enum.

- [ ] **Step 2: Update the existing test to use the new contract**

For the existing test, update assertions to:
1. Unpack the new tuple return shape from `agent.answer()` (`query, conversation = ...`)
2. Use `agent._file_back_thread(conversation.id, session)` instead of `agent._file_back(...)`
3. Assert the article exists, no exception raised, and `conversation.filed_article_id` is set

The test name and intent stay the same — only the calls change.

- [ ] **Step 3: Run the test, verify it passes**

```bash
.venv/bin/pytest tests/integration/test_qa_loop_integration.py -v
```

Expected: existing test PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_qa_loop_integration.py
git commit -m "test(integration): update PR #85 test for new conversation-aware contract"
```

## Task 1.13: Add the multi-turn context integration test

**Files:**
- Modify: `tests/integration/test_qa_loop_integration.py`

Add the test that proves prior turns end up in the LLM prompt.

- [ ] **Step 1: Add the test**

Append to `tests/integration/test_qa_loop_integration.py`:

```python
async def test_multi_turn_conversation_includes_prior_context_in_prompt(test_session, monkeypatch):
    """Q1 establishes context. Q2 in the same conversation must include Q1 in the LLM prompt."""
    from unittest.mock import AsyncMock

    from wikimind.engine.qa_agent import QAAgent
    from wikimind.models import QueryRequest

    # Mock the LLM router to capture the request and return a canned response
    captured_requests: list = []

    async def fake_complete(request, session):
        captured_requests.append(request)
        return '{"answer": "fake answer", "confidence": "high", "sources": [], "related_articles": [], "follow_up_questions": []}'

    agent = QAAgent()
    agent.router.complete = AsyncMock(side_effect=fake_complete)
    agent.router.parse_json_response = lambda r: {
        "answer": "fake answer",
        "confidence": "high",
        "sources": [],
        "related_articles": [],
        "follow_up_questions": [],
    }

    # Seed at least one Article so retrieval finds something
    from wikimind.models import Article
    test_session.add(
        Article(
            id="art-1",
            slug="seed",
            title="Seed Article",
            file_path="/dev/null",
            summary="seed",
        )
    )
    await test_session.commit()

    # Stub _retrieve_context to avoid filesystem reads
    agent._retrieve_context = AsyncMock(return_value=[{"title": "Seed Article", "content": "seed content", "score": 1}])

    # Q1
    q1, conv = await agent.answer(QueryRequest(question="What is X?"), test_session)

    # Q2 in the same conversation
    q2, _ = await agent.answer(
        QueryRequest(question="How does it work?", conversation_id=conv.id),
        test_session,
    )

    # Two LLM calls captured
    assert len(captured_requests) == 2

    # The second call's user message must include the Q1 + A1 context block
    second_msg = captured_requests[1].messages[0]["content"]
    assert "Conversation so far:" in second_msg
    assert "Q1: What is X?" in second_msg
    assert "A1: fake answer" in second_msg
    assert "Current question: How does it work?" in second_msg
```

- [ ] **Step 2: Run the test, verify it passes**

```bash
.venv/bin/pytest tests/integration/test_qa_loop_integration.py::test_multi_turn_conversation_includes_prior_context_in_prompt -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_qa_loop_integration.py
git commit -m "test(integration): add multi-turn conversation context test"
```

## Task 1.14: Add the loop closure integration test (the headline test)

**Files:**
- Modify: `tests/integration/test_qa_loop_integration.py`

This is **the most important test in the entire spec.** It proves that filed-back conversations are retrievable by future questions — that the Karpathy loop actually closes.

- [ ] **Step 1: Add the test**

Append to `tests/integration/test_qa_loop_integration.py`:

```python
async def test_filed_back_conversation_is_retrievable_by_next_query(test_session, tmp_path, monkeypatch):
    """The Karpathy loop closure test.

    1. Seed a fixture Article into the wiki.
    2. Conversation A: ask a question that retrieves the fixture article.
       File back the conversation.
    3. Conversation B (new): ask a different question that should retrieve
       the article filed back from Conversation A.
    4. Assert: Conversation B's retrieval finds the filed-back article.

    If this test ever fails, the loop is broken — that is the entire
    point of WikiMind.
    """
    from datetime import datetime
    from pathlib import Path
    from unittest.mock import AsyncMock

    from wikimind.config import get_settings
    from wikimind.engine.qa_agent import QAAgent
    from wikimind.models import Article, QueryRequest

    monkeypatch.setenv("WIKIMIND_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()

    # Seed a fixture article on disk so retrieval has something real to find
    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    fixture_path = wiki_dir / "fixture-source.md"
    fixture_path.write_text(
        "# Fixture Source\n\nThe Karpathy loop is the core mechanism of WikiMind. It compounds explorations into the wiki.\n",
        encoding="utf-8",
    )
    test_session.add(
        Article(
            id="art-fixture",
            slug="fixture-source",
            title="Fixture Source",
            file_path=str(fixture_path),
            summary="A fixture article for the loop closure test.",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
    )
    await test_session.commit()

    # Mock the LLM router to return canned answers that cite by title
    canned_responses = iter(
        [
            {
                "answer": "The Karpathy loop is documented in [[Fixture Source]]. It compounds explorations.",
                "confidence": "high",
                "sources": ["Fixture Source"],
                "related_articles": [],
                "follow_up_questions": [],
            },
            {
                "answer": "Per [[How does the Karpathy loop work?]], the loop compounds explorations.",
                "confidence": "high",
                "sources": ["How does the Karpathy loop work?"],
                "related_articles": [],
                "follow_up_questions": [],
            },
        ]
    )

    agent = QAAgent()
    agent.router.complete = AsyncMock(return_value="ignored — parse_json_response is stubbed")
    agent.router.parse_json_response = lambda r: next(canned_responses)

    # Phase 1: Conversation A asks the question, file it back
    q_a, conv_a = await agent.answer(
        QueryRequest(question="How does the Karpathy loop work?"),
        test_session,
    )
    article_a, was_update = await agent._file_back_thread(conv_a.id, test_session)
    assert was_update is False
    filed_article_id = article_a.id

    # The filed-back article must now be in the Article table and on disk
    filed_article = await test_session.get(Article, filed_article_id)
    assert filed_article is not None
    assert Path(filed_article.file_path).exists()

    # Phase 2: Conversation B asks a related question.
    # Retrieval is naive token-overlap, so the question must share words
    # with the filed-back article's content. The filed-back article's
    # title is "How does the Karpathy loop work?" — so a question about
    # "Karpathy loop" should find it.
    q_b, conv_b = await agent.answer(
        QueryRequest(question="Tell me about the Karpathy loop"),
        test_session,
    )

    # Phase 3: Verify the filed-back article was retrievable.
    # We can't directly assert on what _retrieve_context returned (it's
    # an internal call), but we CAN assert that the filed-back article
    # is in the Article table and that running retrieval over the wiki
    # would find it. Use the agent's own retrieval helper.
    retrieved = await agent._retrieve_context("Tell me about the Karpathy loop", test_session)
    retrieved_titles = {r["title"] for r in retrieved}

    assert "How does the Karpathy loop work?" in retrieved_titles, (
        f"LOOP CLOSURE FAILED: filed-back article was not found by a related "
        f"future question. Retrieved: {retrieved_titles}"
    )
```

- [ ] **Step 2: Run the test, verify it passes**

```bash
.venv/bin/pytest tests/integration/test_qa_loop_integration.py::test_filed_back_conversation_is_retrievable_by_next_query -v
```

Expected: PASS.

If this test fails, the loop is broken. Common failure modes:
- The filed-back article's `file_path` doesn't get a real markdown file written
- `_retrieve_context()` reads from `Article.file_path` and the file doesn't exist
- The slugify of the title doesn't match the search heuristic

Fix the underlying issue — do NOT weaken the test.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_qa_loop_integration.py
git commit -m "test(integration): add Karpathy loop closure test (headline)"
```

## Task 1.15: Update .env.example with new QA settings

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Add the new env var entries**

Open `.env.example`. Find the section that documents the LLM/server config. Add a new section:

```
# Q&A agent — multi-turn conversation tunables (ADR-011)
WIKIMIND_QA__MAX_PRIOR_TURNS_IN_CONTEXT=5
WIKIMIND_QA__PRIOR_ANSWER_TRUNCATE_CHARS=500
WIKIMIND_QA__CONVERSATION_TITLE_MAX_CHARS=120
```

The double underscore (`__`) is the Pydantic Settings nested delimiter — `WIKIMIND_QA__MAX_PRIOR_TURNS_IN_CONTEXT` maps to `settings.qa.max_prior_turns_in_context`.

- [ ] **Step 2: Commit**

```bash
git add .env.example
git commit -m "docs(env): document new WIKIMIND_QA__* settings"
```

## Task 1.16: Run make verify and address any fallout

**Files:** any

- [ ] **Step 1: Run the full verify**

```bash
make verify
```

- [ ] **Step 2: Address any failures**

Common issues:
- Coverage drop below 80% → add tests to whichever module dropped, not by lowering the floor
- Mypy complaints about new types → add type annotations; do NOT use `# type: ignore` unless the existing code already does for the same construct
- Ruff lint complaints → fix the violation; do NOT add a noqa unless absolutely necessary
- Doc-sync auto-gen check failing → run `make export-openapi` to regenerate `docs/openapi.yaml`, then commit the regenerated file
- Doc-sync co-change check failing → the rule engine wants you to update a doc that you forgot. Read the error message and fix it.

Iterate until `make verify` is fully green.

- [ ] **Step 3: Commit any auto-generated changes**

```bash
git add docs/openapi.yaml
git commit -m "docs(openapi): regenerate for /query/conversations endpoints"
```

(Only commit if the file actually changed.)

## Task 1.17: Push and open PR 1

**Files:** any

- [ ] **Step 1: Push the branch**

```bash
git push -u origin claude/ask-slice-pr1-backend
```

- [ ] **Step 2: Open the PR**

```bash
gh pr create --title "feat(qa): conversational Q&A backend (ADR-011) — PR 1 of 3" --body "$(cat <<'EOF'
## Summary

PR 1 of 3 implementing the Ask vertical slice spec
(`docs/superpowers/specs/2026-04-08-ask-vertical-slice-design.md`)
and ADR-011. This is the **backend** half — data model, agent
changes, routes, and the Karpathy loop closure integration test.
The frontend (PR 2) and Playwright e2e (PR 3) follow.

### What this PR does

- Adds `Conversation` SQLModel + `query.conversation_id` / `query.turn_index` columns
- Extends `database.py:_migrate_added_columns` for the new columns and adds an idempotent backfill helper for legacy `Query` rows
- Adds three `WIKIMIND_QA__*` settings (max_prior_turns_in_context, prior_answer_truncate_chars, conversation_title_max_chars) — no magic numbers
- Conversation-aware `QAAgent.answer()` returning `(Query, Conversation)` with prior turns in the prompt
- Per-conversation file-back via `_file_back_thread()` that creates-or-updates an Article based on `Conversation.filed_article_id`
- New routes: `GET /query/conversations`, `GET /query/conversations/{id}`, `POST /query/conversations/{id}/file-back`
- Removed: `POST /query/{id}/file-back` (replaced by the conversation-level endpoint)
- The headline integration test `test_filed_back_conversation_is_retrievable_by_next_query` proves the Karpathy loop closes

### What this PR does NOT do

- No frontend changes (PR 2)
- No Playwright e2e (PR 3)
- No streaming (#88), no editing/branching (#89), no partial-thread file-back (#90), no export (#91), no embeddings (#20)

### Breaking changes

`POST /query/{id}/file-back` is removed. The frontend `apps/web/src/api/query.ts` still references it as a typed function — that's fine because no UI consumes it yet, and PR 2 will rewrite that file.

## Test plan

- [ ] CI green (lint, mypy, pytest, coverage ≥ 80%, doc-sync)
- [ ] `tests/integration/test_qa_loop_integration.py::test_filed_back_conversation_is_retrievable_by_next_query` passes
- [ ] `tests/integration/test_qa_loop_integration.py::test_multi_turn_conversation_includes_prior_context_in_prompt` passes
- [ ] Manual test: hit `POST /query` with a question; `POST /query` again with the returned conversation_id; `POST /query/conversations/{id}/file-back`; `GET /wiki/articles/<slug>` returns the filed-back markdown
EOF
)"
```

- [ ] **Step 3: Verify CI starts and watch it complete**

```bash
gh pr view --web
```

Watch the PR until all checks are green. If a check fails, fix it and push again.

---

# PR 2 — Frontend

**Branch:** `claude/ask-slice-pr2-frontend`

**Definition of done for PR 2:** All frontend tasks below complete. `apps/web` `lint`, `typecheck`, and `build` all green. A manual smoke test through the dev server (started via `make dev` for the backend and `cd apps/web && npm run dev` for the frontend) confirms the user can ask a question, see an answer, ask a follow-up, and save the thread. PR 2 depends on PR 1 being merged.

**Important:** Per the spec, this PR ships **without component-level unit tests**. The frontend has no test infrastructure today, and introducing it is a project-level decision the user has declined. Behavioral coverage comes from PR 3's Playwright test.

## Task 2.1: Create the new branch from main (after PR 1 merged)

**Files:** none

- [ ] **Step 1: Verify PR 1 is merged**

```bash
gh pr view <PR1-number> --json state
```

Expected: `"state":"MERGED"`. If not merged, wait.

- [ ] **Step 2: Pull and branch**

```bash
git checkout main
git pull --ff-only origin main
git checkout -b claude/ask-slice-pr2-frontend
```

## Task 2.2: Update the API client with new types and methods

**Files:**
- Modify: `apps/web/src/api/query.ts`

- [ ] **Step 1: Replace the file with the new contract**

Replace the entire contents of `apps/web/src/api/query.ts` with:

```typescript
// Endpoints in src/wikimind/api/routes/query.py.

import { apiFetch } from "./client";

// ----- Types -----

export interface AskRequest {
  question: string;
  conversation_id?: string;
  file_back?: boolean; // deprecated; ignored by new conversation-aware backend
}

export interface QueryRecord {
  id: string;
  question: string;
  answer: string;
  confidence: string | null;
  source_article_ids: string | null;
  related_article_ids: string | null;
  filed_back: boolean;
  filed_article_id: string | null;
  created_at: string;
  conversation_id: string | null;
  turn_index: number;
}

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  filed_article_id: string | null;
}

export interface ConversationSummary extends Conversation {
  turn_count: number;
}

export interface ConversationDetail {
  conversation: Conversation;
  queries: QueryRecord[];
}

export interface AskResponse {
  query: QueryRecord;
  conversation: Conversation;
}

export interface FileBackResponse {
  article: { id: string; slug: string; title: string };
  was_update: boolean;
}

// ----- Functions -----

export function askQuestion(req: AskRequest): Promise<AskResponse> {
  return apiFetch<AskResponse>("/query", { method: "POST", body: req });
}

export function queryHistory(limit = 50): Promise<QueryRecord[]> {
  return apiFetch<QueryRecord[]>("/query/history", { query: { limit } });
}

export function listConversations(limit = 50): Promise<ConversationSummary[]> {
  return apiFetch<ConversationSummary[]>("/query/conversations", { query: { limit } });
}

export function getConversation(id: string): Promise<ConversationDetail> {
  return apiFetch<ConversationDetail>(`/query/conversations/${id}`);
}

export function fileBackConversation(id: string): Promise<FileBackResponse> {
  return apiFetch<FileBackResponse>(`/query/conversations/${id}/file-back`, { method: "POST" });
}
```

- [ ] **Step 2: Run typecheck**

```bash
cd apps/web && npm run typecheck
```

Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add apps/web/src/api/query.ts
git commit -m "feat(web): conversation-aware query API client"
```

## Task 2.3: Add /ask routes to App.tsx

**Files:**
- Modify: `apps/web/src/App.tsx`

- [ ] **Step 1: Update the routes**

Replace the contents of `apps/web/src/App.tsx` with:

```tsx
import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/shared/Layout";
import { InboxView } from "./components/inbox/InboxView";
import { WikiExplorerView } from "./components/wiki/WikiExplorerView";
import { AskView } from "./components/ask/AskView";
import { useWebSocket } from "./hooks/useWebSocket";

export function App() {
  // Open the gateway WebSocket exactly once for the whole app.
  useWebSocket();

  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Navigate to="/inbox" replace />} />
        <Route path="/inbox" element={<InboxView />} />
        <Route path="/ask" element={<AskView />} />
        <Route path="/ask/:conversationId" element={<AskView />} />
        <Route path="/wiki" element={<WikiExplorerView />} />
        <Route path="/wiki/:slug" element={<WikiExplorerView />} />
        <Route path="*" element={<Navigate to="/inbox" replace />} />
      </Routes>
    </Layout>
  );
}
```

- [ ] **Step 2: Add the Ask nav link to Layout.tsx**

In `apps/web/src/components/shared/Layout.tsx`, find where the existing nav links for "Inbox" and "Wiki" are defined. Add a third link "Ask" between them. The exact JSX depends on the existing Layout structure — match its style. For example, if the existing nav uses `react-router-dom`'s `<NavLink>`:

```tsx
<NavLink to="/inbox" className={navLinkClass}>Inbox</NavLink>
<NavLink to="/ask" className={navLinkClass}>Ask</NavLink>
<NavLink to="/wiki" className={navLinkClass}>Wiki</NavLink>
```

(Read the existing file first to match the precise pattern.)

- [ ] **Step 3: Commit (will fail typecheck because AskView doesn't exist yet — that's OK, the next task creates it)**

```bash
git add apps/web/src/App.tsx apps/web/src/components/shared/Layout.tsx
git commit -m "feat(web): add /ask routes and nav link"
```

(If pre-commit hooks block this commit because the typecheck fails, you can either skip pre-commit just for this commit OR build the AskView first and combine both into one commit. Prefer the second — combine with Task 2.4.)

## Task 2.4: Create the AskView page container

**Files:**
- Create: `apps/web/src/components/ask/AskView.tsx`

- [ ] **Step 1: Write the component**

Create `apps/web/src/components/ask/AskView.tsx`:

```tsx
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  askQuestion,
  getConversation,
  listConversations,
  fileBackConversation,
  type AskRequest,
} from "../../api/query";
import { ConversationHistory } from "./ConversationHistory";
import { ConversationThread } from "./ConversationThread";
import { QueryInput } from "./QueryInput";

export function AskView() {
  const { conversationId } = useParams<{ conversationId?: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [pendingError, setPendingError] = useState<string | null>(null);

  // Load the current conversation's full thread (only if we have an id)
  const conversationDetail = useQuery({
    queryKey: ["conversation", conversationId],
    queryFn: () => getConversation(conversationId!),
    enabled: !!conversationId,
  });

  // Sidebar
  const conversations = useQuery({
    queryKey: ["conversations"],
    queryFn: () => listConversations(50),
  });

  // Ask mutation — appends a turn to the current conversation, or starts a new one
  const ask = useMutation({
    mutationFn: (req: AskRequest) => askQuestion(req),
    onSuccess: (response) => {
      setPendingError(null);
      const newId = response.conversation.id;
      // If we were on /ask (no id), navigate to /ask/:newId
      if (!conversationId) {
        navigate(`/ask/${newId}`, { replace: true });
      }
      queryClient.invalidateQueries({ queryKey: ["conversation", newId] });
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
    onError: (err: Error) => {
      setPendingError(err.message || "Failed to ask question");
    },
  });

  // File-back mutation
  const fileBack = useMutation({
    mutationFn: (id: string) => fileBackConversation(id),
    onSuccess: (response) => {
      queryClient.invalidateQueries({ queryKey: ["conversation", conversationId] });
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      // Toast: would normally use a toast lib, but for now just alert.
      // TODO upstream: integrate with whatever toast library the rest of the app uses.
      const verb = response.was_update ? "Updated" : "Saved to";
      window.alert(`${verb} wiki article: ${response.article.title}`);
    },
  });

  const handleSubmit = (question: string) => {
    ask.mutate({ question, conversation_id: conversationId });
  };

  const handleSave = () => {
    if (conversationId) fileBack.mutate(conversationId);
  };

  return (
    <div className="flex h-full">
      <aside className="w-64 border-r border-slate-200 overflow-y-auto">
        <ConversationHistory
          conversations={conversations.data ?? []}
          activeId={conversationId}
        />
      </aside>
      <main className="flex-1 flex flex-col overflow-hidden">
        <div className="flex-1 overflow-y-auto p-6">
          <ConversationThread
            detail={conversationDetail.data}
            isLoading={conversationDetail.isLoading || ask.isPending}
            onSave={handleSave}
            isSaving={fileBack.isPending}
          />
          {pendingError && (
            <div className="mt-4 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-700">
              {pendingError}
            </div>
          )}
        </div>
        <div className="border-t border-slate-200 p-4">
          <QueryInput onSubmit={handleSubmit} disabled={ask.isPending} />
        </div>
      </main>
    </div>
  );
}
```

(Note on the `window.alert` for the toast: the spec says "toast with link." If the project has an existing toast library (check `apps/web/package.json` and `apps/web/src/components/shared/`), use it instead. If not, a `window.alert` is acceptable for the first pass — file a follow-up issue to add proper toasts.)

- [ ] **Step 2: Commit**

```bash
git add apps/web/src/components/ask/AskView.tsx
git commit -m "feat(web): add AskView page container"
```

## Task 2.5: Create the ConversationHistory sidebar

**Files:**
- Create: `apps/web/src/components/ask/ConversationHistory.tsx`

- [ ] **Step 1: Write the component**

Create `apps/web/src/components/ask/ConversationHistory.tsx`:

```tsx
import { Link } from "react-router-dom";
import type { ConversationSummary } from "../../api/query";

interface Props {
  conversations: ConversationSummary[];
  activeId?: string;
}

export function ConversationHistory({ conversations, activeId }: Props) {
  return (
    <div className="p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Conversations
        </h2>
        <Link
          to="/ask"
          className="text-xs font-medium text-blue-600 hover:underline"
        >
          + New
        </Link>
      </div>
      {conversations.length === 0 ? (
        <p className="text-xs text-slate-400">No conversations yet.</p>
      ) : (
        <ul className="space-y-1">
          {conversations.map((c) => (
            <li key={c.id}>
              <Link
                to={`/ask/${c.id}`}
                className={`block rounded px-2 py-2 text-sm hover:bg-slate-100 ${
                  c.id === activeId ? "bg-slate-100 font-medium" : ""
                }`}
              >
                <div className="truncate">{c.title}</div>
                <div className="mt-0.5 flex items-center gap-2 text-xs text-slate-400">
                  <span>{relativeTime(c.updated_at)}</span>
                  <span>•</span>
                  <span>{c.turn_count} turn{c.turn_count === 1 ? "" : "s"}</span>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const now = Date.now();
  const seconds = Math.round((now - then) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}
```

- [ ] **Step 2: Commit**

```bash
git add apps/web/src/components/ask/ConversationHistory.tsx
git commit -m "feat(web): add ConversationHistory sidebar"
```

## Task 2.6: Create the ConversationThread component

**Files:**
- Create: `apps/web/src/components/ask/ConversationThread.tsx`

- [ ] **Step 1: Write the component**

Create `apps/web/src/components/ask/ConversationThread.tsx`:

```tsx
import type { ConversationDetail } from "../../api/query";
import { TurnCard } from "./TurnCard";
import { SaveThreadButton } from "./SaveThreadButton";

interface Props {
  detail: ConversationDetail | undefined;
  isLoading: boolean;
  onSave: () => void;
  isSaving: boolean;
}

export function ConversationThread({ detail, isLoading, onSave, isSaving }: Props) {
  if (!detail) {
    return (
      <div className="text-slate-400">
        {isLoading ? "Loading…" : "Ask a question to start a new conversation."}
      </div>
    );
  }

  const { conversation, queries } = detail;
  const isFiledBack = !!conversation.filed_article_id;

  return (
    <div className="space-y-6">
      {queries.map((q) => (
        <TurnCard key={q.id} query={q} />
      ))}
      {isLoading && (
        <div className="text-sm text-slate-400">Thinking…</div>
      )}
      {queries.length > 0 && !isLoading && (
        <div className="pt-4">
          <SaveThreadButton
            isFiledBack={isFiledBack}
            isSaving={isSaving}
            onClick={onSave}
          />
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add apps/web/src/components/ask/ConversationThread.tsx
git commit -m "feat(web): add ConversationThread component"
```

## Task 2.7: Create the TurnCard component with expand/collapse

**Files:**
- Create: `apps/web/src/components/ask/TurnCard.tsx`

This is the component the user explicitly asked for during brainstorming. It must support expand/collapse for long answers.

- [ ] **Step 1: Write the component**

Create `apps/web/src/components/ask/TurnCard.tsx`:

```tsx
import { useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { QueryRecord } from "../../api/query";

const COLLAPSE_THRESHOLD_CHARS = 800;

interface Props {
  query: QueryRecord;
}

export function TurnCard({ query }: Props) {
  const sources = useMemo(() => parseSources(query.source_article_ids), [query.source_article_ids]);
  const isLong = query.answer.length > COLLAPSE_THRESHOLD_CHARS;
  const [expanded, setExpanded] = useState(!isLong);

  const displayed = expanded ? query.answer : truncateOnParagraphBoundary(query.answer, COLLAPSE_THRESHOLD_CHARS);

  return (
    <article className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <header className="mb-3">
        <div className="text-xs font-medium uppercase tracking-wide text-slate-400">
          Q{query.turn_index + 1}
        </div>
        <h3 className="mt-1 text-base font-semibold text-slate-900">{query.question}</h3>
      </header>

      <div className="prose prose-sm max-w-none text-slate-700">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{displayed}</ReactMarkdown>
      </div>

      {isLong && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="mt-2 text-sm font-medium text-blue-600 hover:underline"
        >
          {expanded ? "Show less" : "Show more"}
        </button>
      )}

      {sources.length > 0 && (
        <footer className="mt-4 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-400">
            Sources:
          </span>
          {sources.map((s) => (
            <a
              key={s}
              href={`/wiki/${slugify(s)}`}
              className="rounded-full bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700 hover:bg-blue-100"
            >
              {s}
            </a>
          ))}
        </footer>
      )}

      {query.confidence && (
        <div className="mt-2 text-xs text-slate-400">
          Confidence: <span className="font-medium text-slate-600">{query.confidence}</span>
        </div>
      )}
    </article>
  );
}

function parseSources(raw: string | null): string[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function truncateOnParagraphBoundary(text: string, max: number): string {
  if (text.length <= max) return text;
  // Find the last \n\n before max
  const slice = text.slice(0, max);
  const lastBreak = slice.lastIndexOf("\n\n");
  if (lastBreak > max * 0.5) {
    return slice.slice(0, lastBreak) + "\n\n…";
  }
  // Fall back to nearest sentence end
  const lastDot = slice.lastIndexOf(". ");
  if (lastDot > max * 0.5) {
    return slice.slice(0, lastDot + 1) + " …";
  }
  return slice + "…";
}

function slugify(title: string): string {
  return title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
}
```

- [ ] **Step 2: Commit**

```bash
git add apps/web/src/components/ask/TurnCard.tsx
git commit -m "feat(web): add TurnCard with expand/collapse for long answers"
```

## Task 2.8: Create the QueryInput component

**Files:**
- Create: `apps/web/src/components/ask/QueryInput.tsx`

- [ ] **Step 1: Write the component**

Create `apps/web/src/components/ask/QueryInput.tsx`:

```tsx
import { useEffect, useRef, useState } from "react";

interface Props {
  onSubmit: (question: string) => void;
  disabled: boolean;
}

export function QueryInput({ onSubmit, disabled }: Props) {
  const [value, setValue] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  // Autofocus on mount and after every successful submit
  useEffect(() => {
    if (!disabled && ref.current) {
      ref.current.focus();
    }
  }, [disabled]);

  const handleSubmit = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSubmit(trimmed);
    setValue("");
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="flex items-end gap-2">
      <textarea
        ref={ref}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        rows={2}
        placeholder="Ask a question about your wiki…"
        className="flex-1 resize-none rounded-lg border border-slate-300 px-4 py-3 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:bg-slate-100 disabled:text-slate-400"
      />
      <button
        type="button"
        onClick={handleSubmit}
        disabled={disabled || !value.trim()}
        className="rounded-lg bg-blue-600 px-4 py-3 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-slate-300"
      >
        Ask
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add apps/web/src/components/ask/QueryInput.tsx
git commit -m "feat(web): add QueryInput component"
```

## Task 2.9: Create the SaveThreadButton component

**Files:**
- Create: `apps/web/src/components/ask/SaveThreadButton.tsx`

- [ ] **Step 1: Write the component**

Create `apps/web/src/components/ask/SaveThreadButton.tsx`:

```tsx
interface Props {
  isFiledBack: boolean;
  isSaving: boolean;
  onClick: () => void;
}

export function SaveThreadButton({ isFiledBack, isSaving, onClick }: Props) {
  const label = isSaving
    ? isFiledBack
      ? "Updating…"
      : "Saving…"
    : isFiledBack
      ? "Update wiki article"
      : "Save thread to wiki";

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={isSaving}
      className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
    >
      {label}
    </button>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add apps/web/src/components/ask/SaveThreadButton.tsx
git commit -m "feat(web): add SaveThreadButton with create/update state"
```

## Task 2.10: Run frontend lint, typecheck, build

**Files:** any

- [ ] **Step 1: Lint**

```bash
cd apps/web && npm run lint
```

Expected: no errors. Fix any issues.

- [ ] **Step 2: Typecheck**

```bash
cd apps/web && npm run typecheck
```

Expected: clean.

- [ ] **Step 3: Build**

```bash
cd apps/web && npm run build
```

Expected: build succeeds with no errors.

- [ ] **Step 4: Manual smoke test**

In one terminal, start the backend:

```bash
make dev
```

In another terminal, start the frontend dev server:

```bash
cd apps/web && npm run dev
```

Open `http://localhost:5173` in the browser. Verify:
- "Ask" link appears in the nav
- Clicking it loads `/ask` with an empty thread and a sidebar
- Type a question, press Enter — answer appears
- Type a follow-up — appears below
- Click "Save thread to wiki" — toast/alert confirms
- Sidebar updates with the new conversation

If any of these steps fail, fix the underlying issue.

- [ ] **Step 5: Update README Phase 2 checklist**

In the project root `README.md`, find the Phase 2 checklist (section labeled Phase 2 in the roadmap). Update:

```
- [ ] Q&A Agent — complete implementation
```

to:

```
- [x] Q&A Agent — conversational implementation (ADR-011)
```

If there's also an "Ask UI" item:

```
- [x] React UI: Ask view
```

Stage and commit:

```bash
git add README.md
git commit -m "docs(readme): mark Q&A and Ask UI as shipped (Phase 2)"
```

## Task 2.11: Push and open PR 2

- [ ] **Step 1: Push**

```bash
git push -u origin claude/ask-slice-pr2-frontend
```

- [ ] **Step 2: Open PR**

```bash
gh pr create --title "feat(web): conversational Ask UI — PR 2 of 3" --body "$(cat <<'EOF'
## Summary

PR 2 of 3 implementing the Ask vertical slice. Adds the **frontend** half — `/ask` route, conversation thread UI, history sidebar, save-to-wiki button, expand/collapse for long answers.

Depends on PR 1 (backend) being merged.

### What this PR does

- New `/ask` and `/ask/:conversationId` routes
- Six new components in `apps/web/src/components/ask/`:
  - `AskView` — page container
  - `ConversationHistory` — sidebar
  - `ConversationThread` — turn list
  - `TurnCard` — single Q+A with expand/collapse for long answers
  - `QueryInput` — submit on Enter
  - `SaveThreadButton` — file-back trigger with create/update state
- Updated `apps/web/src/api/query.ts` with new types and methods
- New "Ask" nav link between Inbox and Wiki
- README Phase 2 checklist updated

### Testing approach

Per the spec, this PR ships **without component-level unit tests** because the frontend has no test infrastructure today. CI runs lint + typecheck + build. Behavioral coverage comes from PR 3's Playwright e2e test.

Manual smoke test confirmed: ask question → see answer → follow-up → save thread → article appears in Wiki Explorer.

## Test plan

- [ ] CI green (lint, typecheck, build)
- [ ] Manual smoke test through dev server reproduces the loop
- [ ] PR 3 (Playwright) provides behavioral coverage
EOF
)"
```

---

# PR 3 — Playwright e2e

**Branch:** `claude/ask-slice-pr3-e2e`

**Definition of done for PR 3:** Playwright is installed in `apps/web`, a single end-to-end test in `apps/web/tests/e2e/ask-loop.spec.ts` drives the actual UI through the full loop, the test passes locally, and CI runs it as part of the frontend checks.

## Task 3.1: Install Playwright in apps/web

**Files:**
- Modify: `apps/web/package.json`
- Create: `apps/web/playwright.config.ts`

- [ ] **Step 1: Branch from main**

```bash
git checkout main
git pull --ff-only origin main
git checkout -b claude/ask-slice-pr3-e2e
```

- [ ] **Step 2: Install Playwright**

```bash
cd apps/web
npm install -D @playwright/test
npx playwright install --with-deps chromium
```

- [ ] **Step 3: Create playwright.config.ts**

Create `apps/web/playwright.config.ts`:

```typescript
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: "line",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5173",
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command: "npm run dev",
    url: "http://localhost:5173",
    reuseExistingServer: !process.env.CI,
    stdout: "pipe",
    stderr: "pipe",
  },
});
```

- [ ] **Step 4: Add an e2e script to package.json**

In `apps/web/package.json`, add a new script:

```json
"e2e": "playwright test"
```

- [ ] **Step 5: Commit**

```bash
git add apps/web/package.json apps/web/package-lock.json apps/web/playwright.config.ts
git commit -m "chore(web): install Playwright + base config"
```

## Task 3.2: Write the Ask loop e2e test

**Files:**
- Create: `apps/web/tests/e2e/ask-loop.spec.ts`

- [ ] **Step 1: Write the test**

Create `apps/web/tests/e2e/ask-loop.spec.ts`:

```typescript
import { test, expect } from "@playwright/test";

/**
 * The Karpathy loop closure test, end-to-end through the actual UI.
 *
 * Prerequisites:
 *   - The FastAPI backend must be running on http://localhost:7842
 *     with at least one Article seeded into the wiki database.
 *   - The frontend dev server runs automatically via the webServer
 *     config in playwright.config.ts.
 *
 * If this test fails, the user-facing loop is broken.
 */
test("user can ask, follow up, and save a thread to the wiki", async ({ page }) => {
  // Open the Ask view
  await page.goto("/ask");
  await expect(page.getByRole("heading", { name: /conversations/i })).toBeVisible();

  // Type a question
  const input = page.getByPlaceholder(/ask a question/i);
  await input.fill("What is the WikiMind project about?");
  await input.press("Enter");

  // Wait for the answer card to appear
  await expect(page.locator("article").first()).toBeVisible({ timeout: 30_000 });

  // The new conversation should now exist in the sidebar
  await expect(page.locator("aside").getByText(/wikimind project/i)).toBeVisible();

  // Ask a follow-up
  await input.fill("How does it close the loop?");
  await input.press("Enter");

  // Two turn cards should now be visible
  await expect(page.locator("article")).toHaveCount(2, { timeout: 30_000 });

  // Save the thread to the wiki
  // (The button label is "Save thread to wiki" before file-back)
  page.once("dialog", (dialog) => dialog.accept()); // accept the alert toast
  await page.getByRole("button", { name: /save thread to wiki/i }).click();

  // After save, the button label changes to "Update wiki article"
  await expect(page.getByRole("button", { name: /update wiki article/i })).toBeVisible();
});
```

- [ ] **Step 2: Run the test against a running backend**

Start the backend in one terminal:

```bash
make dev
```

(Optional: ingest a fixture source so retrieval has something to find. The test assumes at least one Article exists. If your local DB is empty, run an ingest first.)

In another terminal, run the test:

```bash
cd apps/web && npm run e2e
```

Expected: test PASS. If it fails:
- Check the screenshot in `playwright-report/`
- Verify the backend is reachable at `http://localhost:7842`
- Verify the frontend dev server starts (Playwright launches it via the webServer config)

- [ ] **Step 3: Commit**

```bash
git add apps/web/tests/e2e/ask-loop.spec.ts
git commit -m "test(e2e): add Ask loop happy path Playwright test"
```

## Task 3.3: Push and open PR 3

- [ ] **Step 1: Push**

```bash
git push -u origin claude/ask-slice-pr3-e2e
```

- [ ] **Step 2: Open PR**

```bash
gh pr create --title "test(e2e): Playwright Ask loop happy path — PR 3 of 3" --body "$(cat <<'EOF'
## Summary

PR 3 of 3 — adds an end-to-end Playwright test that drives the actual Ask UI through the full conversational loop. This is the **behavioral coverage** for PR 2's frontend, since PR 2 deliberately ships without component-level unit tests.

### What this PR does

- Installs `@playwright/test` in `apps/web`
- Adds `playwright.config.ts` (single chromium project, runs against local Vite dev server)
- Adds `apps/web/tests/e2e/ask-loop.spec.ts` with one test:
  - Open `/ask`
  - Ask a question
  - Ask a follow-up
  - Save the thread to the wiki
  - Verify the button label transitions from "Save" to "Update"

### Prerequisites

The test requires the FastAPI backend to be running and the wiki to have at least one ingested Article. CI may need a wikidata-fixture step before running e2e.

## Test plan

- [ ] `npm run e2e` passes locally with backend running
- [ ] CI green (Playwright runs as part of the frontend test job)
EOF
)"
```

---

# Self-Review

Before considering this plan complete, the implementing engineer should verify:

**1. Spec coverage** — Each major spec section maps to one or more tasks:

| Spec section | Plan task(s) |
|---|---|
| Settings (qa.*) | 1.1 |
| Data model — Conversation table | 1.2 |
| Data model — Query columns | 1.2 |
| Schema additions (lightweight migration) | 1.3 |
| Backfill helper | 1.4 |
| Conversation serializer | 1.5 |
| `_load_prior_turns` | 1.6 |
| `answer()` conversation awareness | 1.7 |
| Updated existing tests | 1.8 |
| `_file_back_thread()` | 1.9 |
| Service layer | 1.10 |
| Routes | 1.11 |
| Existing integration test update | 1.12 |
| Multi-turn context test | 1.13 |
| **Loop closure test (headline)** | 1.14 |
| `.env.example` | 1.15 |
| `make verify` | 1.16 |
| Push + open PR 1 | 1.17 |
| Frontend API client | 2.2 |
| Routes + nav | 2.3 |
| AskView | 2.4 |
| ConversationHistory | 2.5 |
| ConversationThread | 2.6 |
| TurnCard expand/collapse | 2.7 |
| QueryInput | 2.8 |
| SaveThreadButton | 2.9 |
| Frontend verification | 2.10 |
| Push + open PR 2 | 2.11 |
| Playwright install | 3.1 |
| e2e test | 3.2 |
| Push + open PR 3 | 3.3 |

**2. Type consistency** — Names used across tasks:

- `Conversation` (model class) — referenced in tasks 1.2, 1.3, 1.4, 1.6, 1.7, 1.9, 1.10, 1.11, 1.12, 1.13, 1.14
- `Conversation.filed_article_id` — referenced in tasks 1.2, 1.9, 1.10
- `Query.conversation_id`, `Query.turn_index` — referenced in tasks 1.2, 1.3, 1.6, 1.7, 1.10
- `QAAgent.answer()` returning `tuple[Query, Conversation]` — used consistently in tasks 1.7, 1.8, 1.10, 1.13, 1.14
- `_file_back_thread(conversation_id, session)` — used in tasks 1.9, 1.10, 1.12, 1.14
- `_load_prior_turns(conversation_id, up_to_turn_index, session)` — used in tasks 1.6, 1.7
- `_get_or_create_conversation`, `_next_turn_index` — defined in task 1.7, called from `answer()`
- `serialize_conversation_to_markdown(conversation, queries)` — defined in 1.5, used in 1.9
- `AskResponse { query, conversation }` — defined in 1.2, used in 1.10, 1.11, 2.2

**3. Placeholders** — Searched for TBD/TODO/FIXME in this plan; the only "TODO" is the inline note in Task 2.4 about replacing `window.alert` with a proper toast library, which is appropriately scoped (the spec says toast, not alert, but no toast library exists today; flagged as a follow-up).

**4. Missing elements** —
- No task for deleting `Query.filed_back` / `filed_article_id` columns. **Intentional** — the spec says these stay for one release, dropped in a follow-up. Out of scope for this plan.
- No task for the optional PR 0 (frontend test infra). **Intentional** — user declined during spec review.

---

Plan complete. Saved to `docs/superpowers/plans/2026-04-08-ask-vertical-slice.md`.

**Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task in an isolated worktree, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints for review.

Which approach?
