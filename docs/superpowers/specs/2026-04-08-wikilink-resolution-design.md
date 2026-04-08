# Wikilink Resolution — Design

**Date:** 2026-04-08
**Status:** Draft — pending user review
**Author:** Design session against issues manavgup/wikimind#95 and #96
**Related issues:** #95 (wikilinks 404), #96 (slug divergence), Epic 3 (knowledge graph)

## Context

Every `[[wikilink]]` in a compiled article currently 404s (issue #95). The compiler's JSON prompt contract asks the LLM for a `backlink_suggestions` list of "related concepts that likely exist in the wiki" (`src/wikimind/engine/compiler.py:52`) and the compiler writes those titles verbatim into the "Related" section as `[[Title]]` markdown (`src/wikimind/engine/compiler.py:333`). Nothing verifies that the target exists, no `Backlink` row is created, and the React `ArticleReader` then slugifies the link text client-side and fetches `/wiki/articles/{slug}`, which fails for two reasons: (a) the LLM hallucinates titles that were never compiled, and (b) even when a target exists, the frontend's homemade regex slugifier and the backend's `python-slugify` library disagree on unicode, underscores, and apostrophes — the slug divergence tracked as #96. The user-visible impact is that the "Related" section is entirely broken: every link is a dead link, there are no real backlinks anywhere in the knowledge base, and the primitive Epic 3 (knowledge graph view) depends on — real `Backlink` rows the compiler does not currently emit.

## Current state

| Concern | Location |
|---|---|
| LLM prompt asks for `backlink_suggestions` strings | `src/wikimind/engine/compiler.py:52` |
| Compiler writes verbatim `[[title]]` to markdown "Related" section | `src/wikimind/engine/compiler.py:333` (inside `_write_article_file`) |
| `Backlink` SQLModel table **already exists** (composite PK `source_article_id` + `target_article_id`, optional `context` snippet) | `src/wikimind/models.py:157` |
| `Backlink` has NO `id` field — composite primary key is `(source_article_id, target_article_id)` | `src/wikimind/models.py:160-162` |
| Compiler **never writes `Backlink` rows** — grep `session.add(Backlink(...))` returns nothing | codebase-wide |
| Slug-based article lookup — the only way to resolve a link from the frontend today | `src/wikimind/services/wiki.py:177` (backed by route `src/wikimind/api/routes/wiki.py:26`) |
| Frontend client-side slugifier (diverges from backend `python-slugify`) | `apps/web/src/components/wiki/ArticleReader.tsx:19-25` |
| Frontend `data-wikilink` attribute hack + custom anchor renderer | `apps/web/src/components/wiki/ArticleReader.tsx:33-40`, `:77-101` |
| `CompilationResult.backlink_suggestions: list[str]` Pydantic field | `src/wikimind/models.py:290` |

Key finding: **the `Backlink` model already exists but is never populated**. The compiler-save path (`Compiler._create_article` and `Compiler._replace_article_in_place` in `compiler.py`) writes the markdown file and commits an `Article` row, and nothing else. The knowledge graph endpoint `WikiService.get_graph` (`services/wiki.py:222`) reads from the `Backlink` table — it has been returning an empty edge set since day one.

## Goals

1. Every `[[wikilink]]` rendered in an article body is either (a) a clickable link to an existing article or (b) visually marked as unresolved and non-clickable. No more silent 404s.
2. Resolved links produce **real `Backlink` rows** in the database at compile time. The knowledge graph primitive that Epic 3 needs becomes populated on the very next compile.
3. The frontend stops doing client-side slugification. Resolved links travel by article ID, not by slug — sidesteps issue #96 entirely.
4. Both issue #95 (broken wikilinks) and issue #96 (slug divergence) are closed by this work. #96 becomes subsumed: if the frontend never slugifies, the two slugifiers can never drift.
5. The compiler's prompt contract is **unchanged**. The LLM keeps asking for `backlink_suggestions` exactly as today. Only the post-processing of its output changes.
6. The resolution algorithm is **deterministic**. Given the same set of articles and the same candidate list, resolution produces the same result every time. No fuzzy thresholds, no embedding lookups, no LLM-in-the-loop.

## Non-goals

- **Does NOT implement the knowledge graph visualization.** Epic 3 builds on top of the `Backlink` rows this work produces; it is not part of this PR.
- **Does NOT implement Obsidian-style "create new note on dead-link click".** Dead links are visually marked and non-interactive. A future feature can make them clickable and open a "create new article" flow; this PR does not.
- **Does NOT change the compiler's prompt contract fundamentally.** The LLM still returns `backlink_suggestions: list[str]`. We add post-processing of that output. We do not ask the LLM for richer candidates (entities + relation types, semantic embeddings, etc) — that is a separate brainstorming session if ever.
- **Does NOT do fuzzy matching.** No Levenshtein, no trigrams, no edit distance. The false-positive risk in a knowledge base (where two articles can have near-identical titles and different meanings) is too high.
- **Does NOT do embedding-based matching.** Scope creep into Epic 3/5 retrieval work.
- **Does NOT retroactively fix every existing article's wikilinks on deploy.** See "Backfill strategy" below for the three options; one is picked in review.
- **Does NOT introduce a new LLM call.** Resolution is a pure function of (candidate strings, existing article titles). Zero cost, zero latency, zero network.

## Design

### Compiler post-processing pipeline

Today, `Compiler._create_article` and `Compiler._replace_article_in_place` each do: generate slug → write markdown file via `_write_article_file` → commit an `Article` row. We insert a resolution step between "compile" and "write markdown":

```text
LLM returns CompilationResult (unchanged)
        ↓
resolve_backlink_candidates(result.backlink_suggestions, session)
        ↓
(resolved: list[ResolvedBacklink], unresolved: list[str])
        ↓
_write_article_file(result, source, slug, resolved, unresolved)
        ↓
For each resolved ref: session.add(Backlink(source_article_id=new_article.id,
                                           target_article_id=ref.target_id,
                                           context=ref.candidate_text))
        ↓
commit
```

The new type:

```python
@dataclass(frozen=True)
class ResolvedBacklink:
    candidate_text: str  # What the LLM said — preserved verbatim for display
    target_id: str       # The Article.id this resolved to
    target_title: str    # The Article.title (canonical spelling, for rendering)
```

`ResolvedBacklink` is a plain dataclass in `src/wikimind/engine/wikilink_resolver.py` (new file), NOT a SQLModel and NOT stored — it is purely a resolution-pipeline carrier.

### Resolution algorithm — two stages, no fuzzy

**Stage 1: exact case-insensitive match.**

For each candidate string, look up `Article` where `LOWER(title) == LOWER(candidate)`. If exactly one match: resolve to it. If zero matches: go to Stage 2. If multiple matches (shouldn't happen today because `Article.slug` is unique but `Article.title` is not): pick the one with the earliest `created_at` — deterministic tiebreak.

**Stage 2: normalized match — the #96 fix.**

Both the candidate and every existing `Article.title` are passed through a single shared normalizer function:

```python
def normalize_title(s: str) -> str:
    """Canonicalize a title for wikilink resolution.

    Lowercases, strips non-alphanumeric characters except hyphens,
    collapses whitespace to single hyphens. Underscores become hyphens.
    Unicode is NFKD-normalized and stripped to ASCII.
    """
```

Match if `normalize_title(candidate) == normalize_title(article.title)`. Same tiebreak as Stage 1 (earliest `created_at`) if multiple articles share a normalized form.

**No Stage 3.** If both stages fail, the candidate is unresolved. That is the final answer. No Levenshtein. No "did you mean". No LLM fallback.

Rationale for no fuzzy matching: in a knowledge base, "Machine Learning" and "Machine Learning Ops" are different articles. "React" and "React Native" are different articles. Any similarity threshold tight enough to avoid false positives at that scale is tight enough to reject the same-article variants we actually want to catch, so fuzzy buys nothing over exact+normalized.

### The single normalizer — drift prevention

`normalize_title` lives in a new module `src/wikimind/engine/title_normalizer.py`. It is imported from **exactly one place**. The compiler imports it. Any future code that needs to compare titles (a runtime resolver, the knowledge graph builder, a search feature) imports it from the same module. There is no second normalizer anywhere in the codebase.

This is the #96 fix. Issue #96 exists because the frontend had one slugifier and the backend had another. The solution is not "keep them in sync" — the solution is "delete one of them". The frontend's `slugify()` helper in `ArticleReader.tsx:19-25` gets deleted entirely; there is no second implementation to diverge from.

### Storage — where do resolution results live?

**Resolved candidates become `Backlink` rows.** The existing `Backlink` model is used as-is (composite PK `(source_article_id, target_article_id)`, optional `context`). For each `ResolvedBacklink` returned by the resolver, the save path creates one `Backlink` row with:
- `source_article_id` = the new Article's ID
- `target_article_id` = `resolved.target_id`
- `context` = `resolved.candidate_text` (the raw string the LLM produced, kept for display and debugging)

Because `Backlink` uses a composite PK, duplicate (source, target) pairs are rejected by SQLite automatically — useful if a future Stage 2 refactor would otherwise emit two `Backlink` rows for two candidate strings that both resolve to the same target. The save path must catch `IntegrityError` on the composite key and skip the duplicate.

**Unresolved candidates: where do they go?** Three options considered:

| Option | Storage | Pros | Cons |
|---|---|---|---|
| **A** | JSON column on `Article` row — `unresolved_backlinks TEXT` (JSON array) | Queryable, survives round trip from disk | New schema column, new migration, one more field to keep in sync with the disk markdown |
| **B** | New `UnresolvedBacklink` table with `(article_id, candidate_text)` rows | Cleanest relational model, easy to query "what candidates never resolved across my wiki" | Whole new table for data that is essentially a TODO list, more surface for bugs, Epic 3 doesn't need it |
| **C** | **Not persisted at all.** The markdown body contains the unresolved `[[Title]]` text, the frontend renders it as a dimmed span, done. | Zero schema change. Single source of truth (the .md file). Re-compiling an article re-derives unresolved state from the same .md output. Trivial to revisit later if we decide we DO want querying. | Can't write a SQL query like "show me all dead links in the wiki" without scanning markdown files |

**Recommendation: Option C.** For a v1 that closes the loop, persisting unresolved candidates buys us nothing the markdown body doesn't already carry. The incremental-sweep backfill job (option B3 below) is the natural place to resolve old unresolved links over time — and it only needs the markdown text, not a separate table. Flagged as an open decision in case the user wants A or B for future flexibility.

### Markdown generation — the "Related" section format

Two options considered:

**Option A — custom marker syntax.** Emit `[[Title|resolved]]` vs `[[Title|unresolved]]`. Requires a custom parser on the frontend (react-markdown doesn't understand the `|resolved` suffix). Keeps Obsidian-style brackets for both cases.

**Option B — standard markdown link for resolved, Obsidian brackets for unresolved.** Emit `[Title](/wiki/<article_id>)` for resolved, `[[Title]]` for unresolved. react-markdown renders the former as a native `<a>` tag with zero custom code. The latter is picked up by a simple pre-processor on the frontend that converts unresolved `[[...]]` to a dimmed span before react-markdown ever sees it.

**Recommendation: Option B.** Standard markdown links work natively with react-markdown and remark-gfm (both already in the deps). No custom parser. No `data-wikilink` attribute hack. The only frontend code is a one-line preprocessing regex that replaces `[[Foo]]` with `<span class="wikilink-unresolved" title="not yet in wiki">Foo</span>`.

**The "Related" section is rebuilt from resolution output, not the raw LLM list.** In `_write_article_file`, the `backlinks` block becomes:

```python
# Inside _write_article_file, replacing the current line 333:
related_lines: list[str] = []
for rb in resolved_backlinks:
    related_lines.append(f"- [{rb.candidate_text}](/wiki/{rb.target_id})")
for text in unresolved_backlinks:
    related_lines.append(f"- [[{text}]]")
backlinks = "\n".join(related_lines)
```

The resolved-link URL uses the **article ID**, not the slug. This is the permanent sidestep of issue #96: the slug is no longer a public identifier that travels through markdown → frontend → backend. The ID is. Slugs remain the human-facing part of the URL bar (via the `/wiki/{id_or_slug}` route below), but they no longer appear in article bodies.

### Backend: article lookup accepts ID or slug

The existing `WikiService.get_article(slug)` at `services/wiki.py:177` is modified to try ID first, then fall back to slug:

```python
async def get_article(self, id_or_slug: str, session: AsyncSession) -> ArticleResponse:
    # Try ID first (UUID format, set by default_factory in the model)
    result = await session.execute(select(Article).where(Article.id == id_or_slug))
    article = result.scalar_one_or_none()
    if article is None:
        # Fall back to slug — preserves backward compat with existing bookmarks
        result = await session.execute(select(Article).where(Article.slug == id_or_slug))
        article = result.scalar_one_or_none()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    # ... rest unchanged
```

The route path parameter is renamed from `slug` to `id_or_slug` for clarity; the URL pattern stays the same (`/wiki/articles/{id_or_slug}`). No new route is added. This is a pure superset — any existing slug-based URL continues to work, and any new ID-based URL from a resolved wikilink also works.

### Frontend changes

`apps/web/src/components/wiki/ArticleReader.tsx`:

1. **Delete the local `slugify()` helper** (lines 19-25). No replacement. The frontend no longer slugifies anything.
2. **Delete the `data-wikilink` attribute hack** in `preprocessMarkdown` (lines 36-39). Replace with a simpler preprocessor that only handles unresolved brackets:
   ```typescript
   function preprocessMarkdown(content: string): string {
     return content
       .replace(FRONTMATTER_REGEX, "")
       .replace(WIKILINK_REGEX, (_, target: string) => {
         const safe = escapeHtml(target.trim());
         return `<span class="wikilink-unresolved" title="Article not yet in wiki">${safe}</span>`;
       });
   }
   ```
3. **Simplify the custom anchor renderer** (lines 77-101). The `wikilink` branch is deleted. Resolved wikilinks now arrive as ordinary `<a href="/wiki/{id}">` tags produced by react-markdown from `[text](/wiki/{id})`. The only custom logic left is the `target="_blank"` for external links, which is still needed for `http://` hrefs but NOT for `/wiki/…` hrefs — the renderer detects internal vs external by path prefix.
4. **Internal links use React Router `<Link>`**, not raw `<a>`, so navigation is client-side. The check is `href?.startsWith("/wiki/")`.
5. **Add a small CSS rule** for `.wikilink-unresolved`: dim color, dotted underline, `cursor: help` (or similar). Lives in the Tailwind class via an `@apply` directive, or inline via a Tailwind class string, matching the existing style conventions for `apps/web/src/index.css`.

The result: `ArticleReader.tsx` shrinks. Fewer lines, fewer moving parts, and the resolved-link path runs through a standard react-markdown render with zero custom attribute plumbing.

### Backfill strategy — the architectural decision flagged for the user

This is the one design call I am explicitly NOT making in this spec. Three options, each with different PR-level impact:

#### Option B1 — Re-compile every existing article on next deploy

Walk every `Article` row, re-run the compiler on the original `Source`, let the normal save path produce resolved wikilinks and `Backlink` rows.

- **Pro:** Clean knowledge graph on day one. Every link is either resolved or consciously unresolved.
- **Con:** LLM cost (every article re-compiled). `updated_at` timestamps change on every row. `content_hash` / provider-based deduplication fingerprints may invalidate. Users see the entire wiki "refresh" with no visible benefit to most articles.
- **PR-level impact:** +1 new job in `src/wikimind/jobs/`, +1 startup hook (or manual admin endpoint). Testing surface grows. Not small.

#### Option B2 — Forward only

New articles get real backlinks. Existing articles keep their unresolved `[[Title]]` text until they happen to be re-ingested for another reason.

- **Pro:** Zero disruption. Zero LLM cost. Deterministic. Simplest possible rollout.
- **Con:** The knowledge graph starts sparse (Epic 3's graph view shows near-empty edges for the first week or two). Existing articles' "Related" sections stay broken forever for users who never re-ingest.
- **PR-level impact:** Zero. This is the "do nothing extra" option.

#### Option B3 — Incremental resolution sweep (recommended long term)

Add a background job `wikilink_resolution_sweep` (new file in `src/wikimind/jobs/`) that walks existing articles, reads each `.md` file, finds the `[[Title]]` tokens, runs them through the exact same `resolve_backlink_candidates()` function, and — if resolution succeeds now for a link that used to be unresolved — rewrites that one line in the .md file AND creates a `Backlink` row. No LLM call. Pure deterministic resolution against the current `Article` table.

- **Pro:** Eventually-consistent knowledge graph. No LLM cost. Re-runnable on a timer (e.g. every ingestion, or nightly). When a user adds an article titled "Quantum Computing", every prior article that linked `[[Quantum Computing]]` as unresolved gets its link upgraded automatically on the next sweep.
- **Con:** Most code of the three options. New job, new tests, new scheduling decision. May miss nuanced context the LLM had when it originally produced the candidate (but since we're only promoting EXACT and NORMALIZED matches, "nuance" shouldn't matter).
- **PR-level impact:** Moderate. New job module, new tests, a small hook in the ingest-complete signal. But orthogonal to this spec's main work — the sweep job can be a separate follow-up PR.

**Recommendation: B3 as the right long-term answer.** Best of both: no disruption at deploy time, no LLM cost, and the graph fills in as the wiki grows without any user action. But it is the most code, and it is reasonable to ship **B2 in this PR** and file B3 as a follow-up issue.

**Flagged as user-facing decision** in the open-decisions section below.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| **Client-side resolution** — fetch the full article list once, do title matching in JS | Doesn't scale past a few hundred articles (pulls the entire article index on every article render). Keeps the render-time resolution bug — the fix needs to happen at compile time so that `Backlink` rows get created. |
| **LLM-in-the-loop resolution** — ask the LLM "which of these existing articles does this link refer to" | Too expensive (one LLM call per wikilink per article), too slow (compile time doubles), and introduces non-determinism into a step that should be pure. |
| **Fuzzy matching with Levenshtein or trigrams** | False-positive risk is too high for a knowledge base. "React" → "React Native" looks fuzzy-close and is semantically distinct. Any threshold tight enough to avoid that is equivalent to exact match. |
| **Embedding-based matching** | Scope creep into Epic 3 (graph building) and Epic 5 (retrieval overhaul). Also introduces a dependency on the embedding model being stable across runs. Reconsider when embeddings land for retrieval anyway. |
| **Change the prompt contract to ask the LLM for structured entities + relation types** | Much bigger change. Requires a Pydantic schema change, prompt validation updates, and retraining every downstream code path that consumes `CompilationResult`. Does not address the core bug (which is post-processing, not prompt quality). |
| **Drop the `[[Title]]` syntax and stop producing wikilinks altogether** | Loses the entire "related concepts" affordance in the reader. The feature is user-valuable when it works. |

## Consequences

**Enables:**

- Real `Backlink` rows in the database on every new compile. Epic 3's knowledge graph view becomes feasible; `WikiService.get_graph` stops returning an empty edge set.
- Obsidian-style dead-link UX. Users can see what's missing from the wiki and know which concepts the LLM is waiting for them to document.
- Deterministic, testable resolution. No flaky "sometimes it matches" behavior.
- A clean slug-or-ID lookup on the backend. External bookmarks to slugs still work; new internal links use stable IDs.

**Constrains:**

- New articles with novel titles create temporary dead links until a future article fills the gap. Acceptable — the dead links are visually distinct, not silent 404s.
- The normalizer is now a piece of critical infrastructure. Changing it changes which links resolve, which could cause spurious churn in `Backlink` rows. Mitigation: the normalizer's tests cover all edge cases (unicode, underscores, apostrophes, long titles), and any future change must preserve the contract or bump a version.

**Risks:**

- **Title normalizer drift** — if a second normalizer appears anywhere in the codebase, the bug from #96 comes back in a new disguise. Mitigation: single function in a single module, imported from exactly one place. A lint rule or a grep check in CI could enforce "only `title_normalizer.py` implements title normalization".
- **Duplicate `Backlink` rows** — two candidates ("React" and "react") both resolve to the same target. The composite PK prevents inserting duplicates, but the save path must catch `IntegrityError` and skip. Covered by a test.
- **Backfill strategy choice affects rollout** — B2 means existing wikis stay broken until the user decides to act. B3 ships the fix but needs more code. The user decides.
- **A candidate that resolves to the CURRENT article** — e.g. the LLM suggests a backlink to the article it's currently compiling. The resolver must filter this out (a self-loop is not a meaningful backlink). Covered by a test. Note that at save time the article does not yet have an ID, so this is enforced by: (a) passing the new article's eventual ID/title into `resolve_backlink_candidates`, or (b) filtering `where Article.id != new_article.id` inside the resolver. Implementation detail for the plan.

## Open decisions for the user

1. **Backfill strategy: B1, B2, or B3?**
   - B1 = re-compile all existing articles (LLM cost, disruption, cleanest graph)
   - B2 = forward only, ship this PR as-is (no cost, graph fills in slowly as users re-ingest)
   - **B3 = incremental sweep job (recommended long term; most code)**
   - Suggestion: **ship B2 in this PR, file B3 as a follow-up issue.** Clean separation, no blocker.

2. **Persist unresolved backlinks?**
   - Option A: JSON column on Article — queryable but adds schema.
   - Option B: New `UnresolvedBacklink` table — cleanest model, more surface.
   - **Option C: not persisted — the markdown body IS the record. (Recommended.)**

3. **Should the compiler prompt contract change to ask for richer candidates (entities + relation types)?**
   - Probably no — the existing `backlink_suggestions` list is adequate for the resolution pipeline and the LLM doesn't need to know about article IDs or link types. But worth explicitly confirming.

4. **Should the unresolved-link span style be purely visual, or should it trigger a "propose to add this article" affordance?**
   - v1 should be visual only — dim, non-clickable, tooltip. A "propose new article" flow is a separate feature and expands scope.

5. **Route parameter rename.** The existing route `GET /wiki/articles/{slug}` (and its service method) gets its path parameter renamed from `slug` to `id_or_slug`. This is a documentation change — no URL pattern change — but `docs/openapi.yaml` will be regenerated. Confirm that's acceptable; it is the intended meaning.

## Related issues

- **#95** — closed by this work (primary fix).
- **#96** — subsumed and closed by this work (no more second slugifier to drift against).
- **Epic 3 (knowledge graph view)** — unblocked by this work. The first compile after this PR ships produces real `Backlink` rows, and `WikiService.get_graph` will return a populated edge list for the first time.
- **Follow-up issue (to be filed):** incremental `wikilink_resolution_sweep` job — option B3 from the backfill section. Scope-separated into its own PR so the main fix can ship immediately.
