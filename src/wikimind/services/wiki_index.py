"""Regenerate ``{data_dir}/wiki/index.md`` content catalog from the database.

The index is a derived Markdown export grouped by concept, aimed at Obsidian
users and agent-first navigation. The DB remains the source of truth; this
file is rewritten in place on every call (NOT append-only).
"""

from __future__ import annotations

import contextlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from wikimind._datetime import utcnow_naive
from wikimind.config import get_settings
from wikimind.models import Article, Backlink, Concept, PageType

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


def _page_type_label(page_type: str) -> str:
    """Return a human-readable label for a page type."""
    labels: dict[str, str] = {
        PageType.SOURCE: "Source",
        PageType.CONCEPT: "Concept",
        PageType.ANSWER: "Answer",
        PageType.INDEX: "Index",
        PageType.META: "Meta",
    }
    return labels.get(page_type, str(page_type))


def _article_entry(article: Article) -> str:
    """Format a single article as a markdown list entry with optional type badge."""
    summary_part = ""
    if article.summary:
        summary_part = f" \u2014 {_first_sentence(article.summary)}"

    # Add page type badge for non-source articles
    type_badge = ""
    if article.page_type != PageType.SOURCE:
        type_badge = f" `[{_page_type_label(article.page_type)}]`"

    return f"- [[{article.slug}]]{type_badge}{summary_part}\n"


async def regenerate_index_md(session: AsyncSession) -> str:  # noqa: PLR0912
    """Regenerate the wiki/index.md content catalog from the database.

    Reads all Articles + their concepts, groups by concept, writes a
    markdown catalog with page_type frontmatter. Concept pages are shown
    prominently as entry points. Rewritten in place on every call
    (NOT append-only).

    Args:
        session: Async database session.

    Returns:
        The wiki-relative path string of the written file.
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

    # Count articles by page_type
    type_counts: Counter[str] = Counter()
    for article in articles:
        type_counts[article.page_type] += 1

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

        for raw_id in raw_ids:
            name = concept_map.get(raw_id, raw_id)
            concept_articles[name].append(article)

    # Build the markdown content with page_type frontmatter
    now = utcnow_naive()
    frontmatter = (
        f"---\npage_type: index\ntitle: Wiki Index\nslug: index\nscope: global\ngenerated: {now.isoformat()}\n---\n\n"
    )

    lines: list[str] = [frontmatter, _INDEX_HEADER]

    # Article counts by type
    if articles:
        lines.append(f"**{len(articles)} articles** \u2014 ")
        type_parts: list[str] = []
        for pt in [PageType.SOURCE, PageType.CONCEPT, PageType.ANSWER, PageType.INDEX, PageType.META]:
            count = type_counts.get(pt, 0)
            if count > 0:
                type_parts.append(f"{count} {_page_type_label(pt).lower()}")
        lines.append(", ".join(type_parts) + "\n\n")

    # Concept pages first (entry points)
    concept_page_articles = [a for a in articles if a.page_type == PageType.CONCEPT]
    if concept_page_articles:
        lines.append("## Concept Pages\n\n")
        for article in sorted(concept_page_articles, key=lambda a: a.slug):
            lines.append(_article_entry(article))
        lines.append("\n")

    # Concepts sorted alphabetically
    for concept_name in sorted(concept_articles):
        lines.append(f"## {concept_name}\n\n")
        for article in sorted(concept_articles[concept_name], key=lambda a: a.slug):
            lines.append(_article_entry(article))
        lines.append("\n")

    # Uncategorized section at the bottom
    if uncategorized:
        lines.append("## Uncategorized\n\n")
        for article in sorted(uncategorized, key=lambda a: a.slug):
            lines.append(_article_entry(article))
        lines.append("\n")

    index_path.write_text("".join(lines), encoding="utf-8")
    log.info("index.md regenerated", article_count=len(articles))
    return "index.md"


async def generate_meta_health_page(session: AsyncSession) -> str:
    """Generate a meta page with wiki health statistics.

    Creates ``wiki/meta/wiki-health.md`` with deterministic summary
    statistics: article counts by type, link counts by relation type,
    and orphan count. Called during linter runs or on-demand.

    Args:
        session: Async database session.

    Returns:
        The wiki-relative path string of the written meta page file.
    """
    settings = get_settings()
    meta_dir = Path(settings.data_dir) / "wiki" / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    health_path = meta_dir / "wiki-health.md"

    articles_result = await session.execute(select(Article))
    articles: list[Article] = list(articles_result.scalars().all())

    type_counts: Counter[str] = Counter()
    for article in articles:
        type_counts[article.page_type] += 1

    backlinks_result = await session.execute(select(Backlink))
    backlinks: list[Backlink] = list(backlinks_result.scalars().all())

    relation_counts: Counter[str] = Counter()
    for bl in backlinks:
        relation_counts[bl.relation_type] += 1

    linked_ids: set[str] = set()
    for bl in backlinks:
        linked_ids.add(bl.source_article_id)
        linked_ids.add(bl.target_article_id)
    orphan_count = sum(1 for a in articles if a.id not in linked_ids)

    now = utcnow_naive()
    frontmatter = f"---\npage_type: meta\ntitle: Wiki Health\nslug: wiki-health\ngenerated: {now.isoformat()}\n---\n\n"

    lines: list[str] = [frontmatter]
    lines.append("# Wiki Health\n\n")
    lines.append(f"Generated: {now.strftime('%Y-%m-%d %H:%M UTC')}\n\n")

    lines.append("## Articles by Type\n\n")
    lines.append("| Type | Count |\n")
    lines.append("|------|-------|\n")
    total = 0
    for pt in [PageType.SOURCE, PageType.CONCEPT, PageType.ANSWER, PageType.INDEX, PageType.META]:
        count = type_counts.get(pt, 0)
        total += count
        lines.append(f"| {_page_type_label(pt)} | {count} |\n")
    lines.append(f"| **Total** | **{total}** |\n")
    lines.append("\n")

    lines.append("## Links by Relation Type\n\n")
    lines.append("| Relation | Count |\n")
    lines.append("|----------|-------|\n")
    link_total = 0
    for rt in sorted(relation_counts.keys()):
        count = relation_counts[rt]
        link_total += count
        lines.append(f"| {rt} | {count} |\n")
    if link_total > 0:
        lines.append(f"| **Total** | **{link_total}** |\n")
    else:
        lines.append("| (none) | 0 |\n")
    lines.append("\n")

    lines.append("## Orphan Articles\n\n")
    lines.append(f"**{orphan_count}** articles with no inbound or outbound links.\n")

    health_path.write_text("".join(lines), encoding="utf-8")
    log.info("wiki-health.md generated", article_count=total, orphan_count=orphan_count)
    return "meta/wiki-health.md"
