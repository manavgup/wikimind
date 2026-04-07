# Duplicate-Source Handling Design

**Date:** 2026-04-07
**Status:** Approved (Option A — Minimal)
**Author:** Brainstorming session with empirical testing

## Context

WikiMind ingests sources (PDFs, URLs, text, YouTube transcripts) and compiles each into a structured wiki article via an LLM. The current pipeline has **zero deduplication logic anywhere** — every ingest creates a new `Source` UUID, and every compile creates a new `Article` row with an auto-generated slug.

This bit us during testing: a user ingested three IBM Sovereign Core PDFs, switched the active LLM provider from Claude Sonnet 4.5 to GPT-4o, and re-ingested the same three PDFs. The wiki ended up with 11 articles, 6 of which were duplicate compilations of the same 3 source documents. Article slugs avoided collision only because the two compilers happened to pick slightly different titles. If they had agreed on a title, the second compile would have crashed on the `Article.slug unique=True` constraint.

User asked: **does duplication of content actually affect quality of response?** Before designing a fix, we ran a controlled empirical test.

## Empirical evidence

### Test setup

Three-phase controlled measurement against the question:
> "What is IBM POV on Digital sovereignty and how does IBM solution technically ensure sovereignty and control over the data?"

GPT-4o was the active LLM provider for all three phases (constant), only the corpus composition varied. Articles were "hidden" from retrieval by appending `.HIDDEN` to their `file_path` so `_read_article_content` returned `None` and the QA agent's term-overlap scorer skipped them. Database state restored after the test.

| Phase | Visible articles | Sources QA cited | Answer length | Confidence |
|---|---|---|---|---|
| **1. Mixed (Claude + GPT-4o)** | 11 total, 6 sov-related | **3 — all Claude-compiled** | 1,255 chars | high |
| **2. Claude-only** | 8 total, 3 sov | 3 (Claude) | 1,049 chars | high |
| **3. GPT-4o-only** | 8 total, 3 sov | 3 (GPT-4o) | 1,501 chars | high |

### What the data showed

1. **The mixed corpus produced essentially the same answer as Claude-only.** Even with all 6 sovereignty articles available, the keyword-based retrieval scored Claude's articles higher (richer text, more keyword density) and selected them for the top-3 context. The GPT-4o duplicates were silently ignored. The QA agent never saw 6 articles — it saw the same 3 Claude articles as the Claude-only phase.

2. **GPT-4o-only produced the LONGEST answer (1,501 chars).** Counterintuitive — but with thinner source material to draw from, the QA agent elaborated more from its own pre-training knowledge. **This is a quality red flag**: longer answer from weaker sources implies more model hallucination risk.

3. **All three phases captured the core IBM POV**, including the framing "architectural vs contractual" which is central to the IBM messaging. They paraphrased differently but were factually equivalent.

4. **The bigger quality lever is which compiler wrote the source articles, not whether duplicates exist.** Claude → richer compiled articles → richer Q&A. GPT-4o → terser compiled articles → more elaboration from model knowledge.

5. **The retrieval system already self-dedupes by quality.** Better-written articles win. Duplicates only become a real problem if two compiles produce equally-strong articles competing for the same top-5 slots — the **pathological same-compiler case** which we did NOT test but which would create real waste.

### Implications

The original framing — "should re-compiling a source replace the old article or keep both?" — turned out to be partly wrong. The actual problems we observed are:

- **Storage bloat** — 6 article files for 3 source PDFs. Real but minor (~12KB per article).
- **UI clutter** — wiki shows two cards with nearly identical titles for the same source. **The main user-visible problem.**
- **Pathological same-compiler dupes** (untested) — re-running the exact same compiler on the same source would produce two articles with virtually identical content. Both would score equally on keyword retrieval. Both would consume top-5 slots. Real retrieval waste.
- **Synthesis crowd-out at scale** (untested) — in a wiki with hundreds of articles, dupes might compete for top-5 retrieval slots and squeeze out adjacent topics. Not a problem at our 11-article test scale.

