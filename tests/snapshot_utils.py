"""Snapshot / golden-file comparison utilities for API response testing.

Records expected API responses as JSON files in ``tests/_snapshots/``.
Tests compare actual responses against snapshots after stripping volatile
fields (timestamps, request IDs, UUIDs) so that only structural and
semantic changes cause failures.

Set ``WIKIMIND_UPDATE_SNAPSHOTS=1`` in the environment to regenerate
snapshot files from the current API output.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

_SNAPSHOTS_DIR = Path(__file__).parent / "_snapshots"

# Fields whose values change between runs and should be replaced with
# a deterministic placeholder before comparison.
_VOLATILE_PATTERNS: dict[str, str] = {
    # UUID-v4 strings
    "id": "<UUID>",
    "request_id": "<REQUEST_ID>",
    "source_id": "<UUID>",
    "job_id": "<UUID>",
    "user_id": "<USER_ID>",
    "article_id": "<UUID>",
    "tag_id": "<UUID>",
}

# ISO-8601 timestamp regex — matches values, not keys.
_ISO_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?")

# UUID-v4 regex for value-level replacement.
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def _stabilize_str(value: str, key: str | None) -> str:
    """Replace a volatile string value with a deterministic placeholder."""
    if key in _VOLATILE_PATTERNS and _UUID_RE.fullmatch(value):
        return _VOLATILE_PATTERNS[key]
    if key == "request_id":
        return "<REQUEST_ID>"
    if key and key.endswith(("_at", "_date")) and _ISO_TIMESTAMP_RE.fullmatch(value):
        return "<TIMESTAMP>"
    if key == "file_path" and value:
        return "<FILE_PATH>"
    return value


def _stabilize(obj: Any, *, _key: str | None = None) -> Any:
    """Recursively replace volatile values with deterministic placeholders."""
    if isinstance(obj, dict):
        return {k: _stabilize(v, _key=k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_stabilize(item) for item in obj]
    if isinstance(obj, str):
        return _stabilize_str(obj, _key)
    return obj


def stabilize_response(data: Any) -> Any:
    """Strip volatile fields from an API response for snapshot comparison."""
    return _stabilize(data)


def _should_update() -> bool:
    """Check whether snapshot update mode is active."""
    return os.environ.get("WIKIMIND_UPDATE_SNAPSHOTS", "").strip() in ("1", "true", "yes")


def assert_matches_snapshot(data: Any, snapshot_name: str) -> None:
    """Compare *data* against a golden-file snapshot.

    When ``WIKIMIND_UPDATE_SNAPSHOTS=1`` is set, the snapshot file is
    overwritten with the current (stabilized) response instead of
    asserting equality.

    Args:
        data: The API response body (parsed JSON).
        snapshot_name: File stem used under ``tests/_snapshots/``
            (e.g. ``"health_response"`` -> ``tests/_snapshots/health_response.json``).
    """
    stable = stabilize_response(data)
    snapshot_path = _SNAPSHOTS_DIR / f"{snapshot_name}.json"

    if _should_update():
        _SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(json.dumps(stable, indent=2, sort_keys=True) + "\n")
        return

    assert snapshot_path.exists(), (
        f"Snapshot file not found: {snapshot_path}\n"
        f"Run with WIKIMIND_UPDATE_SNAPSHOTS=1 to create it.\n"
        f"Actual (stabilized):\n{json.dumps(stable, indent=2, sort_keys=True)}"
    )

    expected = json.loads(snapshot_path.read_text())
    actual_pretty = json.dumps(stable, indent=2, sort_keys=True)
    expected_pretty = json.dumps(expected, indent=2, sort_keys=True)
    assert stable == expected, (
        f"Snapshot mismatch for {snapshot_name}:\n"
        f"--- expected (snapshot) ---\n{expected_pretty}\n"
        f"--- actual (stabilized) ---\n{actual_pretty}\n"
        f"\nRun with WIKIMIND_UPDATE_SNAPSHOTS=1 to update."
    )
