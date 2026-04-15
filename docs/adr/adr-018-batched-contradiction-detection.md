# ADR-018: Batched Contradiction Detection

**Status:** Accepted
**Date:** 2026-04-15
**Issue:** [#138](https://github.com/manavgup/wikimind/issues/138)

## Context

The wiki linter's contradiction detection makes one LLM API call per article pair. For a concept with 18 pairs this means 18 sequential calls, each with request overhead, totalling ~90 seconds. The per-call cost is dominated by system-prompt repetition and round-trip latency rather than token volume.

## Decision

Batch N article pairs (default 4, configurable via `WIKIMIND_LINTER__CONTRADICTION_BATCH_SIZE`) into a single LLM prompt. The batch prompt includes all pair sections with indexed labels (`Pair 0`, `Pair 1`, ...) and asks the model to return a JSON array of per-pair result objects keyed by `pair_index`.

### Retry and fallback strategy

1. If the batch LLM call fails, retry once with the same prompt.
2. If the retry also fails, fall back to individual per-pair `_compare_article_pair()` calls for every pair in the batch. This guarantees that a malformed batch response never silently drops pairs.

### Cache granularity

Per-pair cache entries (`LintPairCache`) are preserved. After a successful batch call, each pair's contradictions are saved individually so future runs can skip already-checked pairs even if the batch composition changes.

### Progress reporting

`report.checked_pairs` is incremented per-pair within each batch (not per-batch), giving the frontend smooth progress updates.

### Configuration

Two new fields on `LinterConfig`:

- `contradiction_batch_enabled` (default `true`) -- feature flag
- `contradiction_batch_size` (default `4`) -- pairs per batch

When `contradiction_batch_enabled` is `false`, or when only one uncached pair remains, the existing per-pair path is used.

## Alternatives Considered

- **No fallback on failure**: Rejected. A single malformed batch response would lose all pairs in that batch with no recovery.
- **Batch-level cache**: Rejected. Batch composition varies between runs; per-pair granularity avoids redundant rechecking.
- **Concurrent batches**: Deferred. Sequential batches are simpler and respect rate limits. Concurrency can be layered on later if latency is still a concern.

## Consequences

- ~4x reduction in LLM API calls for contradiction detection (N pairs / batch_size).
- Slightly larger per-call token usage (system prompt shared across pairs offsets this).
- Fallback path adds resilience at the cost of reverting to O(pairs) calls when the batch model response is unparseable.
