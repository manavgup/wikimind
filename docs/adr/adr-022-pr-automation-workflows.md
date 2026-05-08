# ADR-022: PR automation workflows with Claude-in-CI

## Status

Accepted

## Context

WikiMind is primarily developed by a single contributor using Claude Code for
feature development. PRs are created by subagents in worktrees and merged after
local verification. This workflow has two friction points:

1. **Review feedback requires manual context-switching.** When a reviewer (human
   or CI bot) leaves comments, the developer must re-read the PR, understand
   each comment, switch to the branch, make changes, and push — even for
   straightforward fixes.

2. **Branch hygiene degrades over time.** Merged branches are not auto-deleted
   (`delete_branch_on_merge` is off), open PRs fall behind main and need
   rebasing, and stale PRs accumulate without intervention.

## Decision

Add four GitHub Actions workflows to automate the PR lifecycle:

### 1. Claude Review Address (`claude-review-address.yml`)

Uses `anthropics/claude-code-action@v1` to respond to `@claude` mentions in
PR comments and reviews. Claude reads the feedback, checks out the branch,
and pushes fix commits. This is opt-in per comment — only activates on
explicit mention.

### 2. Auto-Rebase (`auto-rebase.yml`)

Triggers on push to `main`. Iterates over all open PRs, rebases each onto
the updated main branch using `--force-with-lease`. PRs with merge conflicts
are labeled `needs-rebase` instead.

### 3. Post-Merge Sweep (`post-merge-sweep.yml`)

Triggers on PR merge. Deletes the head branch and resolves any outstanding
review threads via the GraphQL API. This compensates for
`delete_branch_on_merge` being disabled.

### 4. Prune Stale (`prune-stale.yml`)

Runs weekly on a cron schedule. Labels PRs with no activity for 21+ days as
`stale`, closes them at 30 days, and deletes remote branches whose PRs have
already been merged.

## Consequences

**Positive:**
- Review feedback can be addressed without manual context-switching
- Open PRs stay rebased on main automatically
- Branch count stays bounded without manual cleanup
- Stale PRs are surfaced and eventually closed

**Negative:**
- Claude review-address consumes API credits per invocation
- Auto-rebase force-pushes, which can disrupt collaborators working on the
  same branch (acceptable for single-contributor workflow)
- Resolved review threads may hide feedback that warranted manual attention

**Mitigations:**
- Review-address is opt-in (requires `@claude` mention)
- Auto-rebase uses `--force-with-lease` to prevent overwriting unexpected changes
- Post-merge sweep only resolves threads on *merged* PRs — open PRs are untouched
