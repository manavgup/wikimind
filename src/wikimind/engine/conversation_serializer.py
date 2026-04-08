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

from slugify import slugify

from wikimind.models import Conversation, Query


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
    slug = slugify(conversation.title)[:80] or "untitled-conversation"
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
        lines.append(query.answer)
        lines.append("")

        # Sources block — omitted if no sources
        sources = _parse_sources(query.source_article_ids)
        if sources:
            lines.append("**Sources:** " + ", ".join(f"[[{s}]]" for s in sources))
            lines.append("")

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
