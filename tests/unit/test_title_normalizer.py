"""Tests for the single shared title normalizer."""

import pytest

from wikimind.engine.title_normalizer import normalize_title


@pytest.mark.parametrize(
    "raw, expected",
    [
        # Baseline
        ("Machine Learning", "machine-learning"),
        ("machine learning", "machine-learning"),
        ("MACHINE LEARNING", "machine-learning"),
        # Whitespace variants collapse
        ("Machine   Learning", "machine-learning"),
        ("  Machine Learning  ", "machine-learning"),
        ("Machine\tLearning", "machine-learning"),
        ("Machine\nLearning", "machine-learning"),
        # Underscores become hyphens
        ("machine_learning", "machine-learning"),
        ("Machine_Learning_Ops", "machine-learning-ops"),
        # Punctuation stripped
        ("Machine Learning!", "machine-learning"),
        ("Machine Learning?", "machine-learning"),
        ("Machine Learning.", "machine-learning"),
        ("Machine, Learning", "machine-learning"),
        # Apostrophes stripped, not preserved as hyphens
        ("Karpathy's wiki pattern", "karpathys-wiki-pattern"),
        ("it's", "its"),
        # Unicode NFKD + ASCII strip
        ("Café", "cafe"),
        ("naïve", "naive"),
        ("Zürich", "zurich"),
        # Hyphens preserved
        ("state-of-the-art", "state-of-the-art"),
        # Multiple consecutive separators collapse
        ("foo   ---   bar", "foo-bar"),
        ("foo___bar", "foo-bar"),
        # Long titles are not truncated (the resolver does not care about length)
        ("a" * 200, "a" * 200),
        # Numbers preserved
        ("GPT-4o", "gpt-4o"),
        ("Article 1", "article-1"),
        # Empty and whitespace-only
        ("", ""),
        ("   ", ""),
        # Symbols dropped
        ("C++", "c"),
        ("C#", "c"),
    ],
)
def test_normalize_title(raw: str, expected: str) -> None:
    assert normalize_title(raw) == expected


def test_normalize_title_is_idempotent() -> None:
    """Normalizing an already-normalized string is a no-op."""
    once = normalize_title("Machine Learning Operations")
    twice = normalize_title(once)
    assert once == twice


def test_normalize_title_deterministic() -> None:
    """Two calls with the same input produce identical output."""
    a = normalize_title("Karpathy's LLM Wiki Pattern")
    b = normalize_title("Karpathy's LLM Wiki Pattern")
    assert a == b
