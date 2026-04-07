#!/usr/bin/env python3
"""Co-change rule engine: verify docs are updated alongside code.

Reads `.docs-sync.yaml` at the repo root for rules of the form:

    - name: ...
      when_changed: ["glob1", "glob2"]
      when_diff_contains: ["regex1"]   # optional
      require_changed: ["docs/foo.md"]  # all-of
      require_one_of: ["docs/adr/*.md"]  # any-of
      severity: error | warning | info
      fix_hint: "..."

The script compares the current diff against these rules and reports
violations. It supports two modes:

- Pre-commit mode (default): uses `git diff --cached` (staged changes).
- CI mode: use `--base BASE_REF` to diff `BASE_REF..HEAD`.

Escape hatches:
- Include the configured marker (default `[skip-doc-check]`) in the most
  recent commit message to bypass all rules.
- The CI workflow handles the PR label escape hatch (`docs-skip`) directly.

Examples:
    python scripts/check_doc_sync.py
    python scripts/check_doc_sync.py --base origin/main
    python scripts/check_doc_sync.py --verbose
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pathspec
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = REPO_ROOT / ".docs-sync.yaml"

SEVERITY_ICONS = {
    "error": "ERROR",
    "warning": "WARN ",
    "info": "INFO ",
}


@dataclass
class Rule:
    """A single co-change rule."""

    name: str
    when_changed: list[str]
    when_diff_contains: list[str] = field(default_factory=list)
    require_changed: list[str] = field(default_factory=list)
    require_one_of: list[str] = field(default_factory=list)
    severity: str = "error"
    fix_hint: str = ""


@dataclass
class Violation:
    """A single violation of a rule."""

    rule: Rule
    triggered_by: list[str]
    missing: list[str]


def load_config(path: Path) -> tuple[list[Rule], dict[str, Any]]:
    """Load rules and escape-hatch config from YAML.

    Args:
        path: Path to `.docs-sync.yaml`.

    Returns:
        A `(rules, escape_hatches)` tuple.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw_rules = data.get("rules", []) or []
    escape = data.get("escape_hatches", {}) or {}

    rules: list[Rule] = []
    for raw in raw_rules:
        rules.append(
            Rule(
                name=raw["name"],
                when_changed=list(raw.get("when_changed", [])),
                when_diff_contains=list(raw.get("when_diff_contains", [])),
                require_changed=list(raw.get("require_changed", [])),
                require_one_of=list(raw.get("require_one_of", [])),
                severity=raw.get("severity", "error"),
                fix_hint=raw.get("fix_hint", ""),
            )
        )
    return rules, escape


def run_git(args: list[str]) -> str:
    """Run a git command and return stdout as a string.

    Args:
        args: Arguments passed to `git` (excluding the program name).

    Returns:
        The captured stdout, with a trailing newline stripped.
    """
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.rstrip("\n")


def get_changed_files(base: str | None) -> list[str]:
    """Return the list of changed files for the current diff.

    Args:
        base: Optional base ref to diff against. When omitted, uses staged
            changes (pre-commit mode).

    Returns:
        A list of repo-root-relative file paths.
    """
    output = run_git(["diff", "--name-only", f"{base}..HEAD"]) if base else run_git(["diff", "--cached", "--name-only"])
    return [line for line in output.splitlines() if line.strip()]


def get_diff_text(base: str | None) -> str:
    """Return the full diff text for the current change set.

    Args:
        base: Optional base ref; same semantics as `get_changed_files`.

    Returns:
        The full unified diff as a single string.
    """
    if base:
        return run_git(["diff", f"{base}..HEAD"])
    return run_git(["diff", "--cached"])


def get_diff_for_files(base: str | None, files: list[str]) -> str:
    """Return the diff restricted to the given files.

    Used by `when_diff_contains` matching so a rule's content regex
    only sees the diff of the files that triggered the rule, not
    unrelated changes elsewhere in the same PR (e.g. an OpenAPI
    YAML diff incidentally matching a Python schema regex).

    Args:
        base: Optional base ref; same semantics as `get_diff_text`.
        files: Subset of changed files to scope the diff to.

    Returns:
        The unified diff text for `files` only, or empty string if
        `files` is empty.
    """
    if not files:
        return ""
    if base:
        return run_git(["diff", f"{base}..HEAD", "--", *files])
    return run_git(["diff", "--cached", "--", *files])


def last_commit_message() -> str:
    """Return the subject+body of the most recent commit, or an empty string."""
    return run_git(["log", "-1", "--format=%B"])


def commit_message_has_marker(message: str, marker: str) -> bool:
    """Return True when `marker` appears as its own line in `message`.

    We require the marker to be on its own line so that commit messages that
    merely describe the escape hatch (e.g. documentation of the doc-sync
    infrastructure itself) do not accidentally bypass the check. Leading and
    trailing whitespace are tolerated, but surrounding text is not.

    Args:
        message: Full commit message (subject + body).
        marker: The escape-hatch token, e.g. `[skip-doc-check]`.

    Returns:
        True if any line in `message` equals `marker` after stripping.
    """
    if not marker:
        return False
    return any(line.strip() == marker for line in message.splitlines())


