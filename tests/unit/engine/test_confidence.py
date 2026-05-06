"""Unit tests for the pure confidence math in ``wikimind.engine.confidence``.

The functions under test are I/O-free, so the tests are simple table-
driven comparisons against hand-computed expected values.
"""

from __future__ import annotations

import math

import pytest

from wikimind.engine.confidence import apply_decay, compute_confidence

# 0.40 * source + 0.30 * recency + 0.20 * 0.7 + 0.10 * contradictions
# Source-count saturates at 4 sources.
# Recency decays linearly to 0 at 365 days.
# Contradiction component: max(0, 1 - 0.25 * count).
_QUALITY_BASELINE_TERM = 0.20 * 0.7  # 0.14


@pytest.mark.parametrize(
    ("source_count", "newest_age_days", "contradictions", "expected"),
    [
        # zero sources, zero age, no contradictions:
        # 0.40*0 + 0.30*1 + 0.14 + 0.10*1 = 0.54
        (0, 0, 0, 0.54),
        # one source, fresh:
        # 0.40*0.25 + 0.30*1 + 0.14 + 0.10*1 = 0.64
        (1, 0, 0, 0.64),
        # four sources saturate the source-count component:
        # 0.40*1 + 0.30*1 + 0.14 + 0.10*1 = 0.94
        (4, 0, 0, 0.94),
        # ten sources cannot exceed the saturation cap (still 0.94):
        (10, 0, 0, 0.94),
        # very old single source (>1 year): recency floored at 0.
        # 0.40*0.25 + 0 + 0.14 + 0.10*1 = 0.34
        (1, 400, 0, 0.34),
        # mid-life recency: 180/365 ≈ 0.5068 → recency ≈ 0.4931
        # 0.40*0.25 + 0.30*(1-180/365) + 0.14 + 0.10 = 0.4880... approx
        (1, 180, 0, 0.40 * 0.25 + 0.30 * (1 - 180 / 365) + 0.14 + 0.10),
        # one contradiction reduces the contradiction component to 0.75:
        # 0.40*1 + 0.30*1 + 0.14 + 0.10*0.75 = 0.915
        (4, 0, 1, 0.915),
        # four contradictions saturate the penalty (component → 0):
        # 0.40*1 + 0.30*1 + 0.14 + 0 = 0.84
        (4, 0, 4, 0.84),
        # five contradictions still saturate (cannot go below 0):
        (4, 0, 5, 0.84),
    ],
)
def test_compute_confidence_table(
    source_count: int,
    newest_age_days: int,
    contradictions: int,
    expected: float,
) -> None:
    """Hand-computed expected values for representative inputs."""
    result = compute_confidence(source_count, newest_age_days, contradictions)
    assert math.isclose(result, expected, abs_tol=1e-9), f"expected {expected}, got {result}"


def test_compute_confidence_clamped_to_unit_interval() -> None:
    """No combination of inputs may produce a value outside [0, 1]."""
    for sc in (0, 1, 4, 50):
        for age in (0, 100, 365, 5000):
            for ct in (0, 1, 10):
                v = compute_confidence(sc, age, ct)
                assert 0.0 <= v <= 1.0


def test_compute_confidence_negative_inputs_treated_as_zero() -> None:
    """Negative inputs (e.g. clock skew) should not blow the formula up."""
    assert compute_confidence(-1, -1, -1) == compute_confidence(0, 0, 0)


@pytest.mark.parametrize(
    ("base", "days", "expected"),
    [
        (1.0, 0, 1.0),
        # 1 - (365/365)*0.3 = 0.7 multiplier
        (1.0, 365, 0.7),
        # 1 - (730/365)*0.3 = 0.4 → floor at 0.5
        (1.0, 730, 0.5),
        # 1095 days: floor at 0.5 multiplier → effective = base * 0.5
        (1.0, 1095, 0.5),
        # 5000 days: still floored
        (1.0, 5000, 0.5),
        # base of 0.6, 1 year old → 0.6 * 0.7 = 0.42
        (0.6, 365, 0.42),
        # negative days clamped to 0 → no decay
        (0.8, -10, 0.8),
    ],
)
def test_apply_decay_table(base: float, days: int, expected: float) -> None:
    """Hand-computed expected decay multipliers."""
    result = apply_decay(base, days)
    assert math.isclose(result, expected, abs_tol=1e-9), f"expected {expected}, got {result}"


def test_apply_decay_floor_at_half() -> None:
    """No matter how stale, decay never drops below 50% of base."""
    for days in (1095, 2000, 100_000):
        assert apply_decay(1.0, days) == 0.5
        assert apply_decay(0.4, days) == 0.2  # 0.4 * 0.5
