# Ask Vertical Slice — Design

**Date:** 2026-04-08
**Status:** Approved (chunks 1 + 2 brainstormed and confirmed by user)
**Author:** Brainstorming session against the WikiMind / Karpathy LLM Wiki Pattern
**Related ADR:** [ADR-011 — Conversational Q&A thread model](../../adr/adr-011-conversational-qa-thread-model.md)

## Context

WikiMind exists to instantiate the Karpathy LLM Wiki Pattern: a knowledge base where the human curates sources and the LLM handles the bookkeeping, and where **explorations compound back into the wiki as new sources**. The product loop is **Ingest → Query → Lint**. Without the Query side of the loop closing properly — meaning a user can ask a question, get a sourced answer, and file the answer back as a wiki article that future questions can retrieve — WikiMind is a fancy ingest pipeline, not a wiki.

As of Round 7 (PRs #85, #86, #87 just merged), the loop is **two specific gaps** away from working:

1. **No UI** for the Q&A path. The backend route `POST /query` exists, the API client method `askQuestion()` exists in `apps/web/src/api/query.ts`, but no React surface lets a user actually drive it. The app's only routes are `/inbox` and `/wiki`.
2. **Naive single-shot semantics**. The current `QAAgent.answer()` has no concept of conversation. Each call is independent. There's no way to ask a follow-up that knows what "it" or "that approach" refers to. PR #85 (manavgup/wikimind#84) just fixed the file-back path so it no longer crashes — the prerequisite for any Save-to-wiki UX.

This spec defines the **minimum loop-closing slice**: a conversational Ask UI backed by a real conversation data model, plus the integration test that proves filed-back answers are retrievable by future questions.

## Goals

1. Close the Karpathy loop end-to-end. A user can: open the app → ask a question → see a sourced answer → ask follow-ups in the same conversation (with the LLM aware of prior turns) → save the conversation as a wiki article → ask a future question and have retrieval surface that filed-back article.
2. Land in **two PRs**: backend (data model + agent + routes + integration test) then frontend (Ask UI). Optional third PR for end-to-end Playwright test.
3. Prove the loop closes with **one integration test that exercises the full cycle** at the API layer. Without that test, the loop could subtly break in any future refactor.
4. Use the existing frontend infrastructure (Vite + React + Tailwind + react-query + zustand + react-router). Add a third top-level route alongside `/inbox` and `/wiki`.
5. Keep changes scoped to the loop closure. Defer all polish, optimization, and graph/sync work to follow-on issues that already exist (or were filed alongside this spec — see Out of scope below).

## Non-goals

This slice deliberately does **not** do the following. Each item has a tracking issue so the deferral is explicit, not forgotten:

| Deferred concern | Tracking issue |
|---|---|
| Streaming responses (token-by-token rendering) | manavgup/wikimind#88 |
| Conversation editing / branching from a prior turn | manavgup/wikimind#89 |
| Partial-thread or multi-thread file-back | manavgup/wikimind#90 |
| Conversation export as standalone markdown (not via wiki file-back) | manavgup/wikimind#91 |
| Retrieval upgrade — ChromaDB + embeddings | manavgup/wikimind#20 |
| Backlink extraction producer | manavgup/wikimind#23 |
| Concept taxonomy auto-generation | manavgup/wikimind#24 |
| Knowledge graph view (force-directed UI) | manavgup/wikimind#25 |
| Cloud sync — including conversation-level sync | manavgup/wikimind#28 |

Additional explicit non-goals:

- **No retrieval changes.** The current naive token-overlap scoring in `QAAgent._retrieve_context` stays exactly as-is. The loop closes regardless of retrieval quality. Better retrieval is a follow-on (#20).
- **No streaming.** Answers arrive whole. SSE / chunked rendering is #88.
- **No prompt polish.** The strict-JSON contract from ADR-007 is preserved unchanged. The Q&A system prompt only gains a conversation-context block when prior turns exist; the response schema is unchanged.
- **No multi-modal or vision.** #68 covers vision-LLM ingestion separately.
- **No conversation archiving, starring, sharing, or search.** Future Phase-5 / sync work.

## Design — Backend

### Data model

**One new table.** One new (and one helper) column on the existing `Query` table.

```python
# src/wikimind/models.py

class Conversation(SQLModel, table=True):
    """A conversation thread of one or more Q&A turns.

    A conversation groups related queries that share LLM context. The
    first turn's question becomes the conversation's title (truncated).
    Filing a conversation back to the wiki is a per-conversation action,
    not per-turn — see ADR-011.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    title: str  # = first question of thread, truncated to CONVERSATION_TITLE_MAX_CHARS
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    filed_article_id: str | None = Field(default=None, foreign_key="article.id")
    # filed_article_id is the SINGLE source of truth for "this conversation
    # has been filed back". Re-saving overwrites the existing Article in place.
```

```python
class Query(SQLModel, table=True):
    # ... existing fields ...
    conversation_id: str | None = Field(
        default=None, foreign_key="conversation.id", index=True
    )
    turn_index: int = 0  # 0 for first turn, 1 for second, etc.

    # DEPRECATED but retained for one release for back-compat with rows
    # written before this spec landed. New code reads filed-back state
    # from Conversation.filed_article_id, not from Query.filed_back.
    # filed_back: bool = False
    # filed_article_id: str | None = None
```

`conversation_id` is **declared nullable in the schema** but **always populated by application code**. This matches the existing repo pattern (`Source.content_hash` is also nullable in the schema, always populated by current code). The reason is the repo's migration approach (next section) — SQLite + the lightweight `_migrate_added_columns` helper does not easily support adding NOT NULL columns to existing tables, so the app-level invariant is enforced in the service layer instead of in the schema.

### Schema additions

The repo does **not** use Alembic. Schema changes go through `database.py:_migrate_added_columns()`, which is described in its own docstring as "the project's lightweight alternative to Alembic and is safe to call on every startup." The function is idempotent: it inspects each tracked table via `PRAGMA table_info` and runs `ALTER TABLE ... ADD COLUMN` only when a column declared in the SQLModel definitions is missing from disk.

This work extends `_migrate_added_columns()` in three ways:

1. **New table — no helper change needed.** The `Conversation` SQLModel class is added to `models.py`. On the next startup, `SQLModel.metadata.create_all()` (the line that already runs in `init_db()`) will create the table automatically. SQLModel's `create_all` is itself idempotent and only creates tables that don't already exist.
2. **New columns on `query`.** Add two new entries to the `additions` list in `_migrate_added_columns`:
   ```python
   ("query", "conversation_id", "ALTER TABLE query ADD COLUMN conversation_id TEXT REFERENCES conversation(id)"),
   ("query", "turn_index",      "ALTER TABLE query ADD COLUMN turn_index INTEGER NOT NULL DEFAULT 0"),
   ```
   Both columns are nullable-or-defaulted in the schema. `turn_index` defaults to 0 so existing rows get a sensible value.
3. **Backfill for legacy rows.** A new helper `_backfill_conversation_for_legacy_queries()` is called from `init_db()` after `_migrate_added_columns`. It:
   - Selects all `Query` rows where `conversation_id IS NULL`.
   - For each one, creates a single-turn `Conversation` row whose `title` is the question truncated to `qa_conversation_title_max_chars`, whose `created_at` matches the Query's, and whose `filed_article_id` mirrors the Query's existing `filed_article_id` (so legacy file-back state is preserved).
   - Updates the Query's `conversation_id` to point at the new Conversation, sets `turn_index = 0`.
   - The whole thing is wrapped in one transaction and is idempotent (re-running finds zero NULL conversation_ids and is a no-op).

In practice, the backfill will touch zero or very few rows, because the Q&A path has been substantively broken (the file-back path crashed until #84 / PR #85 just landed) and any user-installed instance has likely never accumulated real Query history.

The deprecated `filed_back` and `filed_article_id` columns on Query stay populated for one release for back-compat. They are dropped in a follow-up cleanup change (out of scope here, tracked alongside the spec implementation).

**SQLite caveat:** SQLite cannot drop or rename columns easily. The deprecation strategy is **leave them in the schema and stop reading them**, not drop them. The eventual cleanup will require a CREATE-TEMP-TABLE-and-copy dance, which the lightweight migration helper doesn't currently know how to do. That cleanup is the trigger for revisiting whether the project should adopt Alembic — not part of this spec.

### Settings (no magic numbers)

Three constants live in `src/wikimind/config.py` as `Settings` fields, NOT as inline constants. This matches the project rule from `CLAUDE.md`: "Keep constants configurable via Settings, not hardcoded magic numbers."

```python
# config.py
qa_max_prior_turns_in_context: int = 5
qa_prior_answer_truncate_chars: int = 500
qa_conversation_title_max_chars: int = 120
```

The `qa_prior_answer_truncate_chars=500` value affects **only** the LLM prompt context block. The full answer is always preserved in `Query.answer` and is always returned by `GET /conversations/{id}`. The truncation exists to protect the model's context window, not to throw data away.

### Q&A agent changes

`src/wikimind/engine/qa_agent.py` — `QAAgent.answer()` gains conversation awareness.

**New signature:**

```python
async def answer(
    self,
    request: QueryRequest,
    session: AsyncSession,
    conversation_id: str | None = None,  # NEW
) -> tuple[Query, Conversation]:                # NEW return shape
```

**New flow:**

1. If `conversation_id` is `None`: create a new `Conversation` whose title is `request.question[:settings.qa_conversation_title_max_chars]`. Compute `turn_index = 0`.
2. If `conversation_id` is set: load the `Conversation`, compute `turn_index = max(existing turn_index) + 1`. Load the prior `qa_max_prior_turns_in_context` turns ordered by `turn_index`.
3. Retrieve context articles via the existing `_retrieve_context()` (unchanged).
4. Build the LLM prompt, prepending a **Conversation so far** block if prior turns exist (see prompt format below).
5. Call the LLM via the existing `_query_llm()`.
6. Persist the new `Query` row with `conversation_id` and `turn_index`.
7. Update `Conversation.updated_at`.
8. Return `(query, conversation)`.

**Prompt format with conversation context** — additive, only added when prior turns exist:

```text
Wiki context:
<retrieved articles, as today>

---

Conversation so far:
Q1: <question>
A1: <answer truncated to qa_prior_answer_truncate_chars>
Q2: <question>
A2: <answer truncated to qa_prior_answer_truncate_chars>

---

Current question: <Q3>

Answer based on the wiki context above. Use the conversation history
to disambiguate references like "it" or "that approach". If the
conversation context contradicts the wiki, prefer the wiki.
```

The system prompt itself (`QA_SYSTEM_PROMPT`) is **unchanged**. The conversation block lives in the user message, not the system message, so the strict-JSON contract from ADR-007 is preserved verbatim.

### File-back changes

The current `QAAgent._file_back()` is per-Query. It is renamed and reshaped to `_file_back_thread()`, called from a new service method.

**New behavior:**

1. Load the `Conversation` and all its `Query` rows ordered by `turn_index`.
2. Serialize the entire thread to markdown via a shared serializer (see Serialization helper below).
3. If `Conversation.filed_article_id` is **NULL**:
   - Create a new `Article` with `slug = slugify(conversation.title)`, `file_path = wiki/qa-answers/<slug>.md`, `confidence = None` (per #84 / Option 2).
   - Write the markdown to disk.
   - Set `Conversation.filed_article_id = article.id` and commit.
   - Return `(article, was_update=False)`.
4. If `Conversation.filed_article_id` is **set**:
   - Load the existing `Article` by id.
   - Overwrite the `.md` file at `article.file_path` with the new serialized markdown.
   - Update `Article.updated_at = utcnow()`.
   - Return `(article, was_update=True)`.

**Re-save semantics:** the article file is overwritten in place. The slug, the article id, and the file path are all stable. Anything that linked to the article (backlinks, history, the URL bar) keeps working.

### Serialization helper

A new module-level function `serialize_conversation_to_markdown(conversation, queries)` lives in `engine/qa_agent.py` (or a new `engine/conversation_serializer.py` if it grows). It is the **single source of truth** for thread → markdown conversion. Both the file-back path and a future conversation-export path (#91) must use the same function so their outputs are byte-identical.

**Markdown format:**

```markdown
---
title: "<conversation.title>"
slug: <slug>
type: qa-conversation
created: <conversation.created_at iso>
updated: <conversation.updated_at iso>
turn_count: <N>
---

# <conversation.title>

## Q1: <question>

<answer>

**Sources:** [[Article 1]], [[Article 2]]

## Q2: <follow-up question>

<answer>

**Sources:** [[Article 3]]

...
```

Frontmatter fields: `title`, `slug`, `type: qa-conversation` (distinct from `type: qa-answer` used by the old per-Query path), `created`, `updated`, `turn_count`.

### Service layer changes

`src/wikimind/services/query.py` — `QueryService.ask()` accepts the optional `conversation_id` and forwards it to `agent.answer()`. The new `QueryService.file_back_conversation(conversation_id)` is the entry point for the new file-back endpoint.

`QueryService.list_conversations(limit)` and `QueryService.get_conversation(id)` are new and back the new GET endpoints.

The existing `QueryService.file_back(query_id)` is **deleted** (it was per-Query and is replaced by per-conversation file-back). The existing `POST /query/{id}/file-back` route is **deleted** and replaced by `POST /conversations/{id}/file-back`.

### Routes

`src/wikimind/api/routes/query.py` is reshaped. Two of its three current endpoints change shape:

```text
POST /query
  body: { question: str, conversation_id?: str, file_back?: bool }
  returns: { query: Query, conversation: Conversation }
  - if conversation_id missing → new Conversation, turn_index=0
  - if conversation_id present → append, turn_index = max+1
  - file_back is deprecated as a hint here; actual file-back happens via the
    conversation endpoint below

GET /query/history?limit=50
  unchanged (lists Query rows for back-compat; UI uses /conversations instead)

POST /query/{id}/file-back
  REMOVED — replaced by POST /conversations/{id}/file-back
```

Three new routes go into `src/wikimind/api/routes/query.py` (or a new `conversations.py` router — decision deferred to implementation, both are fine):

```text
POST /conversations/{id}/file-back
  returns: { article: Article, was_update: bool }

GET /conversations?limit=50
  returns: list of { id, title, created_at, updated_at, turn_count, filed_article_id }
  ordered by updated_at DESC

GET /conversations/{id}
  returns: { conversation, queries: [Query, ...] }  # ordered by turn_index
```

`docs/openapi.yaml` will be auto-regenerated by the pre-commit hook on the implementation PR (per the doc-sync rules in `CLAUDE.md`).

### Backend tests

**Unit tests** in `tests/unit/test_qa_agent.py` and `tests/unit/test_services.py`:

- `serialize_conversation_to_markdown()` produces the expected markdown for a 1-turn, 3-turn, and 5-turn conversation
- `_file_back_thread()` creates an Article when `filed_article_id` is None
- `_file_back_thread()` overwrites in place when `filed_article_id` is set, returns `was_update=True`
- Prior-turn loading respects `qa_max_prior_turns_in_context`
- Prior-turn answer truncation respects `qa_prior_answer_truncate_chars`
- `turn_index` assignment is monotonic — even if two queries land in the same conversation in quick succession, they get distinct, sequential indices
- Existing tests in `tests/unit/test_qa_agent.py` continue to pass with the new return shape (mocks updated)

**Integration test** in `tests/integration/test_qa_loop_integration.py` (the file already exists from PR #85). This is the **headline test that proves the Karpathy loop closes**:

```python
async def test_filed_back_conversation_is_retrievable_by_next_query():
    """The Karpathy loop closure test.

    1. Seed a fixture Article into the wiki.
    2. Conversation A: ask a question that retrieves the fixture article.
       File back the conversation.
    3. Conversation B: ask a different question that should retrieve
       the article filed back from Conversation A (NOT the original fixture).
    4. Assert: Conversation B's answer cites the filed-back article by title.

    If this test ever fails, the loop is broken — that is the entire
    point of WikiMind.
    """
```

Plus a multi-turn integration test:

```python
async def test_multi_turn_conversation_includes_prior_context():
    """Q1: 'What is X?' → answer mentions Y.
    Q2 (same conversation): 'How does it relate to Z?'
    Assert the LLM call's prompt includes 'Q1: What is X?' in the
    Conversation so far block."""
```

Both integration tests use the existing hermetic fixtures (mocked LLM router, real SQLite, no network).

### Coverage

The repo enforces an 80% coverage floor in `make verify` (per PR #80 / `coverage-check` target). The new code must maintain or improve overall coverage. Realistic target: 90%+ on the new modules, since they're well-bounded.

## Design — Frontend

### Routes

`apps/web/src/App.tsx` — two new routes for the Ask surface:

```tsx
<Route path="/ask" element={<AskView />} />
<Route path="/ask/:conversationId" element={<AskView />} />
```

`/ask` opens a fresh conversation. `/ask/:conversationId` loads an existing one. The history sidebar links to the latter.

`apps/web/src/components/shared/Layout.tsx` — new nav link "Ask" between "Inbox" and "Wiki". The visual order Inbox → Ask → Wiki mirrors the Karpathy loop: raw input → exploration → compounded output.

### Components — `apps/web/src/components/ask/`

| Component | Responsibility |
|---|---|
| `AskView.tsx` | Page container. Two-column layout matching `WikiExplorerView`'s style. Left: `ConversationHistory` sidebar. Right: `ConversationThread` plus `QueryInput` anchored at the bottom. Reads `conversationId` from URL via `useParams`; if absent, the view is in "fresh conversation" mode. |
| `ConversationHistory.tsx` | Sidebar list of conversations, fetched from `GET /conversations` via react-query. Each row shows the title (truncated to one line), a relative timestamp ("2 hours ago"), and a turn-count badge. Click navigates to `/ask/:id`. Re-fetches when a new conversation is created in the current session (react-query invalidation on the conversations query key). |
| `ConversationThread.tsx` | Renders all turns in order. One `TurnCard` per turn. Below the last turn: the `SaveThreadButton`, only visible when the thread has at least one completed turn. |
| `TurnCard.tsx` | One Q+A pair. Shows the question, the answer (rendered as markdown via `react-markdown` + `remark-gfm` — already deps), source chips that link to `/wiki/:slug`, and the **expand/collapse behavior** (see below). |
| `QueryInput.tsx` | Bottom-anchored textarea. Submit on Enter, Shift+Enter for newline. Disabled while a request is in flight. Auto-focuses on mount and after every successful submit. |
| `SaveThreadButton.tsx` | Thread-level file-back trigger. POSTs to `/conversations/{id}/file-back`. Button label is "Save thread to wiki" if `Conversation.filed_article_id` is null, otherwise "Update wiki article". On success: toast with link to `/wiki/:slug`. |

### TurnCard expand/collapse — explicit requirement

Long answers must be visually collapsible **per turn**. This is a hard requirement, not a nice-to-have. Without it, a long answer dominates the viewport and follow-ups become invisible.

Behavior:

- **Collapse threshold**: based on rendered text length, not the LLM-context truncation number. Specifically: collapse if the rendered text would exceed roughly 800 characters of plain text (after stripping markdown). This is a heuristic; tune in spec review if it feels wrong.
- **Collapse boundary respects markdown structure**: never collapse mid-code-block, mid-list, mid-table. The collapse boundary snaps to the nearest paragraph break before the threshold.
- **Affordance**: a "Show more" button at the bottom of the collapsed answer; toggles to "Show less" when expanded.
- **State**: collapse state is local to the `TurnCard` component (`useState`), not persisted to URL or server. It's a viewing preference, not data. Each render of the same conversation starts collapsed for long answers — we are NOT storing per-user view state.
- **Default**: collapsed by default for long answers, expanded by default for short ones. Short answers never show the affordance.
- **Sources and confidence chips are always visible**, regardless of collapse state. They live above or below the expandable answer body, not inside it.

### API client changes — `apps/web/src/api/query.ts`

The file already exists. New types and exports:

```typescript
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
  queries: QueryRecord[];   // ordered by turn_index
}

export interface AskRequest {
  question: string;
  conversation_id?: string;   // NEW
  file_back?: boolean;        // deprecated; ignored by new backend code
}

export interface AskResponse {
  query: QueryRecord;
  conversation: Conversation;
}

// Existing askQuestion() return shape changes — breaking change to client lib,
// but no consumer exists yet.
export function askQuestion(req: AskRequest): Promise<AskResponse>;

// New methods
export function listConversations(limit?: number): Promise<ConversationSummary[]>;
export function getConversation(id: string): Promise<ConversationDetail>;
export function fileBackConversation(id: string): Promise<{ article: Article; was_update: boolean }>;
```

Plus update to `QueryRecord` to expose `conversation_id` and `turn_index`.

### State management

- `@tanstack/react-query` for all server state. Cache keys:
  - `["conversations"]` for the sidebar list
  - `["conversation", id]` for the detail view
- Mutations: `askQuestion` invalidates `["conversation", id]` and `["conversations"]`. `fileBackConversation` invalidates `["conversation", id]`.
- **No new zustand store.** All state is server state, route state (`useParams`), or component-local (`useState`).
- The existing `useWebSocket` hook is not used by this slice. It's available if a follow-on wants live-streaming updates or push notifications.

### Frontend tests — important caveat

**The frontend currently has zero test infrastructure.** `apps/web/package.json` has no `test` script, no vitest, no `@testing-library/react`, no jsdom. Existing CI for the frontend runs only `lint`, `typecheck`, and `build`. None of the existing components (`InboxView`, `WikiExplorerView`, `ArticleReader`, etc.) have unit tests.

Introducing component-level test infrastructure as part of this feature work would meaningfully expand PR 2's scope and is a project-level decision that should not be made implicitly inside a feature spec. **This spec therefore deliberately does not introduce vitest in PR 2.** The frontend changes go through the existing gates (`lint`, `typecheck`, `build`) and behavioral coverage comes from PR 3's optional Playwright end-to-end test instead.

**If the user wants frontend unit testing as part of this work**, the right move is to add it as a separate small PR before PR 2: install vitest + `@testing-library/react` + `@testing-library/jest-dom` + jsdom, add a `vitest.config.ts`, add a `test` script to `package.json`, wire it into CI. This is a one-time setup that benefits all future frontend work, not just this slice. Decision deferred to spec review.

### Frontend build / verification

`apps/web/package.json` has `lint`, `typecheck`, `build`, `dev`, `preview`. Existing CI runs lint + typecheck + build for the frontend on every PR. The new components must satisfy the existing linter and type checker without disabling any rules. No coverage threshold exists for the frontend today; this spec does not add one.

## Data flow — happy path

```text
1. User opens /ask in browser.
2. AskView renders empty thread + QueryInput; ConversationHistory loads sidebar.
3. User types "What is X?" + Enter.
4. askQuestion({question: "What is X?"}) posts to POST /query.
5. Backend: no conversation_id → creates Conversation(title="What is X?", id=C1).
   QAAgent.answer retrieves context articles, calls LLM (no prior turns), persists
   Query(turn_index=0, conversation_id=C1).
6. Response: {query, conversation: C1}.
7. Frontend: react-query updates ["conversations"] cache; AskView navigates to
   /ask/C1; thread re-renders with the new TurnCard.
8. User types follow-up "How does it work?".
9. askQuestion({question: "How does it work?", conversation_id: C1}) posts.
10. Backend: loads C1, computes turn_index=1, loads prior turn 0, builds prompt
    with "Conversation so far: Q1: What is X? / A1: <truncated>", calls LLM,
    persists Query(turn_index=1, conversation_id=C1), updates C1.updated_at.
11. Response: {query, conversation: C1 (refreshed)}.
12. Frontend: thread appends second TurnCard.
13. User clicks "Save thread to wiki".
14. fileBackConversation(C1) posts to POST /conversations/C1/file-back.
15. Backend: loads C1 + both Query rows, serializes to markdown, sees C1.filed_article_id
    is null, creates Article(slug=slugify(C1.title), file_path=wiki/qa-answers/<slug>.md),
    writes file, sets C1.filed_article_id, returns {article, was_update: false}.
16. Frontend: toast "Saved to wiki" with link to /wiki/<slug>.
17. SaveThreadButton label changes to "Update wiki article".
18. — Loop closure proof —
    User navigates back to /ask, starts a new conversation, asks a related question.
    QAAgent retrieval scans all Article rows. The article filed back from C1 is
    in the table. Retrieval finds it. The new conversation's answer cites it.
```

## Error handling

Stays simple and explicit. No silent failures (project policy).

| Failure | Behavior |
|---|---|
| LLM call fails (router exhausts all providers) | `QAAgent.answer()` raises; service returns HTTP 502; frontend toasts an error and the QueryInput re-enables. The Query row is NOT persisted. No half-state. |
| Retrieval returns zero articles | Existing behavior preserved: `QueryResult(answer="No relevant articles found...", confidence="low")`. The Query row IS persisted (so the conversation history reflects the failed lookup). |
| File-back: `Conversation` not found | HTTP 404. Frontend toasts "Conversation not found" and refetches the sidebar. |
| File-back: race condition (two clicks land at once) | The DB transaction wraps the `filed_article_id` check + write. The second call sees `filed_article_id` already set and follows the update path. Both clicks succeed; both return `was_update=true` for the second one. |
| Conversation context window exceeded | The `qa_max_prior_turns_in_context` cap is the upper bound. If even 5 truncated prior turns push the prompt over the model's context limit, the LLM call will fail (existing behavior). Mitigation: configure `qa_prior_answer_truncate_chars` lower. Out of scope: smarter summarization of prior turns. |
| User navigates away mid-request | The fetch is not cancelled; the persisted Query lands as part of the conversation. Next time the user opens that conversation, the turn is there. Acceptable. |

## Build sequence

Three PRs, sequential. The first must merge before the second can test against a real backend.

### PR 1 — backend (~450 lines added)

- New `Conversation` SQLModel; new columns + backfill helper in `database.py:_migrate_added_columns`
- Models, services, agent changes
- New routes; deletion of old `POST /query/{id}/file-back`
- New `qa_*` Settings fields in `config.py`
- Unit tests (serializer, file-back branching, prior-turn handling, turn_index monotonicity)
- Integration tests (loop closure, multi-turn context)
- Auto-regenerated `docs/openapi.yaml` (handled by the doc-sync pre-commit hook)
- ADR-011 lives in `docs/adr/` and lands in this PR (or as a sibling commit) since the architectural decision is exercised by the code in this PR
- `.env.example` updated with the three new `qa_*` settings

### PR 2 — frontend (~600 lines added)

- New routes in `App.tsx`
- New `apps/web/src/components/ask/` directory with all six components
- Updated `apps/web/src/api/query.ts`
- New nav link in `Layout.tsx`
- README Phase 2 checklist update
- **No component-level unit tests** — see "Frontend tests — important caveat" above. Behavioral coverage comes from PR 3.
- Depends on PR 1 being merged (the backend contract must be live)

### PR 3 — end-to-end smoke test (recommended, ~150 lines)

- Playwright test in `apps/web/tests/e2e/ask-loop.spec.ts`
- Drives the actual UI: opens `/ask`, types a question, waits for the answer to render, clicks Save, navigates to the wiki article, asserts content
- Requires a one-time Playwright install in `apps/web/` (`@playwright/test` as a devDep, `playwright.config.ts`, `tests/e2e/` directory)
- This is the **frontend's actual behavioral test coverage** for this slice, since PR 2 deliberately does not include unit tests. Upgraded from "optional" to "recommended" for that reason.
- Can land in parallel with PR 2

### Optional PR 0 — frontend unit test infrastructure

If the user decides during spec review that frontend unit tests should be part of this work, this is the place: a small standalone PR that adds vitest + `@testing-library/react` + `@testing-library/jest-dom` + jsdom + `vitest.config.ts` + a `test` script + CI wiring. Adds no behavior; only sets up the tooling. PR 2 then includes component tests against that infrastructure. Decision pending in spec review.

## Test plan summary

| Layer | What | Where |
|---|---|---|
| Backend unit | Serializer, file-back branching, prior-turn truncation, turn_index | `tests/unit/test_qa_agent.py`, `tests/unit/test_services.py` |
| Backend integration | **Loop closure**, multi-turn context | `tests/integration/test_qa_loop_integration.py` |
| Frontend lint + types + build | Existing CI checks pass | Existing `apps/web` CI |
| End-to-end (PR 3, recommended) | Full UI happy path through real backend | `apps/web/tests/e2e/ask-loop.spec.ts` (Playwright) |
| Frontend unit (optional PR 0) | TurnCard collapse, SaveThreadButton state, etc — only if PR 0 lands | `apps/web/src/components/ask/*.test.tsx` |

The integration test for loop closure is the **single most important test** in this whole spec. If it passes, WikiMind is a working Karpathy-loop wiki. If it fails, no amount of UI polish matters.

## Documentation impact

Per the doc-sync protocol in `CLAUDE.md`:

| Doc | Update needed | Trigger |
|---|---|---|
| `README.md` | Yes — Phase 2 checkbox `[ ] Q&A Agent — complete implementation` becomes partly checked, plus add Ask UI to user-facing feature list | Manual edit in PR 2 |
| `docs/openapi.yaml` | Yes — query route gains `conversation_id`; new conversation routes added | Auto-regenerated by `make export-openapi`, enforced by pre-commit |
| `docs/adr/adr-011-conversational-qa-thread-model.md` | NEW | Created by PR 1 |
| `docs/adr/README.md` | Auto-regenerated | `scripts/regenerate_adr_index.py` |
| `.env.example` | Yes — three new `qa_*` Settings need entries | Manual edit in PR 1 |
| `CLAUDE.md` | No changes — no convention changes |  |

`make check-docs` and `make check-doc-sync` run in pre-commit and CI; either will fail the PR if the above are not honored.

## Risks and open questions

**1. Naive retrieval may make conversational follow-ups feel dumb.** Token-overlap scoring doesn't understand pronouns or topical drift. A follow-up like "what about its weaknesses?" will retrieve articles matching "weaknesses" — which may or may not be the right ones. The conversation context in the prompt mitigates this somewhat (the LLM knows what "it" refers to), but retrieval itself stays naive. **Mitigation**: ship anyway. The loop closes. If usage shows this is the dominant pain point, prioritize #20 (embeddings) immediately after.

**2. Re-saving overwrites the wiki article in place — there is no "previous version" history.** If a user saves a 3-turn conversation, then asks two more turns and re-saves, the original 3-turn article is gone. **Mitigation**: this is intentional (the conversation IS the article; the conversation grew). If users want versioning, that's a separate feature (and arguably belongs to the wiki layer, not the Q&A layer).

**3. The `Conversation.title` is set at first-turn time and never updated.** If the conversation drifts off-topic, the title becomes misleading. **Mitigation**: explicitly out of scope. The branching/editing follow-up (#89) is the right place to address this — when a fork happens, the fork can have its own title.

**4. Existing `POST /query/{id}/file-back` route is deleted, not deprecated.** Any external client (none today) that calls it will get a 404. **Mitigation**: there are no external clients. The frontend is the only consumer and is being rewritten in this same change set. Document the breaking change in the PR description.

**5. `make verify` coverage floor is 80%; new files must maintain it.** Realistic target: the new modules will be 90%+ since they're small and focused. The integration test contributes substantial coverage to `qa_agent.py` and `services/query.py`. No risk anticipated.

## Definition of done

The slice is complete when **all** of the following are true:

- [ ] PR 1 merged. Migration runs cleanly on a fresh DB and on a DB with existing Query rows. All backend tests pass. `make verify` green. ADR-011 committed.
- [ ] PR 2 merged. The Ask UI is reachable at `/ask`. A user can open the app, ask a question, see an answer, ask a follow-up that uses prior context, save the conversation, and find the saved article in the Wiki Explorer. Frontend tests pass.
- [ ] The integration test `test_filed_back_conversation_is_retrievable_by_next_query` is green in CI.
- [ ] One manual end-to-end run by the user (or PR 3 Playwright test, if shipped) confirms the loop closes through the actual UI, not just the API.
- [ ] `README.md` Phase-2 checklist updated.
- [ ] All four follow-on issues (#88, #89, #90, #91) referenced in PR descriptions and the spec.

When the integration test passes and the manual run succeeds, **WikiMind has a closed Karpathy loop** for the first time. That is the milestone this slice exists to deliver.
