"""Wiki linter engine — check-per-function health audit system.

Re-exports the public API: the runner and individual detection functions.
"""

from wikimind.engine.linter.contradictions import detect_contradictions
from wikimind.engine.linter.orphans import detect_orphans
from wikimind.engine.linter.runner import run_lint
from wikimind.engine.linter.stale_spans import detect_stale_spans

__all__ = ["detect_contradictions", "detect_orphans", "detect_stale_spans", "run_lint"]
