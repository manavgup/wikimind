"""Regenerate ``{data_dir}/wiki/index.md`` content catalog from the database.

The index is a derived Markdown export grouped by concept, aimed at Obsidian
users and agent-first navigation. The DB remains the source of truth; this
file is rewritten in place on every call (NOT append-only).
"""

from __future__ import annotations

import contextlib
import json
from collections import Counter, defaultdict
from typing import TYPE_CHECKING, NamedTuple

import structlog
from sqlmodel import select

from wikimind._datetime import utcnow_naive
from wikimind.models import Article, ArticleConcept, Backlink, Concept, PageType
from wikimind.storage import get_wiki_storage

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

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


class GroupedArticles(NamedTuple):
    """Articles grouped by concept with uncategorized remainder."""

    by_concept: dict[str, list[Article]]
    uncategorized: list[Article]


async def _group_articles_by_concept(
    articles: list[Article],
    session: AsyncSession,
) -> GroupedArticles:
    """Group articles by concept name and identify uncategorized articles.

    Reads from the ArticleConcept join table with a fallback to the legacy
    ``Article.concept_ids`` JSON column for pre-migration data.

    Args:
        articles: All articles to categorize.
        session: Async database session.

    Returns:
        GroupedArticles with by_concept mapping and uncategorized list.
    """
    concepts_result = await session.execute(select(Concept))
    concept_map: dict[str, str] = {c.id: c.name for c in concepts_result.scalars().all()}

    ac_result = await session.execute(select(ArticleConcept))
    article_concept_map: dict[str, list[str]] = defaultdict(list)
    for ac in ac_result.scalars().all():
        article_concept_map[ac.article_id].append(ac.concept_name)

    concept_articles: dict[str, list[Article]] = defaultdict(list)
    uncategorized: list[Article] = []

    for article in articles:
        raw_ids = article_concept_map.get(article.id, [])
        # Fallback to JSON column for pre-migration data
        if not raw_ids and article.concept_ids:
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

    return GroupedArticles(concept_articles, uncategorized)


def _build_index_lines(
    articles: list[Article],
    concept_articles: dict[str, list[Article]],
    uncategorized: list[Article],
) -> list[str]:
    """Build the markdown lines for the wiki index page.

    Args:
        articles: All articles (for summary counts).
        concept_articles: Articles grouped by concept name.
        uncategorized: Articles not tagged with any concept.

    Returns:
        List of markdown strings to be joined into the index file.
    """
    now = utcnow_naive()
    frontmatter = (
        f"---\npage_type: index\ntitle: Wiki Index\nslug: index\nscope: global\ngenerated: {now.isoformat()}\n---\n\n"
    )

    lines: list[str] = [frontmatter, _INDEX_HEADER]

    # Article counts by type
    if articles:
        type_counts: Counter[str] = Counter(a.page_type for a in articles)
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
        lines.extend(_article_entry(a) for a in sorted(concept_page_articles, key=lambda a: a.slug))
        lines.append("\n")

    # Concepts sorted alphabetically
    for concept_name in sorted(concept_articles):
        lines.append(f"## {concept_name}\n\n")
        lines.extend(_article_entry(a) for a in sorted(concept_articles[concept_name], key=lambda a: a.slug))
        lines.append("\n")

    # Uncategorized section at the bottom
    if uncategorized:
        lines.append("## Uncategorized\n\n")
        lines.extend(_article_entry(a) for a in sorted(uncategorized, key=lambda a: a.slug))
        lines.append("\n")

    return lines


async def regenerate_index_md(
    session: AsyncSession,
    user_id: str,
) -> str:
    """Regenerate the wiki/index.md content catalog from the database.

    Reads all Articles + their concepts, groups by concept, writes a
    markdown catalog with page_type frontmatter. Concept pages are shown
    prominently as entry points. Rewritten in place on every call
    (NOT append-only).

    Args:
        session: Async database session.
        user_id: Optional user ID for data isolation.

    Returns:
        The wiki-relative path string of the written file.
    """
    wiki_storage = get_wiki_storage(user_id)

    article_stmt = select(Article)
    if user_id:
        article_stmt = article_stmt.where(Article.user_id == user_id)
    articles_result = await session.execute(article_stmt)
    articles: list[Article] = list(articles_result.scalars().all())

    concept_articles, uncategorized = await _group_articles_by_concept(articles, session)
    lines = _build_index_lines(articles, concept_articles, uncategorized)

    await wiki_storage.write("index.md", "".join(lines))
    log.info("index.md regenerated", article_count=len(articles))
    return "index.md"


class HealthData(NamedTuple):
    """Articles and backlinks fetched for the health page."""

    articles: list[Article]
    backlinks: list[Backlink]


async def _fetch_health_data(
    session: AsyncSession,
    user_id: str,
) -> HealthData:
    """Fetch articles and backlinks for the health page, scoped by user_id."""
    article_stmt = select(Article)
    if user_id:
        article_stmt = article_stmt.where(Article.user_id == user_id)
    articles_result = await session.execute(article_stmt)
    articles: list[Article] = list(articles_result.scalars().all())

    # Filter backlinks to only those between this user's articles
    article_ids = {a.id for a in articles}
    backlink_stmt = select(Backlink)
    if user_id:
        backlink_stmt = backlink_stmt.where(
            Backlink.source_article_id.in_(article_ids),  # type: ignore[attr-defined]
            Backlink.target_article_id.in_(article_ids),  # type: ignore[attr-defined]
        )
    backlinks_result = await session.execute(backlink_stmt)
    backlinks: list[Backlink] = list(backlinks_result.scalars().all())

    return HealthData(articles, backlinks)


async def generate_meta_health_page(
    session: AsyncSession,
    user_id: str,
) -> str:
    """Generate a meta page with wiki health statistics.

    Creates ``wiki/meta/wiki-health.md`` with deterministic summary
    statistics: article counts by type, link counts by relation type,
    and orphan count. Called during linter runs or on-demand.

    Args:
        session: Async database session.
        user_id: Optional user ID for data isolation.

    Returns:
        The wiki-relative path string of the written meta page file.
    """
    wiki_storage = get_wiki_storage(user_id)

    articles, backlinks = await _fetch_health_data(session, user_id=user_id)

    type_counts: Counter[str] = Counter()
    for article in articles:
        type_counts[article.page_type] += 1

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

    await wiki_storage.write("meta/wiki-health.md", "".join(lines))
    log.info("wiki-health.md generated", article_count=total, orphan_count=orphan_count)
    return "meta/wiki-health.md"
