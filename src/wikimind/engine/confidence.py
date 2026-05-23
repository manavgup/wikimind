"""Pure functions that compute confidence scores with decay.

Confidence scoring operates at two levels:

* **Claim-level** — each compiled claim gets a numeric score in ``[0.0, 1.0]``
  based on how many sources back it and the LLM's categorical confidence label.
  See :func:`compute_claim_confidence`.

* **Article-level** — an arithmetic mean of its claims' confidence scores, or a
  provenance-based fallback when the article has no persisted claims. See
  :func:`compute_confidence` and :func:`aggregate_claim_confidence`.

Both levels are *separate* from :class:`wikimind.models.ConfidenceLevel`,
which is the categorical per-claim label produced by the LLM compiler.

This module is intentionally I/O-free: every function takes plain data and
returns a float, so it can be exhaustively unit-tested without a DB or
compiler context.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Tunable weights — kept as module-level constants rather than scattered
# magic numbers so a future Settings-driven override is a one-line change.
# ---------------------------------------------------------------------------

_SOURCE_COUNT_WEIGHT: float = 0.40
_RECENCY_WEIGHT: float = 0.30
_SOURCE_QUALITY_WEIGHT: float = 0.20
_CONTRADICTION_WEIGHT: float = 0.10

# Source-count component saturates at this many sources.
_SOURCE_COUNT_SATURATION: int = 4

# Recency component decays linearly to zero over this many days.
_RECENCY_HORIZON_DAYS: int = 365

# Per-source-type quality weighting is not yet implemented; until it is,
# we use a constant baseline. See the docstring on
# :func:`compute_confidence` for the planned extension point.
_SOURCE_QUALITY_BASELINE: float = 0.7

# Each contradiction subtracts this much from the contradiction component
# (clamped to zero).
_CONTRADICTION_PENALTY_PER_HIT: float = 0.25

# Decay floor — after long enough, confidence cannot drop below this
# fraction of the base score.
_DECAY_FLOOR: float = 0.5
_DECAY_HORIZON_DAYS: int = 365
_DECAY_MAX_REDUCTION: float = 0.3

# Claim-level confidence: categorical label baseline scores.
# A "sourced" claim starts at 0.8; more backing sources push it toward 1.0.
_CLAIM_CONFIDENCE_BASELINES: dict[str, float] = {
    "sourced": 0.8,
    "mixed": 0.5,
    "inferred": 0.3,
    "opinion": 0.2,
}
_CLAIM_DEFAULT_BASELINE: float = 0.3

# Claim-level: each additional source adds this much (diminishing returns
# via saturation at _SOURCE_COUNT_SATURATION sources).
_CLAIM_SOURCE_BONUS_WEIGHT: float = 0.2


def _clamp01(value: float) -> float:
    """Clamp *value* to the closed interval ``[0.0, 1.0]``."""
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def compute_confidence(
    source_count: int,
    newest_source_age_days: int,
    contradiction_count: int,
) -> float:
    """Compute the base article-level confidence score.

    The score is a weighted sum of four components, each in ``[0.0, 1.0]``:

    * **Source count (40%)** — ``min(1.0, source_count / 4)``. Saturates at
      four sources to avoid rewarding spam.
    * **Recency (30%)** — ``max(0.0, 1.0 - newest_source_age_days / 365)``.
      Linear decay over one year.
    * **Source-quality baseline (20%)** — currently a constant ``0.7``. This
      slot is reserved for a future per-source-type weighting (e.g. peer-
      reviewed paper > random blog post). The function signature will not
      change when that is added; only the implementation will.
    * **Contradiction penalty (10%)** — ``max(0.0, 1.0 - 0.25 * count)``.

    Args:
        source_count: Number of sources backing the article. Negative
            values are treated as zero by the saturation formula.
        newest_source_age_days: Age in days of the most recently ingested
            source. Negative values (clock skew) are treated as zero.
        contradiction_count: Number of incoming ``CONTRADICTS`` backlinks.

    Returns:
        A confidence score clamped to ``[0.0, 1.0]``.
    """
    source_component = min(1.0, max(0, source_count) / _SOURCE_COUNT_SATURATION)
    recency_component = max(
        0.0,
        1.0 - max(0, newest_source_age_days) / _RECENCY_HORIZON_DAYS,
    )
    quality_component = _SOURCE_QUALITY_BASELINE
    contradiction_component = max(
        0.0,
        1.0 - _CONTRADICTION_PENALTY_PER_HIT * max(0, contradiction_count),
    )

    score = (
        _SOURCE_COUNT_WEIGHT * source_component
        + _RECENCY_WEIGHT * recency_component
        + _SOURCE_QUALITY_WEIGHT * quality_component
        + _CONTRADICTION_WEIGHT * contradiction_component
    )
    return _clamp01(score)


def compute_staleness(
    days_since_reinforced: float,
    decay_rate: float = 0.002,
) -> float:
    """Compute a staleness score for an article.

    The score is a linear function of days since the article was last
    reinforced, clamped to ``[0.0, 1.0]``.  The ``decay_rate`` controls
    how fast the score grows — the default ``0.002`` reaches 0.5 at
    250 days.

    Args:
        days_since_reinforced: Fractional days since the last reinforcement
            event.  Negative values are treated as zero (fresh).
        decay_rate: Growth rate per day.  Configurable via
            ``Settings.staleness.decay_rate``.

    Returns:
        A staleness score clamped to ``[0.0, 1.0]``.
    """
    days = max(0.0, days_since_reinforced)
    return _clamp01(days * decay_rate)


def apply_decay(base: float, days_since_reinforced: int) -> float:
    """Apply time-decay to a stored base confidence score.

    The decay multiplier is ``max(0.5, 1.0 - (days/365) * 0.3)``, so the
    effective score never drops below 50% of its base value no matter how
    stale the article gets. The full decay (multiplier ``0.5``) kicks in
    around the 1095-day mark.

    Args:
        base: The stored ``Article.confidence_score``.
        days_since_reinforced: Days elapsed since the article was last
            (re)compiled. Negative values are treated as zero.

    Returns:
        The decayed effective confidence, clamped to ``[0.0, 1.0]``.
    """
    days = max(0, days_since_reinforced)
    multiplier = max(
        _DECAY_FLOOR,
        1.0 - (days / _DECAY_HORIZON_DAYS) * _DECAY_MAX_REDUCTION,
    )
    return _clamp01(base * multiplier)


def compute_claim_confidence(
    confidence_level: str,
    source_count: int,
) -> float:
    """Compute a numeric confidence score for a single compiled claim.

    The score combines a baseline derived from the LLM's categorical
    confidence label with a source-count bonus that rewards claims backed
    by multiple independent sources. The bonus saturates at
    ``_SOURCE_COUNT_SATURATION`` sources to avoid rewarding spam.

    Formula::

        baseline + bonus_weight * min(1.0, source_count / saturation)

    Args:
        confidence_level: Categorical label from the LLM (``sourced``,
            ``mixed``, ``inferred``, ``opinion``).
        source_count: Number of distinct sources backing this claim.

    Returns:
        A confidence score clamped to ``[0.0, 1.0]``.
    """
    baseline = _CLAIM_CONFIDENCE_BASELINES.get(
        confidence_level.lower(),
        _CLAIM_DEFAULT_BASELINE,
    )
    source_bonus = min(1.0, max(0, source_count) / _SOURCE_COUNT_SATURATION)
    return _clamp01(baseline + _CLAIM_SOURCE_BONUS_WEIGHT * source_bonus)


def aggregate_claim_confidence(claim_scores: list[float]) -> float:
    """Compute article-level confidence as the arithmetic mean of claim scores.

    Returns 0.5 (neutral default) when there are no claims, so the caller
    can fall back to the provenance-based ``compute_confidence`` if desired.

    Args:
        claim_scores: Per-claim confidence scores, each in ``[0.0, 1.0]``.

    Returns:
        The arithmetic mean of the scores, clamped to ``[0.0, 1.0]``,
        or ``0.5`` if the list is empty.
    """
    if not claim_scores:
        return 0.5
    return _clamp01(sum(claim_scores) / len(claim_scores))
