"""Tests for batched contradiction detection (issue #138).

Covers the three batch helper functions: _build_batch_prompt,
_parse_batch_response, and _run_batch (retry + fallback behavior).
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wikimind.engine.linter.contradictions import (
    _build_batch_prompt,
    _parse_batch_response,
    _run_batch,
)
from wikimind.models import Article, PageType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_article(title: str, tmp_path: Path | None = None) -> Article:
    """Create a minimal Article instance for prompt-building tests."""
    slug = title.lower().replace(" ", "-")
    file_path = f"/tmp/{slug}.md"
    if tmp_path is not None:
        fp = tmp_path / f"{slug}.md"
        fp.write_text(
            f"# {title}\n\n## Key Claims\n- claim from {title}\n",
            encoding="utf-8",
        )
        file_path = str(fp)
    return Article(
        id=str(uuid.uuid4()),
        slug=slug,
        title=title,
        file_path=file_path,
        page_type=PageType.SOURCE,
    )


# ---------------------------------------------------------------------------
# _build_batch_prompt
# ---------------------------------------------------------------------------


def test_build_batch_prompt_formats_pairs() -> None:
    """Batch prompt includes all pair sections with correct indices."""
    pairs = [
        (_make_article("A1"), _make_article("A2"), ["claim1"], ["claim2"]),
        (_make_article("B1"), _make_article("B2"), ["claim3"], ["claim4"]),
    ]
    system, user = _build_batch_prompt(pairs)
    assert "2 article pairs" in user
    assert "Pair 0" in user
    assert "Pair 1" in user
    assert "wiki health auditor" in system


def test_build_batch_prompt_single_pair() -> None:
    """Batch prompt works with a single pair."""
    pairs = [
        (_make_article("X"), _make_article("Y"), ["c1"], ["c2"]),
    ]
    _system, user = _build_batch_prompt(pairs)
    assert "1 article pairs" in user
    assert "Pair 0" in user
    assert "Pair 1" not in user


def test_build_batch_prompt_includes_claims() -> None:
    """Batch prompt includes claims text from both articles."""
    pairs = [
        (
            _make_article("A"),
            _make_article("B"),
            ["The earth is round"],
            ["The earth is flat"],
        ),
    ]
    _system, user = _build_batch_prompt(pairs)
    assert "The earth is round" in user
    assert "The earth is flat" in user


# ---------------------------------------------------------------------------
# _parse_batch_response
# ---------------------------------------------------------------------------


def test_parse_batch_response_maps_by_index() -> None:
    """Response items are mapped to their pair_index."""
    response_data = [
        {
            "pair_index": 0,
            "contradictions": [
                {
                    "description": "d1",
                    "article_a_claim": "a",
                    "article_b_claim": "b",
                    "confidence": "high",
                },
            ],
        },
        {"pair_index": 1, "contradictions": []},
    ]
    result = _parse_batch_response(response_data, 2)
    assert len(result[0]) == 1
    assert len(result[1]) == 0


def test_parse_batch_response_handles_missing_index() -> None:
    """Missing pair_index entries get empty contradiction lists."""
    response_data = [{"pair_index": 0, "contradictions": []}]
    result = _parse_batch_response(response_data, 2)
    assert len(result[0]) == 0
    assert len(result[1]) == 0  # index 1 missing from response


def test_parse_batch_response_ignores_out_of_range_index() -> None:
    """Pair indices outside [0, expected_count) are ignored."""
    response_data = [
        {"pair_index": 5, "contradictions": [{"description": "bad"}]},
        {"pair_index": 0, "contradictions": []},
    ]
    result = _parse_batch_response(response_data, 2)
    assert len(result[0]) == 0
    assert len(result[1]) == 0
    assert 5 not in result


def test_parse_batch_response_empty_input() -> None:
    """Empty response still returns default empty lists."""
    result = _parse_batch_response([], 3)
    assert all(len(result[i]) == 0 for i in range(3))


# ---------------------------------------------------------------------------
# _run_batch (retry + fallback)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_batch_success(tmp_path: Path) -> None:
    """Successful batch call returns findings without fallback."""
    art_a = _make_article("Alpha", tmp_path)
    art_b = _make_article("Beta", tmp_path)
    pairs = [(art_a, art_b, ["claim A"], ["claim B"])]

    mock_response = MagicMock()
    mock_router = MagicMock()
    mock_router.complete = AsyncMock(return_value=mock_response)
    mock_router.parse_json_response = MagicMock(
        return_value=[
            {
                "pair_index": 0,
                "contradictions": [
                    {
                        "description": "test",
                        "article_a_claim": "cA",
                        "article_b_claim": "cB",
                        "confidence": "high",
                    },
                ],
            }
        ]
    )

    settings = MagicMock()
    settings.linter.contradiction_llm_max_tokens = 1024
    settings.linter.contradiction_llm_temperature = 0.2

    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None))))
    )
    session.flush = AsyncMock()

    findings = await _run_batch(pairs, "concept-1", mock_router, settings, "report-1", session)

    assert len(findings) == 1
    assert findings[0].description == "test"
    assert mock_router.complete.call_count == 1


@pytest.mark.asyncio
async def test_run_batch_retries_then_falls_back(tmp_path: Path) -> None:
    """On batch failure, retry once, then fall back to per-pair calls."""
    art_a = _make_article("Alpha", tmp_path)
    art_b = _make_article("Beta", tmp_path)
    pairs = [(art_a, art_b, ["claim A"], ["claim B"])]

    mock_router = MagicMock()
    mock_router.complete = AsyncMock(side_effect=RuntimeError("LLM exploded"))

    settings = MagicMock()
    settings.linter.contradiction_llm_max_tokens = 1024
    settings.linter.contradiction_llm_temperature = 0.2

    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None))))
    )
    session.flush = AsyncMock()

    with patch(
        "wikimind.engine.linter.contradictions._compare_article_pair",
        new_callable=AsyncMock,
        return_value=[],
    ) as mock_per_pair:
        findings = await _run_batch(pairs, "concept-1", mock_router, settings, "report-1", session)

    # router.complete called twice (initial + retry)
    assert mock_router.complete.call_count == 2
    # _compare_article_pair called once per pair (fallback)
    assert mock_per_pair.call_count == 1
    assert findings == []


@pytest.mark.asyncio
async def test_run_batch_retry_succeeds_on_second_attempt(tmp_path: Path) -> None:
    """If the first attempt fails but the retry succeeds, no fallback is used."""
    art_a = _make_article("Alpha", tmp_path)
    art_b = _make_article("Beta", tmp_path)
    pairs = [(art_a, art_b, ["claim A"], ["claim B"])]

    good_response = MagicMock()

    mock_router = MagicMock()
    mock_router.complete = AsyncMock(
        side_effect=[RuntimeError("transient"), good_response],
    )
    mock_router.parse_json_response = MagicMock(
        return_value=[{"pair_index": 0, "contradictions": []}],
    )

    settings = MagicMock()
    settings.linter.contradiction_llm_max_tokens = 1024
    settings.linter.contradiction_llm_temperature = 0.2

    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None))))
    )
    session.flush = AsyncMock()

    with patch(
        "wikimind.engine.linter.contradictions._compare_article_pair",
        new_callable=AsyncMock,
    ) as mock_per_pair:
        findings = await _run_batch(pairs, None, mock_router, settings, "r1", session)

    assert mock_router.complete.call_count == 2
    assert mock_per_pair.call_count == 0  # no fallback needed
    assert findings == []


@pytest.mark.asyncio
async def test_run_batch_parse_error_triggers_fallback(tmp_path: Path) -> None:
    """Unparseable response (not a list) triggers retry then fallback."""
    art_a = _make_article("Alpha", tmp_path)
    art_b = _make_article("Beta", tmp_path)
    pairs = [(art_a, art_b, ["claim A"], ["claim B"])]

    mock_response = MagicMock()
    mock_router = MagicMock()
    mock_router.complete = AsyncMock(return_value=mock_response)
    # Return a dict without "results" key -- triggers ValueError
    mock_router.parse_json_response = MagicMock(return_value={"unexpected": "shape"})

    settings = MagicMock()
    settings.linter.contradiction_llm_max_tokens = 1024
    settings.linter.contradiction_llm_temperature = 0.2

    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(first=MagicMock(return_value=None))))
    )
    session.flush = AsyncMock()

    with patch(
        "wikimind.engine.linter.contradictions._compare_article_pair",
        new_callable=AsyncMock,
        return_value=[],
    ) as mock_per_pair:
        await _run_batch(pairs, None, mock_router, settings, "r1", session)

    # Two attempts (both parse to bad shape), then fallback
    assert mock_router.complete.call_count == 2
    assert mock_per_pair.call_count == 1
