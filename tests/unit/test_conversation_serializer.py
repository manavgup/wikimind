"""Unit tests for the conversation → markdown serializer (ADR-011)."""

from datetime import datetime

from wikimind.engine.conversation_serializer import serialize_conversation_to_markdown
from wikimind.models import Conversation, Query


def _conv(title: str = "What is X?") -> Conversation:
    return Conversation(
        id="conv-1",
        title=title,
        created_at=datetime(2026, 4, 8, 12, 0, 0),
        updated_at=datetime(2026, 4, 8, 12, 5, 0),
    )


def _q(question: str, answer: str, turn_index: int = 0, sources: str = "[]") -> Query:
    return Query(
        id=f"q-{turn_index}",
        question=question,
        answer=answer,
        confidence="high",
        source_article_ids=sources,
        conversation_id="conv-1",
        turn_index=turn_index,
        created_at=datetime(2026, 4, 8, 12, 0, turn_index),
    )


def test_serializer_emits_frontmatter_with_required_fields():
    conv = _conv()
    queries = [_q("What is X?", "X is a thing.", turn_index=0)]
    md = serialize_conversation_to_markdown(conv, queries)

    assert md.startswith("---\n")
    assert 'title: "What is X?"' in md
    assert "type: qa-conversation" in md
    assert "turn_count: 1" in md
    assert "created: 2026-04-08T12:00:00" in md
    assert "updated: 2026-04-08T12:05:00" in md


def test_serializer_emits_one_section_per_turn_in_order():
    conv = _conv()
    queries = [
        _q("What is X?", "X is a thing.", turn_index=0),
        _q("How does it work?", "It works by Y.", turn_index=1),
        _q("Any limitations?", "Yes — Z.", turn_index=2),
    ]
    md = serialize_conversation_to_markdown(conv, queries)

    pos_q1 = md.find("Q1: What is X?")
    pos_q2 = md.find("Q2: How does it work?")
    pos_q3 = md.find("Q3: Any limitations?")
    assert 0 < pos_q1 < pos_q2 < pos_q3


def test_serializer_renders_sources_as_wikilinks():
    conv = _conv()
    queries = [_q("Q?", "A.", turn_index=0, sources='["Article One", "Article Two"]')]
    md = serialize_conversation_to_markdown(conv, queries)

    assert "[[Article One]]" in md
    assert "[[Article Two]]" in md


def test_serializer_handles_empty_sources():
    conv = _conv()
    queries = [_q("Q?", "A.", turn_index=0, sources="[]")]
    md = serialize_conversation_to_markdown(conv, queries)

    assert "Q1: Q?" in md
    assert "A." in md


def test_serializer_uses_conversation_title_as_h1():
    conv = _conv(title="My exploration")
    queries = [_q("First question", "First answer", turn_index=0)]
    md = serialize_conversation_to_markdown(conv, queries)

    assert "# My exploration" in md


def test_serializer_byte_identical_for_same_input():
    """Two calls with the same input must produce byte-identical output."""
    conv = _conv()
    queries = [_q("Q1", "A1", turn_index=0), _q("Q2", "A2", turn_index=1)]

    a = serialize_conversation_to_markdown(conv, queries)
    b = serialize_conversation_to_markdown(conv, queries)

    assert a == b


def test_serializer_escapes_double_quotes_in_title():
    """Title containing double quotes must produce valid YAML frontmatter."""
    conv = _conv(title='What is "AI"?')
    queries = [_q("Q?", "A.", turn_index=0)]
    md = serialize_conversation_to_markdown(conv, queries)

    # The title line should have escaped double quotes inside the outer quotes
    # so the YAML is parseable.
    assert 'title: "What is \\"AI\\"?"' in md


def test_serializer_uses_conversation_id_as_slug():
    """Slug is always the conversation's UUID id, regardless of the title content."""
    conv = _conv(title="!@#$%")
    queries = [_q("Q?", "A.", turn_index=0)]
    md = serialize_conversation_to_markdown(conv, queries)

    # Slug is the conversation id, not derived from the title.
    assert "slug: conv-1" in md


def test_serializer_handles_empty_queries_list():
    """A conversation with zero turns produces valid markdown (frontmatter + H1, no turn sections)."""
    conv = _conv()
    md = serialize_conversation_to_markdown(conv, [])

    assert md.startswith("---\n")
    assert "turn_count: 0" in md
    assert "# What is X?" in md
    # No Q-headers
    assert "## Q1:" not in md
