"""Tests for wiki/index.md content catalog generation."""

from __future__ import annotations

import json

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from wikimind.models import Article, Concept
from wikimind.services.wiki_index import (
    _INDEX_HEADER,
    _SUMMARY_MAX_CHARS,
    _first_sentence,
    regenerate_index_md,
)
from wikimind.storage import resolve_wiki_path


class TestFirstSentence:
    """Unit tests for the _first_sentence helper."""

    def test_extracts_first_sentence(self) -> None:
        text = "This is the first sentence. This is the second."
        assert _first_sentence(text) == "This is the first sentence."

    def test_returns_full_text_when_no_period_space(self) -> None:
        text = "No period at end"
        assert _first_sentence(text) == "No period at end"

    def test_truncates_long_sentence(self) -> None:
        text = "A" * 200 + ". Second sentence."
        result = _first_sentence(text)
        assert len(result) <= _SUMMARY_MAX_CHARS
        assert result.endswith("\u2026")

    def test_does_not_truncate_short_sentence(self) -> None:
        text = "Short sentence. Another one."
        result = _first_sentence(text)
        assert result == "Short sentence."
        assert "\u2026" not in result


class TestRegenerateIndexMd:
    """Unit tests for regenerate_index_md."""

    @pytest.mark.anyio
    async def test_empty_database_produces_header_only(self, db_session: AsyncSession) -> None:
        """An empty DB should produce a file with frontmatter and the header."""
        rel = await regenerate_index_md(db_session)
        path = resolve_wiki_path(rel)
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "page_type: index" in content
        assert _INDEX_HEADER in content

    @pytest.mark.anyio
    async def test_articles_grouped_by_concept(self, db_session: AsyncSession) -> None:
        """Articles should appear under their concept headings."""
        # Create concepts
        c1 = Concept(id="c1", name="Databases")
        c2 = Concept(id="c2", name="Algorithms")
        db_session.add_all([c1, c2])
        await db_session.commit()

        # Create articles with concept_ids
        a1 = Article(
            slug="postgres-internals",
            title="Postgres Internals",
            file_path="/wiki/postgres-internals.md",
            concept_ids=json.dumps(["c1"]),
            summary="How Postgres works internally. Deep dive into storage.",
        )
        a2 = Article(
            slug="sorting-algorithms",
            title="Sorting Algorithms",
            file_path="/wiki/sorting-algorithms.md",
            concept_ids=json.dumps(["c2"]),
            summary="Overview of sorting algorithms. Comparison based approaches.",
        )
        db_session.add_all([a1, a2])
        await db_session.commit()

        rel = await regenerate_index_md(db_session)
        path = resolve_wiki_path(rel)
        content = path.read_text(encoding="utf-8")

        # Both concept headings should appear
        assert "## Algorithms" in content
        assert "## Databases" in content

        # Articles under correct headings
        assert "- [[sorting-algorithms]]" in content
        assert "- [[postgres-internals]]" in content

        # Alphabetical order: Algorithms before Databases
        assert content.index("## Algorithms") < content.index("## Databases")

    @pytest.mark.anyio
    async def test_uncategorized_section(self, db_session: AsyncSession) -> None:
        """Articles without concepts should land in Uncategorized."""
        a1 = Article(
            slug="random-note",
            title="Random Note",
            file_path="/wiki/random-note.md",
            concept_ids=None,
            summary="A note with no concept.",
        )
        db_session.add(a1)
        await db_session.commit()

        rel = await regenerate_index_md(db_session)
        path = resolve_wiki_path(rel)
        content = path.read_text(encoding="utf-8")

        assert "## Uncategorized" in content
        assert "- [[random-note]]" in content

    @pytest.mark.anyio
    async def test_unresolved_concept_ids_used_as_raw_headings(self, db_session: AsyncSession) -> None:
        """Concept names that don't match Concept table rows are used directly as headings."""
        a1 = Article(
            slug="orphan-article",
            title="Orphan Article",
            file_path="/wiki/orphan.md",
            concept_ids=json.dumps(["Machine Learning"]),
            summary="This concept name is used directly.",
        )
        db_session.add(a1)
        await db_session.commit()

        rel = await regenerate_index_md(db_session)
        path = resolve_wiki_path(rel)
        content = path.read_text(encoding="utf-8")

        assert "## Machine Learning" in content
        assert "- [[orphan-article]]" in content
        assert "## Uncategorized" not in content

    @pytest.mark.anyio
    async def test_entry_format(self, db_session: AsyncSession) -> None:
        """Each entry should be: - [[slug]] -- summary first sentence."""
        c1 = Concept(id="c1", name="Testing")
        db_session.add(c1)
        await db_session.commit()

        a1 = Article(
            slug="unit-testing-guide",
            title="Unit Testing Guide",
            file_path="/wiki/unit-testing-guide.md",
            concept_ids=json.dumps(["c1"]),
            summary="How to write effective unit tests. Covers mocking and fixtures.",
        )
        db_session.add(a1)
        await db_session.commit()

        rel = await regenerate_index_md(db_session)
        path = resolve_wiki_path(rel)
        content = path.read_text(encoding="utf-8")

        expected = "- [[unit-testing-guide]] \u2014 How to write effective unit tests."
        assert expected in content

    @pytest.mark.anyio
    async def test_summary_truncation(self, db_session: AsyncSession) -> None:
        """Summaries longer than 120 chars should be truncated with an ellipsis."""
        c1 = Concept(id="c1", name="Long")
        db_session.add(c1)
        await db_session.commit()

        long_sentence = "A" * 200 + ". Second."
        a1 = Article(
            slug="long-summary",
            title="Long Summary",
            file_path="/wiki/long-summary.md",
            concept_ids=json.dumps(["c1"]),
            summary=long_sentence,
        )
        db_session.add(a1)
        await db_session.commit()

        rel = await regenerate_index_md(db_session)
        path = resolve_wiki_path(rel)
        content = path.read_text(encoding="utf-8")

        # The entry line should contain a truncated summary
        for line in content.splitlines():
            if "[[long-summary]]" in line:
                # Extract the summary part after the em dash
                summary_part = line.split("\u2014 ", 1)[1]
                assert len(summary_part) <= _SUMMARY_MAX_CHARS
                assert summary_part.endswith("\u2026")
                break
        else:
            pytest.fail("Entry for long-summary not found")

    @pytest.mark.anyio
    async def test_regeneration_overwrites(self, db_session: AsyncSession) -> None:
        """Calling regenerate twice should overwrite, not append."""
        a1 = Article(
            slug="first-article",
            title="First Article",
            file_path="/wiki/first-article.md",
            concept_ids=None,
            summary="First.",
        )
        db_session.add(a1)
        await db_session.commit()

        rel = await regenerate_index_md(db_session)
        path = resolve_wiki_path(rel)
        first_content = path.read_text(encoding="utf-8")
        assert "[[first-article]]" in first_content

        # Add a second article and regenerate
        a2 = Article(
            slug="second-article",
            title="Second Article",
            file_path="/wiki/second-article.md",
            concept_ids=None,
            summary="Second.",
        )
        db_session.add(a2)
        await db_session.commit()

        rel = await regenerate_index_md(db_session)
        path = resolve_wiki_path(rel)
        second_content = path.read_text(encoding="utf-8")

        # Both should be present
        assert "[[first-article]]" in second_content
        assert "[[second-article]]" in second_content

        # The header should appear exactly once (not duplicated by append)
        assert second_content.count("# Wiki Index") == 1

    @pytest.mark.anyio
    async def test_article_with_no_summary(self, db_session: AsyncSession) -> None:
        """Articles with no summary should have no em-dash suffix."""
        a1 = Article(
            slug="no-summary",
            title="No Summary",
            file_path="/wiki/no-summary.md",
            concept_ids=None,
            summary=None,
        )
        db_session.add(a1)
        await db_session.commit()

        rel = await regenerate_index_md(db_session)
        path = resolve_wiki_path(rel)
        content = path.read_text(encoding="utf-8")

        assert "- [[no-summary]]\n" in content
        assert "\u2014" not in content.split("[[no-summary]]")[1].split("\n")[0]

    @pytest.mark.anyio
    async def test_article_in_multiple_concepts(self, db_session: AsyncSession) -> None:
        """An article with multiple concepts should appear under each."""
        c1 = Concept(id="c1", name="Alpha")
        c2 = Concept(id="c2", name="Beta")
        db_session.add_all([c1, c2])
        await db_session.commit()

        a1 = Article(
            slug="multi-concept",
            title="Multi Concept",
            file_path="/wiki/multi-concept.md",
            concept_ids=json.dumps(["c1", "c2"]),
            summary="Belongs to two concepts.",
        )
        db_session.add(a1)
        await db_session.commit()

        rel = await regenerate_index_md(db_session)
        path = resolve_wiki_path(rel)
        content = path.read_text(encoding="utf-8")

        # Should appear under both headings
        assert "## Alpha" in content
        assert "## Beta" in content

        # Count occurrences of the article slug
        assert content.count("[[multi-concept]]") == 2

    @pytest.mark.anyio
    async def test_articles_sorted_within_concept(self, db_session: AsyncSession) -> None:
        """Articles within a concept should be sorted alphabetically by slug."""
        c1 = Concept(id="c1", name="Concept")
        db_session.add(c1)
        await db_session.commit()

        a_zebra = Article(
            slug="zebra",
            title="Zebra",
            file_path="/wiki/zebra.md",
            concept_ids=json.dumps(["c1"]),
            summary="Zebra summary.",
        )
        a_alpha = Article(
            slug="alpha",
            title="Alpha",
            file_path="/wiki/alpha.md",
            concept_ids=json.dumps(["c1"]),
            summary="Alpha summary.",
        )
        db_session.add_all([a_zebra, a_alpha])
        await db_session.commit()

        rel = await regenerate_index_md(db_session)
        path = resolve_wiki_path(rel)
        content = path.read_text(encoding="utf-8")

        assert content.index("[[alpha]]") < content.index("[[zebra]]")

    @pytest.mark.anyio
    async def test_malformed_concept_ids_go_to_uncategorized(self, db_session: AsyncSession) -> None:
        """Articles with malformed concept_ids JSON should go to Uncategorized."""
        a1 = Article(
            slug="bad-json",
            title="Bad JSON",
            file_path="/wiki/bad-json.md",
            concept_ids="not-valid-json",
            summary="Malformed concept IDs.",
        )
        db_session.add(a1)
        await db_session.commit()

        rel = await regenerate_index_md(db_session)
        path = resolve_wiki_path(rel)
        content = path.read_text(encoding="utf-8")

        assert "## Uncategorized" in content
        assert "- [[bad-json]]" in content
