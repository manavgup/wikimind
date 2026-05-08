#!/usr/bin/env python3
"""Update detect-secrets baseline idempotently.

Re-scans the repo and updates `.secrets.baseline`, but only writes the file
when there are substantive changes (not just a ``generated_at`` timestamp
bump).  This prevents pre-commit from reporting "files were modified" on
every run when nothing meaningful changed.

Used as a pre-commit hook entry point.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_NAME = ".secrets.baseline"
BASELINE = REPO_ROOT / BASELINE_NAME


def _detect_secrets_cmd() -> list[str]:
    """Return the command to invoke detect-secrets, preferring the venv copy."""
    venv_bin = REPO_ROOT / ".venv" / "bin" / "detect-secrets"
    if venv_bin.exists():
        return [str(venv_bin)]
    if shutil.which("detect-secrets"):
        return ["detect-secrets"]
    # Last resort: run as a Python module
    return [sys.executable, "-m", "detect_secrets"]


def main() -> int:
    """Re-scan and update baseline only if content changed."""
    if not BASELINE.exists():
        # No baseline yet — create one from scratch.
        subprocess.run(
            [*_detect_secrets_cmd(), "scan", "--baseline", BASELINE_NAME],
            cwd=REPO_ROOT,
            check=False,
        )
        return 0

    # Read current baseline.
    old_text = BASELINE.read_text(encoding="utf-8")
    try:
        old_data = json.loads(old_text)
    except json.JSONDecodeError:
        old_data = {}

    # Run scan to update the baseline file in-place.
    # Use the relative filename so detect-secrets stores a portable path
    # in its filters_used entry (avoids absolute-path drift in worktrees).
    subprocess.run(
        ["detect-secrets", "scan", "--baseline", BASELINE_NAME],
        cwd=REPO_ROOT,
        check=False,
    )

    # Read updated baseline.
    new_text = BASELINE.read_text(encoding="utf-8")
    try:
        new_data = json.loads(new_text)
    except json.JSONDecodeError:
        # If the new file is invalid JSON, keep it (something is wrong).
        return 0

    # Compare ignoring the generated_at timestamp.
    old_comparable = {k: v for k, v in old_data.items() if k != "generated_at"}
    new_comparable = {k: v for k, v in new_data.items() if k != "generated_at"}

    if old_comparable == new_comparable:
        # Only the timestamp changed — restore the original file to avoid
        # pre-commit reporting "files were modified by this hook".
        BASELINE.write_text(old_text, encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
