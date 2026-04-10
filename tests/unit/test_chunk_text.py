"""Tests for chunk_text token-aware fallback (issue #110).

Verifies that chunk_text correctly splits text that exceeds max_chunk_tokens
regardless of whether the input has markdown headings, paragraph boundaries,
or neither.
"""

from __future__ import annotations

import re

from wikimind.ingest.service import chunk_text, estimate_tokens


def _join_chunk_content(chunks: list) -> str:
    """Concatenate chunk contents, stripping whitespace for comparison."""
    return "".join(c.content for c in chunks)


# -----------------------------------------------------------------------
# Heading-based splitting still works as before
# -----------------------------------------------------------------------


def test_heading_based_splitting_unchanged() -> None:
    """Documents with headings and small sections should produce heading-based chunks."""
    text = "# Intro\n\nSome intro text.\n\n## Details\n\nSome details."
    chunks = chunk_text(text, "doc-1", max_chunk_tokens=100)
    assert len(chunks) >= 1
    # All chunks should be within the limit
    for c in chunks:
        assert c.token_count <= 100


def test_small_document_single_chunk() -> None:
    """A small document should remain a single chunk."""
    text = "Hello, this is a small document."
    chunks = chunk_text(text, "doc-1", max_chunk_tokens=4000)
    assert len(chunks) == 1
    assert chunks[0].content == text


# -----------------------------------------------------------------------
# No-headings fallback: paragraph splitting
# -----------------------------------------------------------------------


def test_no_headings_large_doc_splits_into_multiple_chunks() -> None:
    """A large document with no headings and >max_chunk_tokens must be split."""
    # Create ~8000 tokens of text (32000 chars at 4 chars/token) with paragraphs
    paragraphs = [f"Paragraph {i}. " + ("word " * 200) for i in range(40)]
    text = "\n\n".join(paragraphs)
    assert estimate_tokens(text) > 4000

    chunks = chunk_text(text, "doc-1", max_chunk_tokens=4000)
    assert len(chunks) > 1


def test_no_headings_all_chunks_under_limit() -> None:
    """Every chunk must be under max_chunk_tokens, even without headings."""
    paragraphs = [f"Para {i}. " + ("word " * 200) for i in range(40)]
    text = "\n\n".join(paragraphs)
    max_tokens = 2000

    chunks = chunk_text(text, "doc-1", max_chunk_tokens=max_tokens)
    for i, c in enumerate(chunks):
        assert c.token_count <= max_tokens, f"Chunk {i} has {c.token_count} tokens, exceeds limit {max_tokens}"


def test_paragraph_boundary_splitting() -> None:
    """When headings produce oversized chunks, paragraph boundaries are used."""
    # Two paragraphs, each ~600 tokens, no headings.  With max=500,
    # heading split yields one big chunk; paragraph split should yield two.
    para_a = "Alpha. " + ("aaa " * 600)
    para_b = "Beta. " + ("bbb " * 600)
    text = para_a + "\n\n" + para_b

    chunks = chunk_text(text, "doc-1", max_chunk_tokens=500)
    assert len(chunks) >= 2
    for c in chunks:
        assert c.token_count <= 500


# -----------------------------------------------------------------------
# Fixed-window fallback when paragraphs are also huge
# -----------------------------------------------------------------------


def test_single_huge_paragraph_uses_token_window() -> None:
    r"""A single giant paragraph (no \n\n) must still be split via token window."""
    # ~5000 tokens in one paragraph (no double-newline breaks)
    text = "word " * 5000
    max_tokens = 1000

    chunks = chunk_text(text, "doc-1", max_chunk_tokens=max_tokens)
    assert len(chunks) >= 5
    for i, c in enumerate(chunks):
        assert c.token_count <= max_tokens, f"Chunk {i} has {c.token_count} tokens, exceeds limit {max_tokens}"


def test_token_window_splits_on_whitespace() -> None:
    """Token-window fallback should not split mid-word."""
    # Create text with long words separated by single spaces
    text = "abcdefghij " * 2000  # 11 chars per unit, ~5500 tokens
    max_tokens = 1000

    chunks = chunk_text(text, "doc-1", max_chunk_tokens=max_tokens)
    for c in chunks:
        # No chunk content should start or end with a partial word fragment
        # that was cut mid-character. Since we split on spaces, content
        # should be clean.
        assert not c.content.startswith(" ")
        assert c.token_count <= max_tokens


# -----------------------------------------------------------------------
# Content preservation
# -----------------------------------------------------------------------


def test_all_text_preserved_no_headings() -> None:
    """Concatenated chunk content should equal the original text (modulo whitespace)."""
    paragraphs = [f"Paragraph {i}. " + ("content " * 200) for i in range(20)]
    text = "\n\n".join(paragraphs)

    chunks = chunk_text(text, "doc-1", max_chunk_tokens=1000)
    # Reconstruct: join with the same separator and compare stripped versions
    reconstructed = "".join(c.content for c in chunks)
    # Remove all whitespace for comparison since splitting may alter spacing
    original_no_ws = "".join(text.split())
    reconstructed_no_ws = "".join(reconstructed.split())
    assert original_no_ws == reconstructed_no_ws


def test_all_text_preserved_with_headings() -> None:
    """Body text (non-heading lines) is preserved when heading-based splitting is used.

    Headings are stored in ``heading_path`` rather than chunk content, so
    only the body text needs to match.
    """
    text = "# Title\n\nSome intro.\n\n## Section\n\nMore content here."
    chunks = chunk_text(text, "doc-1", max_chunk_tokens=4000)
    reconstructed = "".join(c.content for c in chunks)
    # Strip heading lines from the original for comparison — headings go
    # into heading_path, not content.
    body_only = re.sub(r"#{1,3} .+", "", text)
    original_no_ws = "".join(body_only.split())
    reconstructed_no_ws = "".join(reconstructed.split())
    assert original_no_ws == reconstructed_no_ws


def test_all_text_preserved_token_window() -> None:
    """Text is preserved even when the token-window fallback is used."""
    text = "word " * 5000
    chunks = chunk_text(text, "doc-1", max_chunk_tokens=500)
    reconstructed = "".join(c.content for c in chunks)
    original_no_ws = "".join(text.split())
    reconstructed_no_ws = "".join(reconstructed.split())
    assert original_no_ws == reconstructed_no_ws


# -----------------------------------------------------------------------
# Chunk metadata
# -----------------------------------------------------------------------


def test_chunk_indices_are_sequential() -> None:
    """Chunk indices should be 0, 1, 2, ... with no gaps."""
    text = "word " * 5000
    chunks = chunk_text(text, "doc-1", max_chunk_tokens=500)
    indices = [c.chunk_index for c in chunks]
    assert indices == list(range(len(chunks)))


def test_chunk_document_id() -> None:
    """All chunks should carry the correct document_id."""
    text = "word " * 5000
    chunks = chunk_text(text, "my-doc-42", max_chunk_tokens=500)
    for c in chunks:
        assert c.document_id == "my-doc-42"


# -----------------------------------------------------------------------
# Edge cases
# -----------------------------------------------------------------------


def test_empty_text() -> None:
    """Empty text should return one chunk with the original text."""
    chunks = chunk_text("", "doc-1")
    assert len(chunks) == 1


def test_text_exactly_at_limit() -> None:
    """Text exactly at the token limit should not be split further."""
    # 4000 tokens = 16000 chars
    text = "a" * 16000
    chunks = chunk_text(text, "doc-1", max_chunk_tokens=4000)
    assert len(chunks) == 1
    assert chunks[0].token_count == 4000
