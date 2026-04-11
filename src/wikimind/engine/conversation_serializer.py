"""Serialize a Q&A conversation to wiki article markdown.

Single source of truth for thread → markdown conversion. Used by the
file-back path (which writes the result to disk and creates an Article
row) and by the upcoming conversation-export endpoint (#91, which
returns it directly without persisting). The two paths MUST produce
byte-identical output for the same input.

See ADR-011.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from wikimind.models import Conversation, Query

# Match a line that starts with 1-4 # characters followed by a space.
# Capped at H4 because downshifting H5/H6 by 2 levels would yield H7/H8
# which doesn't render in HTML — those rare cases are left alone.
_HEADING_RE = re.compile(r"^(#{1,4}) ", flags=re.MULTILINE)


def _downshift_answer_headings(answer: str) -> str:
    """Downshift markdown headings in an answer body by 2 levels.

    The serialized conversation places each answer underneath a `## Q{n}:`
    turn header. The LLM's own answer body often starts with its own H1
    (a restatement of the question), which produces a triple-titled
    document where the same title appears 3 times in a row at the top.

    Downshifting all of the answer's headings by 2 levels (H1→H3, H2→H4,
    H3→H5, H4→H6) makes them nest correctly under the Q-turn header
    instead of competing with the article-level H1. The hierarchy is
    preserved, no content is removed.

    H5 and H6 in the answer are left alone because downshifting them
    further would yield non-renderable H7/H8.
    """
    return _HEADING_RE.sub(lambda m: "##" + m.group(1) + " ", answer)


def serialize_conversation_to_markdown(
    conversation: Conversation,
    queries: list[Query],
) -> str:
    """Serialize a conversation and its turns into wiki article markdown.

    Args:
        conversation: The Conversation row.
        queries: All Query rows for the conversation, ordered by turn_index.

    Returns:
        Markdown string with frontmatter and one section per turn.
    """
    slug = conversation.id
    turn_count = len(queries)

    lines: list[str] = []
    lines.append("---")
    escaped_title = conversation.title.replace('"', '\\"')
    lines.append(f'title: "{escaped_title}"')
    lines.append(f"slug: {slug}")
    lines.append("type: qa-conversation")
    lines.append(f"created: {conversation.created_at.isoformat()}")
    lines.append(f"updated: {conversation.updated_at.isoformat()}")
    lines.append(f"turn_count: {turn_count}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {conversation.title}")
    lines.append("")

    for query in queries:
        turn_number = query.turn_index + 1  # 1-indexed in the document
        lines.append(f"## Q{turn_number}: {query.question}")
        lines.append("")
        lines.append(_downshift_answer_headings(query.answer))
        lines.append("")

        # Sources block — omitted if no sources
        sources = _parse_sources(query.source_article_ids)
        if sources:
            lines.append("**Sources:** " + ", ".join(f"[[{s}]]" for s in sources))
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


@dataclass
class SelectedTurn:
    """A turn selected for partial/multi-thread file-back.

    Groups a Query with the conversation it belongs to, preserving the
    original turn_index for gap detection.
    """

    conversation: Conversation
    query: Query


def serialize_selected_turns_to_markdown(
    turns: list[SelectedTurn],
    title: str | None = None,
) -> str:
    """Serialize selected turns from one or more conversations into wiki markdown.

    Supports partial-thread saves (subset of turns from one conversation) and
    multi-thread merges (turns from multiple conversations combined into one
    article). Output turns are numbered Q1, Q2, Q3... continuously regardless
    of original turn indices.

    Gap separators (``---``) are inserted:
    - Between non-contiguous turns within the same conversation
    - At conversation boundaries when merging multiple threads

    Args:
        turns: Ordered list of selected turns. Caller determines the order.
        title: Custom article title. Defaults to the first conversation's title.

    Returns:
        Markdown string with frontmatter and one section per selected turn.
    """
    if not turns:
        effective_title = title or "Untitled"
        return f'---\ntitle: "{effective_title}"\ntype: qa-selection\nturn_count: 0\n---\n\n# {effective_title}\n'

    effective_title = title or turns[0].conversation.title
    turn_count = len(turns)

    lines: list[str] = []
    lines.append("---")
    escaped_title = effective_title.replace('"', '\\"')
    lines.append(f'title: "{escaped_title}"')
    lines.append("type: qa-selection")
    lines.append(f"turn_count: {turn_count}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {effective_title}")
    lines.append("")

    prev_conv_id: str | None = None
    prev_turn_index: int | None = None

    for output_num, selected in enumerate(turns, start=1):
        conv_id = selected.conversation.id
        query = selected.query

        # Insert gap separator when needed
        need_separator = False
        if prev_conv_id is not None:
            if conv_id != prev_conv_id:
                # Cross-conversation boundary
                need_separator = True
            elif prev_turn_index is not None and query.turn_index != prev_turn_index + 1:
                # Non-contiguous turns within the same conversation
                need_separator = True

        if need_separator:
            lines.append("---")
            lines.append("")

        lines.append(f"## Q{output_num}: {query.question}")
        lines.append("")
        lines.append(_downshift_answer_headings(query.answer))
        lines.append("")

        sources = _parse_sources(query.source_article_ids)
        if sources:
            lines.append("**Sources:** " + ", ".join(f"[[{s}]]" for s in sources))
            lines.append("")

        prev_conv_id = conv_id
        prev_turn_index = query.turn_index

    return "\n".join(lines).rstrip() + "\n"


def _parse_sources(raw: str | None) -> list[str]:
    """Parse the JSON-encoded source_article_ids field into a list of titles."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if item]
