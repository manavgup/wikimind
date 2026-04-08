# ADR-011: Conversational Q&A thread model

## Status

Accepted

## Context

WikiMind exists to instantiate the Karpathy LLM Wiki Pattern, where the product
loop is **Ingest → Query → Lint** and the critical mechanism is that
*"explorations compound back into the wiki as new sources."* Until this ADR,
the Q&A path was single-shot: each `POST /query` was an independent LLM call
with no awareness of any prior question. This made multi-turn exploration
impossible — a follow-up like "what about its weaknesses?" had no idea what
"it" referred to.

The Ask vertical slice (spec:
`docs/superpowers/specs/2026-04-08-ask-vertical-slice-design.md`) is the work
to close the loop end-to-end with a real conversational UX. Building it
requires a data model decision that has long-term consequences for the rest of
the product: file-back semantics, cloud sync (#28), conversation editing
(#89), partial-thread save (#90), and conversation export (#91) all hang off
of how a "conversation" is represented.

The decision points were:

1. **Threading semantics** — does a follow-up share LLM context with prior
   turns, or is each query independent?
2. **Conversation persistence** — is a conversation a first-class entity
   (own table), or just an implicit grouping of `Query` rows by some
   identifier?
3. **File-back unit** — when the user clicks "Save to wiki," does that save
   one Q+A pair (the current per-Query behavior, just fixed in #84), or the
   whole conversation as a single article?

These three decisions are deeply interrelated. They are recorded together in
this single ADR rather than split, because choosing one constrains the
others.

## Decision

WikiMind models Q&A as **conversations of one or more turns**, where:

### 1. A conversation is a first-class entity with its own table

```python
class Conversation(SQLModel, table=True):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    title: str  # = first question of thread, truncated
    created_at: datetime
    updated_at: datetime
    filed_article_id: str | None = Field(foreign_key="article.id")
```

`Query` gains a non-nullable `conversation_id` foreign key and a `turn_index`
column. Every Query belongs to exactly one Conversation. The first Query in a
conversation has `turn_index=0`.

### 2. Per-turn retrieval, conversation context in the prompt

Each turn re-runs retrieval independently against the wiki. The Q&A agent's
prompt is augmented with a **Conversation so far** block listing the prior N
turns (configurable via `qa_max_prior_turns_in_context`, default 5), with
each prior answer truncated to a configurable character limit
(`qa_prior_answer_truncate_chars`, default 500). This truncation affects
**only** the LLM context; the full answer is always preserved in
`Query.answer` and is always returned by `GET /conversations/{id}`.

The system prompt (ADR-007's strict-JSON contract) is unchanged. The
conversation block is added to the **user message**, not the system message.

### 3. File-back is per-conversation, not per-turn

The file-back action serializes the entire conversation to one wiki article.
The article's title is `Conversation.title` (the first question, truncated).
`Conversation.filed_article_id` is the single source of truth for "this
conversation has been filed back" — re-saving overwrites the existing
article in place via that pointer. The article id, slug, and file path stay
stable across re-saves; only the body and `updated_at` change.

The previous per-Query file-back path (`POST /query/{id}/file-back`) is
removed. The previous `Query.filed_back` and `Query.filed_article_id` columns
are deprecated but retained for one release for back-compat with rows
written before this ADR.

## Alternatives Considered

### Threading semantics

**Visual grouping only (frontend trick).** Treat conversations as a pure
display concept; backend remains single-shot. Each follow-up is an independent
`POST /query` with no shared state. Rejected: the conversational UX promise
breaks immediately on the first follow-up that uses a pronoun. The LLM has no
way to know what "it" refers to. Defeats the entire purpose of having
conversations in the first place.

**Conversation context + shared retrieval pool.** Same as the chosen design,
but retrieval also remembers which articles were used in prior turns and biases
future retrieval toward the same source set. Rejected: marginal benefit at the
wiki sizes WikiMind will have for a while; meaningfully more complex; pushes a
retrieval-system change into a feature that doesn't need it. The chosen design
gets the conversational behavior with no retrieval changes at all.

### Conversation persistence

**Just add `conversation_id` and `parent_query_id` columns to Query.**
Smallest possible migration: two new nullable columns, no new table. A
conversation would be implicit — the set of Query rows sharing a
`conversation_id`, with the first row having `parent_query_id=NULL`.
Rejected for three reasons:

1. The "title = first question, single-article-per-thread, replace on re-save"
   semantics from the file-back decision want a place to live. With no
   Conversation table, the title would be a runtime computation every time
   the UI needs it, and `filed_article_id` would have to live awkwardly on the
   first Query row of the thread (fragile if that row is ever deleted or
   re-numbered).
2. Adding a `Conversation` table later, after threads exist as flat Query
   rows, requires a backfill to create Conversation rows for every existing
   thread. Doing it now is one extension to `database.py:_migrate_added_columns`
   plus a small idempotent backfill helper; doing it later is the same plus
   the complexity of dealing with whatever shape Query rows have accumulated
   in the meantime. Cost is small now and grows over time.
3. Phase 5 cloud sync (#28) is going to want a conversation-level identifier
   with metadata anyway. Skating to where the puck is going costs nothing
   today.

**Hybrid: lazy Conversation row.** Same shape as the chosen design, but the
Conversation row only gets created when the user files back. Until then,
queries are orphans grouped by `conversation_id` only. Rejected: introduces
two states for the same concept ("orphan" vs "materialized"), which makes
debugging and querying weird, for very little storage savings.

### File-back unit

**Save the current turn only (one Q+A pair → one wiki article).** This is
what the codebase did before this ADR — the old `_file_back()` was per-Query.
Rejected:

1. The Karpathy gist explicitly says *"explorations compound like ingested
   sources."* A single Q+A pair isn't really an exploration — it's a lookup.
   What's worth filing back, in a way that genuinely makes the wiki smarter,
   is *the path the user took*, not just the destination.
2. A turn-3 question in isolation is often nonsense ("what about its
   weaknesses?"). Saving it as a wiki article with that as the title produces
   garbage.
3. The whole point of having conversation context in the prompt is that the
   exploration is the unit of meaning. Saving a single turn throws away the
   context that made the answer useful.

**Both — per-turn save and whole-thread save (two buttons).** Maximum
flexibility. Rejected: two code paths, two sets of file-back semantics,
decision fatigue at the UI surface ("which button do I want?"), and the
whole-thread save is the one the Karpathy framing actually demands.
Preference is to ship whole-thread save only, see if anyone wants per-turn,
add it later if real usage demands it. Tracked as a follow-up in #90.

## Consequences

### Enables

- **The Karpathy loop closes.** The integration test
  `test_filed_back_conversation_is_retrievable_by_next_query` (in
  `tests/integration/test_qa_loop_integration.py`, added by this work)
  exercises the full cycle: ingest source → conversation A asks about it →
  file back → conversation B retrieves the filed-back article. When this test
  passes, WikiMind is a working Karpathy-loop wiki.
- **Multi-turn conversations work.** Follow-ups with pronouns ("it", "that
  approach") resolve correctly because the LLM has the prior turns in its
  context window.
- **Re-save semantics are clean.** A user can keep extending a conversation
  and re-save; the wiki article updates in place; nothing else has to track
  versions.
- **Conversation editing / branching (#89), partial-thread save (#90), and
  conversation export (#91)** all have a natural data model to extend. Adding
  `parent_conversation_id` (for branches) or a turn-selection serializer (for
  partial save) is a small additive change against the structure defined here.
- **Cloud sync (#28)** has a stable conversation-level identifier with
  metadata to sync, rather than having to invent one later.

### Constrains

- **The Conversation/Query relationship is fixed at write time.** A Query
  always belongs to exactly one Conversation. Moving turns between
  conversations is not supported. If users want this, the branching follow-up
  (#89) is the right place to address it.
- **`Conversation.title` is set at first-turn time and never updated by the
  Ask UI.** If the conversation drifts off-topic, the title becomes
  misleading. The branching follow-up (#89) is also the right place to
  address this — when a fork happens, the fork gets its own title.
- **The deprecated `Query.filed_back` and `Query.filed_article_id` columns
  must be cleaned up later.** They are retained for one release for
  back-compat. SQLite cannot drop columns easily, so the cleanup will
  require a CREATE-TEMP-TABLE-and-copy step that the repo's lightweight
  migration helper does not currently know how to do. That cleanup is the
  natural trigger for revisiting whether the project should adopt Alembic.
  Out of scope for this ADR.
- **Re-save is destructive.** There is no "previous version" of a filed-back
  article. If a user re-saves an extended conversation, the original article
  is gone (overwritten). This is intentional (the conversation IS the
  article), but worth documenting so it doesn't surprise future contributors.

### Risks

- **Naive retrieval may make conversational follow-ups feel weak.** Token-
  overlap scoring doesn't understand pronouns or topical drift. The
  conversation context block in the prompt mitigates this by giving the LLM
  the prior turns, but retrieval itself remains naive. Mitigation: the loop
  closes regardless of retrieval quality. If usage shows this is the
  dominant pain point, prioritize #20 (ChromaDB + embeddings) immediately
  after this slice ships.
- **The token cost of including prior turns in every prompt is real.** Five
  turns × ~200 tokens of truncated answer = ~1k extra tokens per follow-up.
  At Claude/OpenAI prices this is fractions of a cent per call, but it's
  cumulatively non-zero. Mitigation: the truncation is configurable; a user
  with high call volume can tune it down.
- **Concurrent inserts into the same conversation could collide on
  `turn_index`.** The chosen approach is `max(existing) + 1` inside the
  service layer, not a DB-level sequence. Two simultaneous turns on the same
  conversation could in principle race. Mitigation: in single-user local-
  daemon mode (the only mode WikiMind runs in today), this doesn't happen.
  When multi-user / cloud sync arrives in Phase 5, revisit with a proper
  sequence or transaction-level lock.
- **The conversation-context prompt addition could in theory push some
  conversations over the model's context window.** With a 5-turn cap and
  500-char truncation, this is unlikely for current models but possible with
  smaller local models (Ollama). Mitigation: existing LLM router fallback
  (ADR-003) catches the error and tries the next provider; if it fails
  everywhere, the user sees an explicit error rather than a silent
  truncation.