The "merge articles from different compilers" instinct is wrong. Different compilers produce genuinely different artifacts with different voices. Claude's "architectural sovereignty enforced through customer-operated control planes" is not the same artifact as GPT-4o's "control and sovereignty over AI and cloud environments" even though they describe the same underlying source. Merging would lose information.

## Goals

1. Eliminate the user-visible duplicate cards in the wiki UI
2. Prevent the pathological same-compiler waste case
3. Preserve the ability to compare different LLM providers' compilations side-by-side
4. Minimal schema and code changes — this is a single-user MVP, not a versioning system
5. Don't preclude a future versioning/history system if we need one later

## Non-goals

- **Not a versioning system.** No `v1`, `v2`, no audit trail of past compilations. If you re-compile with the same provider, the old article is gone.
- **Not a merge/synthesis system.** Articles from different compilers stay as separate artifacts.
- **Not a freshness detector.** No automatic re-compile when URL content drifts. (Phase 4+ feature with the linter.)
- **Not multi-tenant safe.** Single-user assumption.

## Design — Option A: Source dedup + replace-by-compiler

### Two new columns

```python
# src/wikimind/models.py
class Source(SQLModel, table=True):
    # ... existing fields
    content_hash: str | None = Field(default=None, index=True)  # sha256 hex of raw bytes

class Article(SQLModel, table=True):
    # ... existing fields
    provider: Provider | None = None  # which LLM compiled this
```

`content_hash` is `sha256` of the raw bytes for binary sources (PDFs) or the UTF-8 encoded text for text sources. Indexed because we look it up on every ingest.

`provider` is the LLM that produced the article. Used to decide whether re-compiling replaces in place or creates a new article.

### Ingest-time dedup

In each adapter (`URLAdapter`, `PDFAdapter`, `TextAdapter`, `YouTubeAdapter`) in `src/wikimind/ingest/service.py`:

```python
# After fetching/extracting content but before creating Source row
content_hash = hashlib.sha256(file_bytes).hexdigest()

existing = await session.execute(
    select(Source).where(Source.content_hash == content_hash)
)
existing_source = existing.scalar_one_or_none()
if existing_source:
    log.info("Source dedup hit", existing_id=existing_source.id, hash=content_hash[:16])
    return existing_source  # caller skips compilation enqueue
```

The `IngestService` (`src/wikimind/services/ingest.py`) detects when the adapter returned an existing source (e.g., the source has `compiled_at` set or has at least one Article) and **skips** calling `BackgroundCompiler.schedule_compile()`. The user gets the existing Source ID back, the existing article remains visible, no LLM call is wasted.

### Compile-time replace

In `Compiler.save_article()` in `src/wikimind/engine/compiler.py`:

```python
# Determine which provider just compiled this
provider = self.router.last_used_provider  # set by LLMRouter on each call

# Check if an article already exists for this (source, provider) pair
existing = await session.execute(
    select(Article).where(
        Article.provider == provider,
        Article.source_ids.contains(f'"{source.id}"'),
    )
)
existing_article = existing.scalar_one_or_none()

if existing_article:
    # Replace in place — keep slug, update content
    Path(existing_article.file_path).unlink(missing_ok=True)
    new_path = self._write_article_file(result, source, existing_article.slug)
    existing_article.title = result.title
    existing_article.summary = result.summary
    existing_article.confidence = self._overall_confidence(result)
    existing_article.concept_ids = self._serialize_concepts(result.concepts)
    existing_article.updated_at = datetime.utcnow()
    session.add(existing_article)
    await session.commit()
    return existing_article

# No existing article for this provider — create new
slug = self._generate_unique_slug(result.title)
article = Article(
    slug=slug,
    title=result.title,
    file_path=str(self._write_article_file(result, source, slug)),
    confidence=self._overall_confidence(result),
    summary=result.summary,
    source_ids=f'["{source.id}"]',
    concept_ids=self._serialize_concepts(result.concepts),
    provider=provider,
)
session.add(article)
# ... rest of existing code
```

