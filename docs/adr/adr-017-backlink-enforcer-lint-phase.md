# ADR-017: Backlink enforcer as lint Phase 3 with auto-repair

## Status

Accepted

## Context

The backlink enforcer (`engine/backlink_enforcer.py`) exists as standalone logic that checks structural integrity of the knowledge graph. However, it was not wired into any production pipeline.

The lint pipeline already runs Phase 1 (contradiction detection) and Phase 2 (orphan detection). The enforcer's checks are complementary.

## Decision

Wire `enforce_backlinks()` into the lint pipeline as **Phase 3**. The enforcer:

1. Runs on every article during a lint pass.
2. Reports violations as `StructuralFinding` rows linked to the `LintReport`.
3. Auto-repairs missing inverse links (`auto_repaired=True`).
4. Reports non-repairable issues for manual resolution.

## Alternatives Considered

- **Report-only**: Rejected. Missing inverses are deterministic fixes.
- **Silent auto-fix**: Rejected. Users should see what changed.
- **Compile-time only**: Rejected. Misses violations from manual edits.

## Consequences

- Lint runs include Phase 3 with O(N) lightweight queries.
- Missing inverse links auto-repaired during lint.
- New `StructuralFinding` table with `violation_type`, `auto_repaired`, `detail`.
- `LintReport` gains `structural_count` and `checked_articles`.
- Health Dashboard gains "Structural" tab.
- Orphan check removed from enforcer (handled by Phase 2).
