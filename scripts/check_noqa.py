"""Pre-commit hook to flag new ``# noqa`` suppressions.

Diffs the staged changes against the merge-base of ``main`` and warns (but does
not block) when new ``# noqa`` comments are introduced.  This makes it easy to
spot lazy suppressions added by subagents while still allowing legitimate
exceptions.

Exit codes:
    0 — always (informational only, never blocks the commit)
"""

from __future__ import annotations

import re
import subprocess
import sys

NOQA_RE = re.compile(r"#\s*noqa\b", re.IGNORECASE)


def _merge_base() -> str:
    """Return the merge-base commit between HEAD and main."""
    try:
        result = subprocess.run(
            ["git", "merge-base", "HEAD", "main"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        # Fallback: compare against HEAD (i.e. only staged changes)
        return "HEAD"


def main() -> None:
    """Scan the diff for new ``# noqa`` additions and print warnings."""
    base = _merge_base()

    result = subprocess.run(
        ["git", "diff", "--cached", "--diff-filter=ACMR", "-U0", base, "--", "*.py"],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        # No diff or git error — nothing to check
        return

    findings: list[str] = []
    current_file = ""
    for line in result.stdout.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:]
        elif line.startswith("+") and not line.startswith("+++") and NOQA_RE.search(line):
            findings.append(f"  {current_file}: {line[1:].strip()}")

    if findings:
        print(f"\n⚠️  New # noqa suppressions detected ({len(findings)}):")
        for f in findings:
            print(f)
        print(
            "\nThese are informational only — the commit is NOT blocked.\n"
            "Please verify each suppression is intentional and add a\n"
            "code-specific suffix (e.g. # noqa: E501) when possible.\n"
        )


if __name__ == "__main__":
    main()
    sys.exit(0)  # Always pass — informational only
