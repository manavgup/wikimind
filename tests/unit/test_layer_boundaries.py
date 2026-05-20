"""Static guardrails for layer-boundary regressions.

Parses imports in each architectural layer and asserts that modules respect
the dependency rules:

- **Routes** (``wikimind.api.routes``) must NOT import from ``wikimind.engine``
  or ``wikimind.ingest`` — they should go through ``wikimind.services``.
- **Jobs** (``wikimind.jobs``) must NOT import from ``wikimind.engine`` — they
  should go through ``wikimind.services``.
- **MCP** (``wikimind.mcp``) must NOT import from ``wikimind.engine`` — they
  should go through ``wikimind.services``.

Known exceptions are documented in allowlists below. Each entry records the
file, the forbidden import, and a justification. When a new violation appears,
the test fails — forcing the developer to either refactor or consciously extend
the allowlist with a reason.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "wikimind"

# ---------------------------------------------------------------------------
# Allowlisted exceptions: (relative_path, forbidden_module_prefix)
#
# Each tuple documents a known boundary crossing that has been reviewed and
# accepted.  Add new entries only with a comment explaining *why* the
# shortcut is necessary.
# ---------------------------------------------------------------------------

# Routes that bypass the service layer to reach engine/ingest directly.
_ROUTES_ALLOWLIST: set[tuple[str, str]] = {
    # settings.py needs LLM provider error classes + router for provider-test endpoint
    ("api/routes/settings.py", "wikimind.engine.llm_router"),
    # synthesis.py calls SynthesisCompiler directly (no service wrapper yet)
    ("api/routes/synthesis.py", "wikimind.engine.synthesis_compiler"),
    # ingest.py uses PDFAdapter for raw-file serving (not an orchestration path)
    ("api/routes/ingest.py", "wikimind.ingest.adapters.pdf"),
}

# Jobs that reach into engine directly instead of going through services.
_JOBS_ALLOWLIST: set[tuple[str, str]] = {
    # worker.py orchestrates compilation — the Compiler *is* the job payload
    ("jobs/worker.py", "wikimind.engine.compiler"),
    ("jobs/worker.py", "wikimind.engine.concept_compiler"),
    ("jobs/worker.py", "wikimind.engine.linter.runner"),
    # sweep.py does deterministic wikilink resolution (no LLM, pure DB)
    ("jobs/sweep.py", "wikimind.engine.wikilink_resolver"),
}

# MCP tools that reach into engine directly.
_MCP_ALLOWLIST: set[tuple[str, str]] = {
    # tools_analysis.py calls SynthesisCompiler directly (no service wrapper yet)
    ("mcp/tools_analysis.py", "wikimind.engine.synthesis_compiler"),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_imports(filepath: Path) -> list[str]:
    """Return all imported module names from *filepath* using AST parsing.

    Handles both ``import X`` and ``from X import Y`` forms, including those
    inside ``if TYPE_CHECKING`` blocks (which still declare a dependency edge).
    """
    source = filepath.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(filepath))

    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def _find_python_files(directory: Path) -> list[Path]:
    """Return all ``.py`` files under *directory*, excluding ``__init__.py``."""
    return sorted(p for p in directory.rglob("*.py") if p.name != "__init__.py")


def _check_forbidden_imports(
    layer_dir: Path,
    forbidden_prefixes: list[str],
    allowlist: set[tuple[str, str]],
) -> list[str]:
    """Scan *layer_dir* for imports matching any *forbidden_prefixes*.

    Returns a list of human-readable violation strings.  Entries present in
    *allowlist* are silently skipped.
    """
    violations: list[str] = []
    for filepath in _find_python_files(layer_dir):
        rel = filepath.relative_to(SRC_ROOT).as_posix()
        for module in _collect_imports(filepath):
            for prefix in forbidden_prefixes:
                if not module.startswith(prefix):
                    continue
                if (rel, module) in allowlist:
                    continue
                # Check prefix-level allowlist match: "wikimind.engine.compiler"
                # is allowed by ("jobs/worker.py", "wikimind.engine.compiler")
                # even if the actual import is a sub-attribute.
                if any(rel == a_rel and module.startswith(a_mod) for a_rel, a_mod in allowlist):
                    continue
                violations.append(f"  {rel} imports {module}")
    return violations


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRouteLayerBoundaries:
    """Routes must not import directly from engine or ingest."""

    def test_routes_do_not_import_engine(self) -> None:
        routes_dir = SRC_ROOT / "api" / "routes"
        if not routes_dir.exists():
            pytest.skip("routes directory not found")

        violations = _check_forbidden_imports(
            routes_dir,
            forbidden_prefixes=["wikimind.engine"],
            allowlist=_ROUTES_ALLOWLIST,
        )
        assert not violations, (
            "Route modules must not import from wikimind.engine directly — "
            "use the service layer instead.\n"
            "Violations:\n" + "\n".join(violations) + "\n\n"
            "If this crossing is intentional, add it to _ROUTES_ALLOWLIST in "
            "tests/unit/test_layer_boundaries.py with a justification."
        )

    def test_routes_do_not_import_ingest(self) -> None:
        routes_dir = SRC_ROOT / "api" / "routes"
        if not routes_dir.exists():
            pytest.skip("routes directory not found")

        violations = _check_forbidden_imports(
            routes_dir,
            forbidden_prefixes=["wikimind.ingest"],
            allowlist=_ROUTES_ALLOWLIST,
        )
        assert not violations, (
            "Route modules must not import from wikimind.ingest directly — "
            "use the service layer instead.\n"
            "Violations:\n" + "\n".join(violations) + "\n\n"
            "If this crossing is intentional, add it to _ROUTES_ALLOWLIST in "
            "tests/unit/test_layer_boundaries.py with a justification."
        )


class TestJobLayerBoundaries:
    """Jobs must not import directly from engine."""

    def test_jobs_do_not_import_engine(self) -> None:
        jobs_dir = SRC_ROOT / "jobs"
        if not jobs_dir.exists():
            pytest.skip("jobs directory not found")

        violations = _check_forbidden_imports(
            jobs_dir,
            forbidden_prefixes=["wikimind.engine"],
            allowlist=_JOBS_ALLOWLIST,
        )
        assert not violations, (
            "Job modules must not import from wikimind.engine directly — "
            "use the service layer instead.\n"
            "Violations:\n" + "\n".join(violations) + "\n\n"
            "If this crossing is intentional, add it to _JOBS_ALLOWLIST in "
            "tests/unit/test_layer_boundaries.py with a justification."
        )


class TestMCPLayerBoundaries:
    """MCP tools must not import directly from engine."""

    def test_mcp_does_not_import_engine(self) -> None:
        mcp_dir = SRC_ROOT / "mcp"
        if not mcp_dir.exists():
            pytest.skip("mcp directory not found")

        violations = _check_forbidden_imports(
            mcp_dir,
            forbidden_prefixes=["wikimind.engine"],
            allowlist=_MCP_ALLOWLIST,
        )
        assert not violations, (
            "MCP modules must not import from wikimind.engine directly — "
            "use the service layer instead.\n"
            "Violations:\n" + "\n".join(violations) + "\n\n"
            "If this crossing is intentional, add it to _MCP_ALLOWLIST in "
            "tests/unit/test_layer_boundaries.py with a justification."
        )


class TestAllowlistsAreValid:
    """Ensure allowlist entries correspond to real violations.

    If an allowlisted import is removed (e.g., refactored to use the service
    layer), the stale allowlist entry should be cleaned up.
    """

    @pytest.mark.parametrize(
        ("rel_path", "module"),
        sorted(_ROUTES_ALLOWLIST),
        ids=[f"{r}::{m}" for r, m in sorted(_ROUTES_ALLOWLIST)],
    )
    def test_routes_allowlist_entries_still_needed(self, rel_path: str, module: str) -> None:
        filepath = SRC_ROOT / rel_path
        if not filepath.exists():
            pytest.fail(f"Allowlisted file does not exist: {rel_path}")
        imports = _collect_imports(filepath)
        matches = [m for m in imports if m.startswith(module)]
        assert matches, (
            f"Stale allowlist entry: {rel_path} no longer imports {module}. Remove it from _ROUTES_ALLOWLIST."
        )

    @pytest.mark.parametrize(
        ("rel_path", "module"),
        sorted(_JOBS_ALLOWLIST),
        ids=[f"{r}::{m}" for r, m in sorted(_JOBS_ALLOWLIST)],
    )
    def test_jobs_allowlist_entries_still_needed(self, rel_path: str, module: str) -> None:
        filepath = SRC_ROOT / rel_path
        if not filepath.exists():
            pytest.fail(f"Allowlisted file does not exist: {rel_path}")
        imports = _collect_imports(filepath)
        matches = [m for m in imports if m.startswith(module)]
        assert matches, f"Stale allowlist entry: {rel_path} no longer imports {module}. Remove it from _JOBS_ALLOWLIST."

    @pytest.mark.parametrize(
        ("rel_path", "module"),
        sorted(_MCP_ALLOWLIST),
        ids=[f"{r}::{m}" for r, m in sorted(_MCP_ALLOWLIST)],
    )
    def test_mcp_allowlist_entries_still_needed(self, rel_path: str, module: str) -> None:
        filepath = SRC_ROOT / rel_path
        if not filepath.exists():
            pytest.fail(f"Allowlisted file does not exist: {rel_path}")
        imports = _collect_imports(filepath)
        matches = [m for m in imports if m.startswith(module)]
        assert matches, f"Stale allowlist entry: {rel_path} no longer imports {module}. Remove it from _MCP_ALLOWLIST."
