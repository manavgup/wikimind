"""Tests for the doc-sync infrastructure scripts.

Covers:
- `check_doc_sync.py` rule evaluation (violation detection + escape hatches).
- `regenerate_readme_targets.py` splicing the README marker block.

These tests import the scripts as modules via importlib so they don't need
to live on `sys.path`. They run fully offline and touch no real git state.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"


def _load_script(name: str):
    """Import a scripts/*.py file as a module."""
    path = SCRIPTS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_docsync_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check_doc_sync = _load_script("check_doc_sync")
regenerate_readme_targets = _load_script("regenerate_readme_targets")


# ---------------------------------------------------------------------------
# check_doc_sync
# ---------------------------------------------------------------------------


def test_rule_flags_config_change_without_env_example() -> None:
    """A config.py change without .env.example is flagged as an error."""
    rule = check_doc_sync.Rule(
        name="Config schema changes need .env.example",
        when_changed=["src/wikimind/config.py"],
        require_changed=[".env.example"],
        severity="error",
        fix_hint="Add the new setting to .env.example",
    )

    changed = ["src/wikimind/config.py"]

    # No when_diff_contains → base ref unused.
    violation = check_doc_sync.evaluate_rule(rule, changed, base=None)

    assert violation is not None
    assert violation.rule.name == "Config schema changes need .env.example"
    assert violation.triggered_by == ["src/wikimind/config.py"]
    assert ".env.example" in violation.missing


def test_rule_passes_when_required_doc_updated() -> None:
    """The same rule should be clean when .env.example also changes."""
    rule = check_doc_sync.Rule(
        name="Config schema changes need .env.example",
        when_changed=["src/wikimind/config.py"],
        require_changed=[".env.example"],
        severity="error",
    )

    changed = ["src/wikimind/config.py", ".env.example"]

    assert check_doc_sync.evaluate_rule(rule, changed, base=None) is None


def test_commit_message_marker_requires_own_line() -> None:
    """The escape-hatch marker must be on its own line to count.

    Ensures that a commit message that merely describes the escape hatch
    (e.g. the doc-sync infrastructure PR itself) does not bypass the check.
    """
    marker = "[skip-doc-check]"

    # On its own line (with surrounding whitespace) → matches.
    assert check_doc_sync.commit_message_has_marker(f"fix: bump\n\n{marker}\n", marker)
    assert check_doc_sync.commit_message_has_marker(f"fix: bump\n   {marker}   \n", marker)

    # Embedded in a sentence → does NOT match.
    assert not check_doc_sync.commit_message_has_marker(
        f"chore: document the {marker} escape hatch",
        marker,
    )
    assert not check_doc_sync.commit_message_has_marker(
        "Use `[skip-doc-check]` in your commit message",
        marker,
    )


def test_escape_hatch_commit_message_marker(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`[skip-doc-check]` on its own line short-circuits the checker."""
    monkeypatch.setattr(check_doc_sync, "last_commit_message", lambda: "fix: bump\n\n[skip-doc-check]\n")
    monkeypatch.setattr(
        check_doc_sync,
        "load_config",
        lambda _path: (
            [
                check_doc_sync.Rule(
                    name="would fire",
                    when_changed=["**/*.py"],
                    require_changed=["NEVER.md"],
                    severity="error",
                )
            ],
            {"commit_message_marker": "[skip-doc-check]"},
        ),
    )
    # If the escape hatch works, these should never be consulted.
    monkeypatch.setattr(check_doc_sync, "get_changed_files", lambda _base: pytest.fail("should not be called"))
    monkeypatch.setattr(check_doc_sync, "get_diff_for_files", lambda _base, _files: pytest.fail("should not be called"))

    # CONFIG_FILE just needs to exist.
    monkeypatch.setattr(check_doc_sync, "CONFIG_FILE", REPO_ROOT / ".docs-sync.yaml")

    monkeypatch.setattr(sys, "argv", ["check_doc_sync.py"])
    exit_code = check_doc_sync.main()

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Escape hatch" in captured.out


