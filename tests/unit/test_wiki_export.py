"""Tests for the full-wiki export service (wiki_export.py).

Covers filename sanitization, YAML frontmatter generation,
Obsidian ZIP export, and markdown+JSON ZIP export.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests.conftest import TEST_USER_ID
from wikimind.config import get_settings
from wikimind.models import (
    Article,
    ArticleConcept,
    WikiExportFormat,
)
from wikimind.services.wiki_export import (
    WikiExportService,
    _build_obsidian_frontmatter,
    _sanitize_filename,
    _strip_frontmatter,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# _sanitize_filename
# ---------------------------------------------------------------------------


class TestSanitizeFilename:
    def test_basic_title(self):
        assert _sanitize_filename("My Article") == "My Article"

    def test_replaces_slashes(self):
        assert _sanitize_filename("A/B\\C") == "A-B-C"

    def test_replaces_colons(self):
        assert _sanitize_filename("Part 1: Introduction") == "Part 1- Introduction"

    def test_removes_angle_brackets(self):
        assert _sanitize_filename("A <B> C") == "A B C"

    def test_removes_pipes(self):
        assert _sanitize_filename("A|B") == "A-B"

    def test_removes_quotes_and_special(self):
        assert _sanitize_filename('What is "AI"?') == "What is AI"

    def test_removes_asterisks(self):
        assert _sanitize_filename("foo*bar") == "foobar"

    def test_truncates_to_200_chars(self):
        long_title = "A" * 250
        result = _sanitize_filename(long_title)
        assert len(result) <= 200

    def test_strips_trailing_dots_and_spaces(self):
        assert _sanitize_filename("title ...") == "title"

    def test_empty_after_sanitization(self):
        """Edge case: a title composed entirely of illegal characters."""
        result = _sanitize_filename("<>?*")
        assert result == ""


# ---------------------------------------------------------------------------
# _strip_frontmatter
# ---------------------------------------------------------------------------


class TestStripFrontmatter:
    def test_strips_yaml_frontmatter(self):
        content = "---\ntitle: Test\nslug: test\n---\n# Body\n\nHello."
        result = _strip_frontmatter(content)
        assert result == "# Body\n\nHello."

    def test_no_frontmatter(self):
        content = "# No frontmatter here\n\nJust body."
        result = _strip_frontmatter(content)
        assert result == content

    def test_incomplete_frontmatter(self):
        content = "---\ntitle: broken"
        result = _strip_frontmatter(content)
        assert result == content

    def test_empty_content(self):
        assert _strip_frontmatter("") == ""


# ---------------------------------------------------------------------------
# _build_obsidian_frontmatter
# ---------------------------------------------------------------------------


class TestBuildObsidianFrontmatter:
    def _make_article(self, **overrides) -> Article:
        defaults = {
            "id": "art-1",
            "slug": "test-slug",
            "title": "Test Title",
            "file_path": "test.md",
            "user_id": TEST_USER_ID,
            "confidence": "high",
            "confidence_score": 0.95,
            "summary": "A short summary.",
        }
        defaults.update(overrides)
        return Article(**defaults)

    def test_basic_frontmatter(self):
        article = self._make_article()
        fm = _build_obsidian_frontmatter(article, ["concept-a", "concept-b"])
        assert fm.startswith("---\n")
        assert "title:" in fm
        assert "slug: test-slug" in fm
        assert "confidence: high" in fm
        assert "confidence_score: 0.95" in fm
        assert 'summary: "A short summary."' in fm
        assert "tags:" in fm
        assert "  - concept-a" in fm
        assert "  - concept-b" in fm
        assert fm.endswith("---\n\n")

    def test_no_concepts(self):
        article = self._make_article()
        fm = _build_obsidian_frontmatter(article, [])
        assert "tags:" not in fm

    def test_no_confidence(self):
        article = self._make_article(confidence=None, confidence_score=None)
        fm = _build_obsidian_frontmatter(article, [])
        assert "confidence:" not in fm
        assert "confidence_score:" not in fm

    def test_no_summary(self):
        article = self._make_article(summary=None)
        fm = _build_obsidian_frontmatter(article, [])
        assert "summary:" not in fm


# ---------------------------------------------------------------------------
# WikiExportService — full ZIP export
# ---------------------------------------------------------------------------


def _wiki_root() -> Path:
    """Return the wiki storage root for TEST_USER_ID and ensure it exists."""
    settings = get_settings()
    root = Path(settings.data_dir) / "wiki" / TEST_USER_ID
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.mark.asyncio
async def test_export_obsidian_zip(db_session: AsyncSession) -> None:
    """Obsidian export produces a ZIP with YAML frontmatter and .md files."""
    wiki = _wiki_root()
    (wiki / "alpha.md").write_text("# Alpha Article\n\nAlpha body content.")

    article = Article(
        id="art-alpha",
        slug="alpha",
        title="Alpha Article",
        file_path="alpha.md",
        summary="Alpha summary.",
        user_id=TEST_USER_ID,
    )
    db_session.add(article)

    concept = ArticleConcept(article_id="art-alpha", concept_name="testing")
    db_session.add(concept)
    await db_session.commit()

    service = WikiExportService()
    buf, filename, count = await service.export_wiki(db_session, TEST_USER_ID, fmt=WikiExportFormat.OBSIDIAN)

    assert count == 1
    assert filename.startswith("wikimind-obsidian-")
    assert filename.endswith(".zip")

    with zipfile.ZipFile(buf) as zf:
        names = zf.namelist()
        assert len(names) == 1
        assert names[0] == "Alpha Article.md"
        content = zf.read(names[0]).decode()
        assert "---" in content
        assert "title:" in content
        assert "slug: alpha" in content
        assert "  - testing" in content
        assert "Alpha body content." in content


@pytest.mark.asyncio
async def test_export_markdown_json_zip(db_session: AsyncSession) -> None:
    """Markdown+JSON export includes articles/ directory and metadata.json."""
    wiki = _wiki_root()
    (wiki / "beta.md").write_text("---\ntitle: Beta\n---\n# Beta Article\n\nBeta body.")

    article = Article(
        id="art-beta",
        slug="beta",
        title="Beta Article",
        file_path="beta.md",
        summary="Beta summary.",
        user_id=TEST_USER_ID,
    )
    db_session.add(article)
    await db_session.commit()

    service = WikiExportService()
    buf, filename, count = await service.export_wiki(db_session, TEST_USER_ID, fmt=WikiExportFormat.MARKDOWN_JSON)

    assert count == 1
    assert filename.startswith("wikimind-export-")
    assert filename.endswith(".zip")

    with zipfile.ZipFile(buf) as zf:
        names = zf.namelist()
        assert "articles/Beta Article.md" in names
        assert "metadata.json" in names

        # Frontmatter should be stripped in the markdown+JSON format
        md_content = zf.read("articles/Beta Article.md").decode()
        assert "---" not in md_content
        assert "Beta body." in md_content

        metadata = json.loads(zf.read("metadata.json").decode())
        assert metadata["format"] == "wikimind-export-v1"
        assert metadata["article_count"] == 1
        assert len(metadata["articles"]) == 1
        art_meta = metadata["articles"][0]
        assert art_meta["slug"] == "beta"
        assert art_meta["title"] == "Beta Article"


@pytest.mark.asyncio
async def test_export_empty_wiki(db_session: AsyncSession) -> None:
    """Exporting an empty wiki produces a valid but empty ZIP."""
    service = WikiExportService()
    buf, filename, count = await service.export_wiki(db_session, TEST_USER_ID, fmt=WikiExportFormat.OBSIDIAN)

    assert count == 0
    with zipfile.ZipFile(buf) as zf:
        assert len(zf.namelist()) == 0


@pytest.mark.asyncio
async def test_export_multiple_articles(db_session: AsyncSession) -> None:
    """Export with multiple articles includes all of them."""
    wiki = _wiki_root()
    for i in range(3):
        (wiki / f"art-{i}.md").write_text(f"# Article {i}\n\nBody {i}.")
        article = Article(
            id=f"art-{i}",
            slug=f"article-{i}",
            title=f"Article {i}",
            file_path=f"art-{i}.md",
            user_id=TEST_USER_ID,
        )
        db_session.add(article)
    await db_session.commit()

    service = WikiExportService()
    buf, _, count = await service.export_wiki(db_session, TEST_USER_ID, fmt=WikiExportFormat.OBSIDIAN)

    assert count == 3
    with zipfile.ZipFile(buf) as zf:
        assert len(zf.namelist()) == 3
