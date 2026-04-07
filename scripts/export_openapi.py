#!/usr/bin/env python3
"""Export the FastAPI application's OpenAPI schema to a YAML file.

This script is the source of truth for `docs/openapi.yaml`. It imports the live
FastAPI `app` from `wikimind.main`, calls `app.openapi()` to generate the
schema, and writes it to disk using `yaml.safe_dump`.

Run it directly to regenerate the committed schema, or with `--check` to
verify the committed file is in sync with the application (used by pre-commit
and CI).

Examples:
    python scripts/export_openapi.py                 # write docs/openapi.yaml
    python scripts/export_openapi.py --check         # exit non-zero on drift
    python scripts/export_openapi.py --output foo.yaml
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

from wikimind.main import app

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "openapi.yaml"


def generate_schema() -> dict[str, Any]:
    """Return the FastAPI app's OpenAPI schema as a plain dict.

    Importing `wikimind.main` at module level triggers side-effects (router
    registration, middleware stack) but does NOT start the server, so the
    import is safe even when the script is invoked with ``--help``.

    Returns:
        The OpenAPI 3.x schema as a JSON-serialisable dict.
    """
    schema: dict[str, Any] = app.openapi()
    return schema


def serialize(schema: dict[str, Any]) -> str:
    """Serialize an OpenAPI schema to YAML.

    Args:
        schema: The schema dict returned by `FastAPI.openapi()`.

    Returns:
        A YAML-formatted string with deterministic ordering.
    """
    return yaml.safe_dump(
        schema,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )


def write(output: Path, content: str) -> None:
    """Write the YAML content to `output`, creating parent directories.

    Args:
        output: Target path for the YAML file.
        content: The serialized YAML content.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")


def check(output: Path, content: str) -> bool:
    """Compare fresh content with the committed file on disk.

    Args:
        output: Path to the committed OpenAPI YAML file.
        content: Freshly generated content to compare against.

    Returns:
        True when the on-disk file matches the fresh content.
    """
    if not output.exists():
        return False
    return output.read_text(encoding="utf-8") == content


def main() -> int:
    """Entry point for the export script."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the committed file matches the generated schema (non-zero exit on drift).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output path (default: docs/openapi.yaml).",
    )
    args = parser.parse_args()

    schema = generate_schema()
    content = serialize(schema)

    output: Path = args.output

    if args.check:
        if check(output, content):
            print(f"OK   {output} is in sync with the FastAPI app.")
            return 0
        print(
            f"DRIFT {output} is out of date.\n      Regenerate with: make export-openapi && git add {output}",
            file=sys.stderr,
        )
        return 1

    write(output, content)
    print(f"WROTE {output} ({len(content)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