The `LLMRouter` needs a small change to expose `last_used_provider` (the provider that was actually used in the most recent `complete()` call, accounting for fallback). Currently this is logged but not exposed.

### Behavior matrix

| Scenario | Before this change | After this change |
|---|---|---|
| Ingest same PDF twice | 2 Source records, 2 compilations, 2 articles | 1 Source record, 1 compilation, 1 article |
| Re-trigger compile, same provider | 2 articles for the same source, slug collision risk | Existing article replaced in place, same slug |
| Compile with Claude, then with GPT-4o | 2 articles (different titles, no link to source) | 2 articles (one per provider, both retrievable) |
| Re-compile with Claude after switching back | 3 articles total | 2 articles total (Claude article replaced, GPT-4o article preserved) |
| Same URL re-ingested, content unchanged | New Source, new compile | Source dedup hit, no new work |
| Same URL re-ingested, content changed | New Source, new compile | New Source (different hash), new compile (correct behavior — content actually changed) |

### Critical files to modify

- `src/wikimind/models.py` — add `content_hash` to Source, `provider` to Article
- `src/wikimind/ingest/service.py` — content hashing + dedup check in all 4 adapters
- `src/wikimind/services/ingest.py` — skip enqueue when dedup hit
- `src/wikimind/engine/compiler.py` — replace-by-provider logic in `save_article()`
- `src/wikimind/engine/llm_router.py` — expose `last_used_provider`
- `src/wikimind/jobs/worker.py` — no changes needed (worker calls `compile()` and `save_article()` which handle the logic)
- `tests/unit/test_ingest_dedup.py` — new
- `tests/unit/test_compile_replace.py` — new
- `tests/unit/test_compile_stack_providers.py` — new

### Migration

Add the columns with safe defaults:
```sql
ALTER TABLE source ADD COLUMN content_hash TEXT;
CREATE INDEX ix_source_content_hash ON source (content_hash);
ALTER TABLE article ADD COLUMN provider TEXT;
```

One-time backfill script (`scripts/backfill_dedup_fields.py`):
1. Walk all `Source` rows. For each, read the file at `file_path`, compute sha256, write to `content_hash`. Skip if file is missing.
2. Walk all `Article` rows. Provider can't be inferred from existing data — leave as `NULL`. New compiles will populate it. Stale articles without a provider will still work; the replace-by-provider check will treat `provider IS NULL` as "no match" and create a new article.

This is intentional — old articles get superseded the first time their source is recompiled, which is fine for our test wiki. For a production deployment we could be smarter (e.g., assume all pre-migration articles are from the configured default provider), but YAGNI.

### Tests

| Test | What it verifies |
|---|---|
| `test_ingest_dedup_text_same` | Pasting the same text twice returns the same Source ID, no second file written |
| `test_ingest_dedup_pdf_same` | Uploading the same PDF twice returns the same Source ID |
| `test_ingest_no_dedup_different_content` | Different PDFs produce different Source IDs |
| `test_ingest_dedup_url_unchanged` | Re-ingesting a URL whose content didn't change returns the same Source ID |
| `test_compile_replace_same_provider` | Recompiling with the same provider replaces the existing Article in place (same id, updated content) |
| `test_compile_stack_different_providers` | Compiling with Claude then GPT-4o creates two Articles linked to the same Source |
| `test_qa_after_replace` | After replace, QA retrieval finds the new content, not the old |
| `test_existing_tests_still_pass` | The 30 existing tests continue passing |

### Edge cases