def test_when_diff_contains_narrows_trigger(monkeypatch: pytest.MonkeyPatch) -> None:
    """`when_diff_contains` acts as an AND filter on top of `when_changed`.

    The scoped diff for the triggering files is fetched via
    `get_diff_for_files`; we monkey-patch it to inject the diff text
    directly without touching real git state.
    """
    rule = check_doc_sync.Rule(
        name="only on validators",
        when_changed=["src/wikimind/config.py"],
        when_diff_contains=[r"model_validator"],
        require_changed=["docs/adr/new.md"],
        severity="warning",
    )

    # Same file, but the (scoped) diff doesn't contain the magic word.
    monkeypatch.setattr(check_doc_sync, "get_diff_for_files", lambda _base, _files: "+ unrelated = 1")
    assert check_doc_sync.evaluate_rule(rule, ["src/wikimind/config.py"], base=None) is None

    # Now the scoped diff contains the word → violation.
    monkeypatch.setattr(
        check_doc_sync,
        "get_diff_for_files",
        lambda _base, _files: "+@model_validator(mode='after')\n+def _v(self): ...",
    )
    violation = check_doc_sync.evaluate_rule(rule, ["src/wikimind/config.py"], base=None)
    assert violation is not None
    assert violation.rule.severity == "warning"


def test_when_diff_contains_scoped_to_triggered_files(monkeypatch: pytest.MonkeyPatch) -> None:
    """The diff regex must NOT match content from unrelated files in the diff.

    Regression test for the bug where a Python schema regex matched
    content in `docs/openapi.yaml` because the rule used the full diff
    text instead of the diff for files that triggered `when_changed`.
    """
    rule = check_doc_sync.Rule(
        name="config schema",
        when_changed=["src/wikimind/config.py"],
        when_diff_contains=[r"^\+\s+\w+:\s*str"],
        require_changed=[".env.example"],
        severity="error",
    )

    # The full diff contains a matching line, BUT it's in openapi.yaml,
    # not in config.py. The scoped diff for config.py is empty (no schema
    # changes), so the rule must NOT fire.
    def fake_scoped_diff(_base: object, files: list[str]) -> str:
        if "src/wikimind/config.py" in files:
            return "+def _helper(): pass\n"  # no schema fields
        return ""

    monkeypatch.setattr(check_doc_sync, "get_diff_for_files", fake_scoped_diff)

    assert check_doc_sync.evaluate_rule(rule, ["src/wikimind/config.py", "docs/openapi.yaml"], base=None) is None


# ---------------------------------------------------------------------------
# regenerate_readme_targets
# ---------------------------------------------------------------------------


def test_splice_replaces_marker_block() -> None:
    """splice() should replace whatever sits between the markers."""
    readme = (
        "# Header\n\nsome prose\n\n<!-- BEGIN make-targets -->\nOLD CONTENT\n<!-- END make-targets -->\n\nmore prose\n"
    )
    new_block = "### General\n\n| Target | Description |\n|--------|-------------|\n| `make help` | Show help |\n"

    updated = regenerate_readme_targets.splice(readme, new_block)

    assert "OLD CONTENT" not in updated
    assert "| `make help` | Show help |" in updated
    # Prose surrounding the block is preserved verbatim.
    assert updated.startswith("# Header")
    assert updated.endswith("more prose\n")


def test_splice_raises_without_markers() -> None:
    """splice() should fail loudly when the markers are missing."""
    readme = "# No markers here\n"

    with pytest.raises(ValueError, match="missing markers"):
        regenerate_readme_targets.splice(readme, "block content")


def test_parse_makefile_groups_by_section(tmp_path: Path) -> None:
    """parse_makefile should collect targets under `##@` sections."""
    makefile = tmp_path / "Makefile"
    makefile.write_text(
        "##@ Build\n"
        "\n"
        ".PHONY: build\n"
        "build: ## Compile the thing\n"
        "\t@echo build\n"
        "\n"
        "##@ Test\n"
        "\n"
        "test: ## Run tests\n"
        "\t@echo test\n"
        "coverage: ## Run tests with coverage\n"
        "\t@echo cov\n",
        encoding="utf-8",
    )

    sections = regenerate_readme_targets.parse_makefile(makefile)

    names = {s.name: [t[0] for t in s.targets] for s in sections}
    assert names == {"Build": ["build"], "Test": ["test", "coverage"]}
