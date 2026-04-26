"""Verify user_id dependency is wired on all endpoints fixed in Issue #339.

These tests inspect FastAPI route signatures to confirm ``get_current_user_id``
is declared as a dependency, catching accidental regressions without needing
full integration round-trips for each endpoint.
"""

from __future__ import annotations

import inspect

from wikimind.api.deps import get_current_user_id
from wikimind.api.routes import jobs, lint, settings, wiki


def _has_user_id_dep(func) -> bool:
    """Return True if *func* has a parameter whose default is Depends(get_current_user_id)."""
    sig = inspect.signature(func)
    for param in sig.parameters.values():
        default = param.default
        # FastAPI Depends wraps the callable in a Depends instance
        if hasattr(default, "dependency") and default.dependency is get_current_user_id:
            return True
    return False


# ---- settings.py -----------------------------------------------------------


def test_update_settings_has_user_id() -> None:
    assert _has_user_id_dep(settings.update_settings)


# ---- wiki.py ---------------------------------------------------------------


def test_rebuild_concepts_has_user_id() -> None:
    assert _has_user_id_dep(wiki.rebuild_concepts)


def test_get_health_has_user_id() -> None:
    assert _has_user_id_dep(wiki.get_health)


def test_resolve_contradiction_has_user_id() -> None:
    assert _has_user_id_dep(wiki.resolve_contradiction)


# ---- lint.py ---------------------------------------------------------------


def test_get_report_has_user_id() -> None:
    assert _has_user_id_dep(lint.get_report)


def test_dismiss_finding_has_user_id() -> None:
    assert _has_user_id_dep(lint.dismiss_finding)


# ---- jobs.py ---------------------------------------------------------------


def test_get_job_has_user_id() -> None:
    assert _has_user_id_dep(jobs.get_job)


def test_trigger_lint_has_user_id() -> None:
    assert _has_user_id_dep(jobs.trigger_lint)


def test_trigger_reindex_has_user_id() -> None:
    assert _has_user_id_dep(jobs.trigger_reindex)