| Case | Handling |
|---|---|
| sha256 collision | Practically impossible (2^256). Don't handle. |
| Source file deleted from disk after ingest | Hash is in DB row, dedup still works on subsequent ingest. Compile would fail (but that's an existing problem, not introduced by this change). |
| Two ingests racing on the same content | One wins, the other's dedup check returns the winner. No locking needed. |
| Same source compiled by Anthropic Sonnet 4.5 then Anthropic Haiku 4.5 | Same provider (`Provider.ANTHROPIC`), so the second one replaces the first. **Limitation**: provider granularity is per-vendor, not per-model. Acceptable for v1; can be tightened later if needed. |
| User wants to keep an old article around for reference before re-compiling | Not supported. They can manually copy the `.md` file out before re-compiling. |
| Article.source_ids is a list (multi-source articles) | The `contains` check looks for the source UUID anywhere in the JSON string. Works for both single and multi-source articles. |
| Provider changed mid-compilation via LLM router fallback | Use the actual final provider (`router.last_used_provider`), not the requested one. Otherwise replace logic gets confused. |

## What this is NOT (restated for clarity)

- Not a versioning system — no `v1`, `v2`, no history
- Not a merge/synthesis system — different-provider articles stay separate
- Not a freshness detector — no auto re-compile on URL drift
- Not multi-tenant safe — single-user assumption
- Not perfect — provider granularity is vendor-level (Anthropic vs OpenAI), not model-level (Sonnet vs Haiku)

## Why not Options B or C?

**Option B (versioned compilations with history table)** was considered. It adds a `CompilationVersion` table and lets the user pick which version is "active" for a given Source. Pros: full audit trail, supports prompt iteration A/B testing. Cons: schema migration, requires UI work for the version switcher (which #17/#18 don't have), more complexity. The empirical test showed synthesis quality isn't the problem at our scale, so the audit trail buys us nothing today.

**Option C (full provenance graph with freshness tracking)** was considered for completeness. Tracks URL content over time, detects drift, prompts for re-compile, supports cross-source synthesis with versioned source bindings. This is a Phase 4+ feature when the linter and freshness detection become priorities. Scope creep for v1.

Option A is forward-compatible with both. The `content_hash` and `provider` fields don't preclude adding `CompilationVersion` later if we discover we need it.

## Verification

Before merging the implementation PR:

```bash
# Backend gates
make verify  # ruff, format, mypy, basedpyright, pydocstyle, all 30+ tests pass

# Empirical regression test (manual)
make dev  # restart server with new code
rm -f ~/.wikimind/db/wikimind.db  # fresh DB

# Test 1: ingest dedup
curl -X POST localhost:7842/ingest/text -d '{"content":"Hello world","title":"Greeting"}'
# → Returns source A
curl -X POST localhost:7842/ingest/text -d '{"content":"Hello world","title":"Greeting"}'
# → Returns same source A (dedup hit)
curl localhost:7842/ingest/sources | jq 'length'
# → 1 (not 2)

# Test 2: compile replace
curl -X POST localhost:7842/ingest/pdf -F 'file=@some.pdf'
sleep 30  # wait for compile
curl localhost:7842/wiki/articles | jq 'length'
# → 1
# Re-trigger compile manually via /jobs/compile/{source_id}
curl -X POST localhost:7842/jobs/compile/{source_id}
sleep 30
curl localhost:7842/wiki/articles | jq 'length'
# → 1 (still — replaced in place, not stacked)

# Test 3: stack across providers
# (Switch provider via WIKIMIND_LLM__DEFAULT_PROVIDER, restart server)
curl -X POST localhost:7842/jobs/compile/{source_id}
sleep 30
curl localhost:7842/wiki/articles | jq 'length'
# → 2 (different providers stacked)
```

## Open questions

None. The user has approved Option A and the empirical test answered the underlying question about whether duplication affects quality.

## References

- Empirical test data: stored in plan file `/Users/mg/.claude/plans/graceful-rolling-wand.md`
- ADR-002: ARQ + fakeredis (mentions the compilation flow)
- ADR-003: Multi-provider LLM router (provider abstraction this design depends on)
- ADR-009: Decoupled ingest from compilation (this design lives entirely on the compile side)
- VISION.md "Privacy & Data Model" section: "Export everything, anytime, as plain text — no lock-in" (no audit trail need at our scale)
