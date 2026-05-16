#!/usr/bin/env python3
"""Static guardrail: detect cross-layer import violations.

The wikimind backend has architectural layers with a strict dependency DAG:

    api/routes → services → engine → store/database

This script scans Python source files under src/wikimind/ and flags imports
that violate layer boundaries:

- services/ must NOT import from api/
- engine/ must NOT import from api/
- store/ must NOT import from api/ or services/
- ingest/ must NOT import from api/

Known violations that predate this check can be listed in KNOWN_VIOLATIONS
and will emit warnings instead of errors.

Usage:
    python scripts/check_layer_boundaries.py
    python scripts/check_layer_boundaries.py --strict  # treat known violations as errors too
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

# Root of the wikimind source package.
SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "wikimind"

# Layer boundary rules: (importer_layer, forbidden_import_prefix)
# Each tuple means: files in importer_layer must not import from forbidden_import_prefix.
RULES: list[tuple[str, str]] = [
    ("services", "wikimind.api"),
    ("engine", "wikimind.api"),
    ("store", "wikimind.api"),
    ("store", "wikimind.services"),
    ("ingest", "wikimind.api"),
]

# Known violations that predate this guardrail. These emit warnings (not errors)
# unless --strict is passed. Each entry is (relative_file_path, imported_module).
KNOWN_VIOLATIONS: set[tuple[str, str]] = {
    ("engine/llm_router.py", "wikimind.api.routes.ws"),
    ("engine/linter/runner.py", "wikimind.api.routes.ws"),
    ("ingest/adapters/pdf.py", "wikimind.api.routes.ws"),
    ("ingest/service.py", "wikimind.api.routes.ws"),
}


@dataclass
class Violation:
    """A single layer-boundary violation."""

    file: Path
    line: int
    importer_layer: str
    imported_module: str
    is_known: bool = False


def get_layer(rel_path: Path) -> str | None:
    """Return the layer name for a file path relative to src/wikimind/."""
    parts = rel_path.parts
    if not parts:
        return None
    return parts[0]


def extract_imports(filepath: Path) -> list[tuple[int, str]]:
    """Parse a Python file and return (line_number, module_name) for all imports."""
    try:
        source = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []

    imports: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append((node.lineno, node.module))
    return imports


def check_file(filepath: Path) -> list[Violation]:
    """Check a single file for layer-boundary violations."""
    rel_path = filepath.relative_to(SRC_ROOT)
    layer = get_layer(rel_path)
    if layer is None:
        return []

    # Determine which prefixes are forbidden for this layer.
    forbidden_prefixes = [prefix for (lyr, prefix) in RULES if lyr == layer]
    if not forbidden_prefixes:
        return []

    violations: list[Violation] = []
    for lineno, module in extract_imports(filepath):
        for prefix in forbidden_prefixes:
            if module == prefix or module.startswith(prefix + "."):
                # Check if this is a known violation.
                rel_str = str(rel_path)
                is_known = (rel_str, module) in KNOWN_VIOLATIONS
                violations.append(
                    Violation(
                        file=filepath,
                        line=lineno,
                        importer_layer=layer,
                        imported_module=module,
                        is_known=is_known,
                    )
                )
    return violations


def main() -> int:
    """Scan all Python files and report violations."""
    strict = "--strict" in sys.argv

    all_violations: list[Violation] = []
    for py_file in sorted(SRC_ROOT.rglob("*.py")):
        all_violations.extend(check_file(py_file))

    if not all_violations:
        print("check-layers: OK — no layer-boundary violations found.")
        return 0

    errors = [v for v in all_violations if not v.is_known]
    warnings = [v for v in all_violations if v.is_known]

    if warnings:
        print("Known violations (warnings — refactor these eventually):")
        for v in warnings:
            rel = v.file.relative_to(SRC_ROOT)
            print(f"  {rel}:{v.line}: {v.importer_layer}/ imports {v.imported_module}")
        print()

    if errors:
        print("NEW layer-boundary violations (errors):")
        for v in errors:
            rel = v.file.relative_to(SRC_ROOT)
            print(f"  {rel}:{v.line}: {v.importer_layer}/ imports {v.imported_module}")
        print()
        print(
            f"FAILED: {len(errors)} new violation(s) found. Fix the imports or update KNOWN_VIOLATIONS if intentional."
        )
        return 1

    if strict:
        print(f"FAILED (--strict): {len(warnings)} known violation(s) still present. Refactor to remove them.")
        return 1

    print("check-layers: OK — only known (pre-existing) violations remain.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