def match_any(patterns: list[str], files: list[str]) -> list[str]:
    """Return files matching any of the given glob patterns.

    Uses `pathspec` with gitwildmatch semantics so that `**/*.py` and
    directory prefixes work as expected.

    Args:
        patterns: Glob patterns (gitwildmatch style).
        files: Candidate file paths relative to the repo root.

    Returns:
        The subset of `files` matching at least one pattern.
    """
    if not patterns:
        return []
    spec = pathspec.GitIgnoreSpec.from_lines(patterns)
    return [f for f in files if spec.match_file(f)]


def diff_contains(diff: str, patterns: list[str]) -> bool:
    """Check whether any of `patterns` match the diff text.

    Args:
        diff: The full diff text.
        patterns: Regular expression patterns.

    Returns:
        True if at least one pattern matches anywhere in the diff.
    """
    if not patterns:
        return True
    return any(re.search(pattern, diff, re.MULTILINE) for pattern in patterns)


def evaluate_rule(rule: Rule, changed: list[str], base: str | None) -> Violation | None:
    """Evaluate a single rule against the current diff.

    `when_diff_contains` patterns are matched only against the diff of
    files that triggered the rule (`when_changed` matches), so a regex
    written for one file type cannot accidentally match content in
    unrelated files (e.g. an OpenAPI YAML diff matching a Python regex).

    Args:
        rule: The rule to evaluate.
        changed: All changed file paths.
        base: Base ref for fetching scoped diffs (None = staged).

    Returns:
        A `Violation` if the rule fires and requirements are unmet, else `None`.
    """
    triggered_by = match_any(rule.when_changed, changed)
    if not triggered_by:
        return None

    if rule.when_diff_contains:
        scoped_diff = get_diff_for_files(base, triggered_by)
        if not diff_contains(scoped_diff, rule.when_diff_contains):
            return None

    missing: list[str] = []

    if rule.require_changed:
        for required in rule.require_changed:
            matched = match_any([required], changed)
            if not matched:
                missing.append(required)

    if rule.require_one_of:
        any_match = match_any(rule.require_one_of, changed)
        if not any_match:
            missing.append("one of: " + ", ".join(rule.require_one_of))

    if not missing:
        return None

    return Violation(rule=rule, triggered_by=triggered_by, missing=missing)


def format_violation(violation: Violation) -> str:
    """Return a human-readable multi-line description of a violation.

    Args:
        violation: The violation to render.

    Returns:
        A pretty-printed string suitable for stdout/stderr.
    """
    icon = SEVERITY_ICONS.get(violation.rule.severity, "?    ")
    header = f"{icon} {violation.rule.severity.upper()} — {violation.rule.name}"
    lines = [header]

    triggered = ", ".join(violation.triggered_by[:3])
    if len(violation.triggered_by) > 3:
        triggered += f" (+{len(violation.triggered_by) - 3} more)"
    lines.append(f"    Triggered by: {triggered}")
    lines.append(f"    Required: {', '.join(violation.missing)}")
    if violation.rule.fix_hint:
        lines.append(f"    Fix: {violation.rule.fix_hint}")
    return "\n".join(lines)


def main() -> int:
    """Entry point for the doc-sync rule engine."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        default=None,
        help="Base ref to diff against (e.g. origin/main). Default: staged changes.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Include info-level notices in the output.",
    )
    args = parser.parse_args()

    if not CONFIG_FILE.exists():
        print(f"ERROR No config at {CONFIG_FILE}", file=sys.stderr)
        return 2

    rules, escape = load_config(CONFIG_FILE)

    marker = escape.get("commit_message_marker")
    if marker and commit_message_has_marker(last_commit_message(), marker):
        print(f"OK   Escape hatch '{marker}' found in commit message — skipping doc-sync rules.")
        return 0

    changed = get_changed_files(args.base)
    if not changed:
        if args.verbose:
            print("INFO No changed files detected — nothing to check.")
        return 0

    violations: list[Violation] = []
    for rule in rules:
        violation = evaluate_rule(rule, changed, args.base)
        if violation is not None:
            violations.append(violation)

    if not violations:
        print(f"OK   {len(rules)} doc-sync rules passed against {len(changed)} changed files.")
        return 0

    has_error = False
    for violation in violations:
        if violation.rule.severity == "info" and not args.verbose:
            continue
        print(format_violation(violation))
        if violation.rule.severity == "error":
            has_error = True

    print()
    error_count = sum(1 for v in violations if v.rule.severity == "error")
    warn_count = sum(1 for v in violations if v.rule.severity == "warning")
    print(f"Summary: {error_count} error(s), {warn_count} warning(s)")

    return 1 if has_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
