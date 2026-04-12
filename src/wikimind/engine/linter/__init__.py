"""Wiki linter engine — check-per-function health audit system.

Re-exports the public API: the runner and individual detection functions.
"""

from wikimind.engine.linter.contradictions import detect_contradictions
from wikimind.engine.linter.orphans import detect_orphans
from wikimind.engine.linter.runner import run_lint

__all__ = ["detect_contradictions", "detect_orphans", "run_lint"]
