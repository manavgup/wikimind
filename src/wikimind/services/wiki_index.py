"""Regenerate ``{data_dir}/wiki/index.md`` content catalog from the database.

The index is a derived Markdown export grouped by concept, aimed at Obsidian
users and agent-first navigation. The DB remains the source of truth; this
file is rewritten in place on every call (NOT append-only).
"""

from __future__ import annotations

import contextlib
import json
from collections import defaultdict
from pathlib import Path

import structlog
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.config import get_settings
from wikimind.models import Article, Concept

log = structlog.get_logger()

_INDEX_HEADER = "# Wiki Index\n\n"

_SUMMARY_MAX_CHARS = 120


def _first_sentence(text: str) -> str:
    """Extract the first sentence from *text*, capped at 120 characters.

    Splits on ``. `` (period-space) to avoid breaking on abbreviations like
    ``e.g.`` or decimal numbers. Falls back to the full text when no sentence
    boundary is found.
    """
    dot_pos = text.find(". ")
    sentence = text[: dot_pos + 1] if dot_pos != -1 else text
    if len(sentence) > _SUMMARY_MAX_CHARS:
        return sentence[: _SUMMARY_MAX_CHARS - 1] + "\u2026"
    return sentence


async def regenerate_index_md(session: AsyncSession) -> Path:
    """Regenerate the wiki/index.md content catalog from the database.

    Reads all Articles + their concepts, groups by concept, writes a
    markdown catalog. Rewritten in place on every call (NOT append-only).

    Args:
        session: Async database session.

    Returns:
        The Path to the written file.
    """
    settings = get_settings()
    wiki_dir = Path(settings.data_dir) / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    index_path = wiki_dir / "index.md"

    # Fetch all articles and concepts
    articles_result = await session.execute(select(Article))
    articles: list[Article] = list(articles_result.scalars().all())

    concepts_result = await session.execute(select(Concept))
    concepts: list[Concept] = list(concepts_result.scalars().all())
    concept_map: dict[str, str] = {c.id: c.name for c in concepts}

    # Group articles by concept name
    concept_articles: dict[str, list[Article]] = defaultdict(list)
    uncategorized: list[Article] = []

    for article in articles:
        raw_ids: list[str] = []
        if article.concept_ids:
            with contextlib.suppress(json.JSONDecodeError, TypeError):
                parsed = json.loads(article.concept_ids)
                if isinstance(parsed, list):
                    raw_ids = [str(v) for v in parsed if v]

        if not raw_ids:
            uncategorized.append(article)
            continue

        # The compiler stores concept *names* (not UUIDs) in concept_ids.
        # Try the Concept table first (UUID → name); fall back to using
        # the raw value directly as the heading (which is a name already).
        for raw_id in raw_ids:
            name = concept_map.get(raw_id, raw_id)
            concept_articles[name].append(article)

    # Build the markdown content
    lines: list[str] = [_INDEX_HEADER]

    # Concepts sorted alphabetically, articles sorted alphabetically within each
    for concept_name in sorted(concept_articles):
        lines.append(f"## {concept_name}\n\n")
        for article in sorted(concept_articles[concept_name], key=lambda a: a.slug):
            summary_part = ""
            if article.summary:
                summary_part = f" \u2014 {_first_sentence(article.summary)}"
            lines.append(f"- [[{article.slug}]]{summary_part}\n")
        lines.append("\n")

    # Uncategorized section at the bottom
    if uncategorized:
        lines.append("## Uncategorized\n\n")
        for article in sorted(uncategorized, key=lambda a: a.slug):
            summary_part = ""
            if article.summary:
                summary_part = f" \u2014 {_first_sentence(article.summary)}"
            lines.append(f"- [[{article.slug}]]{summary_part}\n")
        lines.append("\n")

    index_path.write_text("".join(lines), encoding="utf-8")
    log.info("index.md regenerated", article_count=len(articles))
    return index_path
