"""Full-wiki export service — portable export in Obsidian or plain markdown+JSON format.

Exports the user's entire wiki (or a filtered subset) as a ZIP archive.
Obsidian format uses YAML frontmatter and [[wikilinks]]. The plain
markdown+JSON format includes a metadata.json sidecar for lossless
round-tripping.
"""

import io
import json
import zipfile
from datetime import UTC, datetime

import structlog
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.models import (
    Article,
    ArticleConcept,
    WikiExportFormat,
)
from wikimind.storage import read_article_content

log = structlog.get_logger()


def _sanitize_filename(title: str) -> str:
    """Convert a title to a safe filesystem name.

    Replaces characters that are illegal on Windows/macOS/Linux filesystems
    and truncates to 200 characters.
    """
    safe = title.replace("/", "-").replace("\\", "-").replace(":", "-")
    safe = safe.replace("<", "").replace(">", "").replace("|", "-")
    safe = safe.replace('"', "").replace("?", "").replace("*", "")
    return safe[:200].strip(". ")


def _build_obsidian_frontmatter(article: Article, concepts: list[str]) -> str:
    """Build YAML frontmatter for an Obsidian-compatible markdown file."""
    lines = ["---"]
    lines.append(f"title: {json.dumps(article.title)}")
    lines.append(f"slug: {article.slug}")
    lines.append(f"page_type: {article.page_type}")
    if article.confidence:
        lines.append(f"confidence: {article.confidence}")
    if article.confidence_score is not None:
        lines.append(f"confidence_score: {article.confidence_score}")
    if article.summary:
        lines.append(f"summary: {json.dumps(article.summary)}")
    lines.append(f"created_at: {article.created_at.isoformat()}")
    lines.append(f"updated_at: {article.updated_at.isoformat()}")
    if concepts:
        lines.append("tags:")
        lines.extend(f"  - {c}" for c in concepts)
    lines.append("---")
    return "\n".join(lines) + "\n\n"


def _strip_frontmatter(content: str) -> str:
    """Remove YAML frontmatter from markdown content if present."""
    if content.startswith("---"):
        end = content.find("\n---\n", 3)
        if end != -1:
            return content[end + 5 :]
    return content


class WikiExportService:
    """Export a user's full wiki as a ZIP archive."""

    async def export_wiki(
        self,
        session: AsyncSession,
        user_id: str,
        fmt: WikiExportFormat = WikiExportFormat.OBSIDIAN,
    ) -> tuple[io.BytesIO, str, int]:
        """Export the full wiki as a ZIP archive.

        Args:
            session: Database session.
            user_id: Owner of the wiki.
            fmt: Export format (obsidian or markdown_json).

        Returns:
            Tuple of (zip bytes buffer, suggested filename, article count).
        """
        result = await session.exec(select(Article).where(Article.user_id == user_id).order_by(Article.title))
        articles = list(result.all())

        # Pre-load concepts for all articles
        concepts_map: dict[str, list[str]] = {}
        if articles:
            article_ids = [a.id for a in articles]
            concept_result = await session.execute(
                select(ArticleConcept).where(
                    ArticleConcept.article_id.in_(article_ids)  # type: ignore[attr-defined]
                )
            )
            for ac in concept_result.scalars().all():
                concepts_map.setdefault(ac.article_id, []).append(ac.concept_name)

        # Read all article contents asynchronously before building ZIP
        contents = await self._read_all_contents(articles, user_id)

        buf = io.BytesIO()
        timestamp = datetime.now(tz=UTC).strftime("%Y%m%d-%H%M%S")

        if fmt == WikiExportFormat.OBSIDIAN:
            filename = f"wikimind-obsidian-{timestamp}.zip"
            self._build_obsidian_zip(buf, articles, concepts_map, contents)
        else:
            filename = f"wikimind-export-{timestamp}.zip"
            self._build_markdown_json_zip(buf, articles, concepts_map, contents)

        buf.seek(0)
        return buf, filename, len(articles)

    async def _read_all_contents(
        self,
        articles: list[Article],
        user_id: str,
    ) -> dict[str, str]:
        """Read markdown content for all articles, keyed by article ID."""
        contents: dict[str, str] = {}
        for article in articles:
            raw = await read_article_content(article.file_path, user_id=user_id)
            contents[article.id] = raw
        return contents

    def _build_obsidian_zip(
        self,
        buf: io.BytesIO,
        articles: list[Article],
        concepts_map: dict[str, list[str]],
        contents: dict[str, str],
    ) -> None:
        """Build an Obsidian-flavored markdown vault ZIP."""
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for article in articles:
                concepts = concepts_map.get(article.id, [])
                raw_content = contents.get(article.id, "")
                body = _strip_frontmatter(raw_content) if raw_content else ""
                frontmatter = _build_obsidian_frontmatter(article, concepts)
                full_content = frontmatter + body

                safe_name = _sanitize_filename(article.title)
                zf.writestr(f"{safe_name}.md", full_content)

    def _build_markdown_json_zip(
        self,
        buf: io.BytesIO,
        articles: list[Article],
        concepts_map: dict[str, list[str]],
        contents: dict[str, str],
    ) -> None:
        """Build a plain markdown + JSON metadata ZIP."""
        metadata_entries: list[dict] = []
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for article in articles:
                concepts = concepts_map.get(article.id, [])
                raw_content = contents.get(article.id, "")
                body = _strip_frontmatter(raw_content) if raw_content else ""

                safe_name = _sanitize_filename(article.title)
                zf.writestr(f"articles/{safe_name}.md", body)

                metadata_entries.append(
                    {
                        "id": article.id,
                        "slug": article.slug,
                        "title": article.title,
                        "page_type": article.page_type,
                        "confidence": article.confidence,
                        "confidence_score": article.confidence_score,
                        "summary": article.summary,
                        "concepts": concepts,
                        "created_at": article.created_at.isoformat(),
                        "updated_at": article.updated_at.isoformat(),
                        "filename": f"{safe_name}.md",
                    }
                )

            zf.writestr(
                "metadata.json",
                json.dumps(
                    {
                        "format": "wikimind-export-v1",
                        "exported_at": datetime.now(tz=UTC).isoformat(),
                        "article_count": len(articles),
                        "articles": metadata_entries,
                    },
                    indent=2,
                ),
            )
