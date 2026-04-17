"""Tests for Phase 5 — answer pages, index/meta generation, API page_type fields."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from wikimind.engine.qa_agent import QAAgent
from wikimind.models import (
    Article,
    ArticleResponse,
    ArticleSummaryResponse,
    Backlink,
    BacklinkEntry,
    Conversation,
    PageType,
    Query,
    RelationType,
)
from wikimind.services.wiki_index import (
    _article_entry,
    _page_type_label,
    generate_meta_health_page,
    regenerate_index_md,
)
from wikimind.storage import resolve_wiki_path

# ---------------------------------------------------------------------------
# _page_type_label
# ---------------------------------------------------------------------------


class TestPageTypeLabel:
    def test_all_types_have_labels(self) -> None:
        for pt in PageType:
            label = _page_type_label(pt)
            assert isinstance(label, str)
            assert len(label) > 0


# ---------------------------------------------------------------------------
# _article_entry
# ---------------------------------------------------------------------------


class TestArticleEntry:
    def test_source_article_no_badge(self) -> None:
        a = Article(slug="my-article", title="My Article", file_path="/x.md", page_type=PageType.SOURCE)
        entry = _article_entry(a)
        assert "- [[my-article]]" in entry
        assert "`[" not in entry  # no type badge for source

    def test_concept_article_has_badge(self) -> None:
        a = Article(slug="concept-page", title="Concept", file_path="/x.md", page_type=PageType.CONCEPT)
        entry = _article_entry(a)
        assert "`[Concept]`" in entry

    def test_answer_article_has_badge(self) -> None:
        a = Article(slug="answer-page", title="Answer", file_path="/x.md", page_type=PageType.ANSWER)
        entry = _article_entry(a)
        assert "`[Answer]`" in entry


# ---------------------------------------------------------------------------
# regenerate_index_md — page_type frontmatter
# ---------------------------------------------------------------------------


class TestRegenerateIndexMdPageType:
    @pytest.mark.anyio
    async def test_frontmatter_includes_page_type(self, db_session: AsyncSession) -> None:
        """The index should have page_type: index in its frontmatter."""
        rel = await regenerate_index_md(db_session)
        path = resolve_wiki_path(rel)
        content = path.read_text(encoding="utf-8")
        assert "page_type: index" in content
        assert "scope: global" in content

    @pytest.mark.anyio
    async def test_article_counts_by_type(self, db_session: AsyncSession) -> None:
        """The index should show article counts grouped by type."""
        a1 = Article(slug="src-1", title="Source 1", file_path="/x.md", page_type=PageType.SOURCE)
        a2 = Article(slug="ans-1", title="Answer 1", file_path="/x.md", page_type=PageType.ANSWER)
        db_session.add_all([a1, a2])
        await db_session.commit()

        rel = await regenerate_index_md(db_session)
        path = resolve_wiki_path(rel)
        content = path.read_text(encoding="utf-8")
        assert "2 articles" in content
        assert "1 source" in content
        assert "1 answer" in content

    @pytest.mark.anyio
    async def test_concept_pages_section(self, db_session: AsyncSession) -> None:
        """Concept-type articles should appear in a 'Concept Pages' section."""
        a = Article(slug="llm-reasoning", title="LLM Reasoning", file_path="/x.md", page_type=PageType.CONCEPT)
        db_session.add(a)
        await db_session.commit()

        rel = await regenerate_index_md(db_session)
        path = resolve_wiki_path(rel)
        content = path.read_text(encoding="utf-8")
        assert "## Concept Pages" in content
        assert "[[llm-reasoning]]" in content

    @pytest.mark.anyio
    async def test_answer_articles_get_badge(self, db_session: AsyncSession) -> None:
        """Answer articles should get a [Answer] badge in the index."""
        a = Article(slug="qa-answer", title="QA Answer", file_path="/x.md", page_type=PageType.ANSWER)
        db_session.add(a)
        await db_session.commit()

        rel = await regenerate_index_md(db_session)
        path = resolve_wiki_path(rel)
        content = path.read_text(encoding="utf-8")
        assert "`[Answer]`" in content


# ---------------------------------------------------------------------------
# generate_meta_health_page
# ---------------------------------------------------------------------------


class TestGenerateMetaHealthPage:
    @pytest.mark.anyio
    async def test_empty_database_produces_health_page(self, db_session: AsyncSession) -> None:
        """An empty DB should produce a valid health page."""
        rel = await generate_meta_health_page(db_session)
        path = resolve_wiki_path(rel)
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "page_type: meta" in content
        assert "# Wiki Health" in content
        assert "**Total** | **0**" in content
        assert "**0** articles with no inbound or outbound links" in content

    @pytest.mark.anyio
    async def test_health_page_counts_articles_by_type(self, db_session: AsyncSession) -> None:
        """Health page should count articles by page_type."""
        a1 = Article(slug="src-1", title="Source 1", file_path="/x.md", page_type=PageType.SOURCE)
        a2 = Article(slug="ans-1", title="Answer 1", file_path="/x.md", page_type=PageType.ANSWER)
        a3 = Article(slug="src-2", title="Source 2", file_path="/x.md", page_type=PageType.SOURCE)
        db_session.add_all([a1, a2, a3])
        await db_session.commit()

        rel = await generate_meta_health_page(db_session)
        path = resolve_wiki_path(rel)
        content = path.read_text(encoding="utf-8")
        assert "| Source | 2 |" in content
        assert "| Answer | 1 |" in content
        assert "**Total** | **3**" in content

    @pytest.mark.anyio
    async def test_health_page_counts_orphans(self, db_session: AsyncSession) -> None:
        """Health page should count articles with no links as orphans."""
        a1 = Article(slug="linked", title="Linked", file_path="/x.md")
        a2 = Article(slug="orphan", title="Orphan", file_path="/x.md")
        db_session.add_all([a1, a2])
        await db_session.flush()

        bl = Backlink(source_article_id=a1.id, target_article_id=a1.id)
        db_session.add(bl)
        await db_session.commit()

        rel = await generate_meta_health_page(db_session)
        path = resolve_wiki_path(rel)
        content = path.read_text(encoding="utf-8")
        assert "**1** articles with no inbound or outbound links" in content

    @pytest.mark.anyio
    async def test_health_page_counts_link_types(self, db_session: AsyncSession) -> None:
        """Health page should count links by relation_type."""
        a1 = Article(slug="a1", title="A1", file_path="/x.md")
        a2 = Article(slug="a2", title="A2", file_path="/x.md")
        db_session.add_all([a1, a2])
        await db_session.flush()

        bl1 = Backlink(source_article_id=a1.id, target_article_id=a2.id, relation_type=RelationType.REFERENCES)
        bl2 = Backlink(source_article_id=a2.id, target_article_id=a1.id, relation_type=RelationType.CONTRADICTS)
        db_session.add_all([bl1, bl2])
        await db_session.commit()

        rel = await generate_meta_health_page(db_session)
        path = resolve_wiki_path(rel)
        content = path.read_text(encoding="utf-8")
        assert "| contradicts | 1 |" in content
        assert "| references | 1 |" in content
        assert "**Total** | **2**" in content


# ---------------------------------------------------------------------------
# Answer page filing sets correct page_type
# ---------------------------------------------------------------------------


class TestAnswerPageType:
    @pytest.mark.anyio
    async def test_file_back_sets_answer_page_type(self, db_session: AsyncSession) -> None:
        """When filing back a conversation, the Article should have page_type=ANSWER."""
        conv = Conversation(title="Test conversation")
        db_session.add(conv)
        await db_session.flush()

        q = Query(
            question="What is X?",
            answer="X is Y.",
            confidence="high",
            conversation_id=conv.id,
            turn_index=0,
        )
        db_session.add(q)
        await db_session.commit()

        agent = QAAgent()
        article, was_update = await agent._file_back_thread(conv.id, db_session)
        assert article.page_type == PageType.ANSWER
        assert not was_update


# ---------------------------------------------------------------------------
# API response includes page_type and relation_type
# ---------------------------------------------------------------------------


class TestApiResponseFields:
    def test_article_response_has_page_type(self) -> None:
        """ArticleResponse should include page_type field."""
        resp = ArticleResponse(
            id="1",
            slug="test",
            title="Test",
            summary=None,
            confidence=None,
            linter_score=None,
            page_type=PageType.CONCEPT,
            content="# Test",
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
        )
        data = resp.model_dump()
        assert data["page_type"] == "concept"

    def test_backlink_entry_has_relation_type(self) -> None:
        """BacklinkEntry should include relation_type field."""
        entry = BacklinkEntry(
            id="1",
            title="Test",
            slug="test",
            relation_type=RelationType.CONTRADICTS,
            resolution="source_a_wins",
        )
        data = entry.model_dump()
        assert data["relation_type"] == "contradicts"
        assert data["resolution"] == "source_a_wins"

    def test_article_summary_response_has_page_type(self) -> None:
        """ArticleSummaryResponse should include page_type field."""
        resp = ArticleSummaryResponse(
            id="1",
            slug="test",
            title="Test",
            summary=None,
            confidence=None,
            linter_score=None,
            page_type=PageType.ANSWER,
            created_at="2026-01-01T00:00:00",
            updated_at="2026-01-01T00:00:00",
        )
        data = resp.model_dump()
        assert data["page_type"] == "answer"
