"""Tests for MCP analysis tools, resources, and prompts.

Tests Tasks 6, 7, and 8 of the MCP server implementation plan.
Each function is tested directly with mocked services and sessions.
"""

from __future__ import annotations

import contextlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import TEST_USER_ID

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def _mock_session_ctx(session):
    """Build an async context manager that yields the given session."""
    yield session


def _patch_user_and_session(session=None):
    """Return a context manager that patches _get_mcp_user_id and _get_session."""
    mock_session = session or AsyncMock()

    class _Patches:
        def __enter__(self):
            self.p1 = patch(
                "wikimind.mcp.tools_analysis._get_mcp_user_id",
                new=AsyncMock(return_value=TEST_USER_ID),
            )
            self.p2 = patch(
                "wikimind.mcp.tools_analysis._get_session",
                return_value=_mock_session_ctx(mock_session),
            )
            self.p1.start()
            self.p2.start()
            return self

        def __exit__(self, *args):
            self.p1.stop()
            self.p2.stop()

    return _Patches()


def _patch_resources_user_and_session(session=None):
    """Return a context manager that patches user/session for resources module."""
    mock_session = session or AsyncMock()

    class _Patches:
        def __enter__(self):
            self.p1 = patch(
                "wikimind.mcp.resources._get_mcp_user_id",
                new=AsyncMock(return_value=TEST_USER_ID),
            )
            self.p2 = patch(
                "wikimind.mcp.resources._get_session",
                return_value=_mock_session_ctx(mock_session),
            )
            self.p1.start()
            self.p2.start()
            return self

        def __exit__(self, *args):
            self.p1.stop()
            self.p2.stop()

    return _Patches()


# ---------------------------------------------------------------------------
# Task 6: wiki_synthesize
# ---------------------------------------------------------------------------


class TestWikiSynthesize:
    """Test the wiki_synthesize MCP tool."""

    async def test_synthesize_success(self):
        from wikimind.mcp.tools_analysis import wiki_synthesize

        mock_article = MagicMock()
        mock_article.title = "Synthesis: AI Trends"

        mock_compilation = MagicMock()
        mock_compilation.article_body = "AI is evolving rapidly..."
        mock_compilation.themes = ["deep learning", "transformers"]

        mock_ctx = AsyncMock()

        with (
            _patch_user_and_session(),
            patch("wikimind.engine.synthesis_compiler.SynthesisCompiler") as mock_compiler_cls,
        ):
            mock_compiler_cls.return_value.synthesize = AsyncMock(return_value=(mock_article, mock_compilation))

            result = await wiki_synthesize(
                ctx=mock_ctx,
                article_ids=["id-1", "id-2", "id-3"],
                synthesis_type="thematic",
                guidance="Focus on recent trends",
            )

            assert result["title"] == "Synthesis: AI Trends"
            assert result["content"] == "AI is evolving rapidly..."
            assert result["themes"] == ["deep learning", "transformers"]

            # Verify progress was reported
            mock_ctx.report_progress.assert_called()

    async def test_synthesize_rejects_less_than_2_articles(self):
        from wikimind.mcp.tools_analysis import wiki_synthesize

        mock_ctx = AsyncMock()

        with pytest.raises(Exception, match="At least 2"):
            await wiki_synthesize(
                ctx=mock_ctx,
                article_ids=["id-1"],
                synthesis_type="thematic",
                guidance="",
            )

    async def test_synthesize_rejects_more_than_10_articles(self):
        from wikimind.mcp.tools_analysis import wiki_synthesize

        mock_ctx = AsyncMock()
        ids = [f"id-{i}" for i in range(11)]

        with pytest.raises(Exception, match="Maximum 10"):
            await wiki_synthesize(
                ctx=mock_ctx,
                article_ids=ids,
                synthesis_type="thematic",
                guidance="",
            )

    async def test_synthesize_rejects_duplicate_ids(self):
        from wikimind.mcp.tools_analysis import wiki_synthesize

        mock_ctx = AsyncMock()

        with pytest.raises(Exception, match="duplicates"):
            await wiki_synthesize(
                ctx=mock_ctx,
                article_ids=["id-1", "id-1", "id-2"],
                synthesis_type="thematic",
                guidance="",
            )

    async def test_synthesize_rejects_invalid_type(self):
        from wikimind.mcp.tools_analysis import wiki_synthesize

        mock_ctx = AsyncMock()

        with pytest.raises(Exception, match="Invalid synthesis_type"):
            await wiki_synthesize(
                ctx=mock_ctx,
                article_ids=["id-1", "id-2"],
                synthesis_type="invalid_type",
                guidance="",
            )

    async def test_synthesize_reports_progress(self):
        from wikimind.mcp.tools_analysis import wiki_synthesize

        mock_article = MagicMock()
        mock_article.title = "Synthesis Result"

        mock_compilation = MagicMock()
        mock_compilation.article_body = "Content"
        mock_compilation.themes = []

        mock_ctx = AsyncMock()

        with (
            _patch_user_and_session(),
            patch("wikimind.engine.synthesis_compiler.SynthesisCompiler") as mock_compiler_cls,
        ):
            mock_compiler_cls.return_value.synthesize = AsyncMock(return_value=(mock_article, mock_compilation))

            await wiki_synthesize(
                ctx=mock_ctx,
                article_ids=["id-1", "id-2"],
                synthesis_type="comparative",
                guidance="",
            )

            # Progress: 1/(2+1) and 3/3
            assert mock_ctx.report_progress.call_count == 2
            calls = mock_ctx.report_progress.call_args_list
            assert calls[0].args == (1, 3)
            assert calls[1].args == (3, 3)


# ---------------------------------------------------------------------------
# Task 6: wiki_get_health
# ---------------------------------------------------------------------------


class TestWikiGetHealth:
    """Test the wiki_get_health MCP tool."""

    async def test_returns_correct_fields(self):
        from wikimind.mcp.tools_analysis import wiki_get_health

        mock_stats = MagicMock()
        mock_stats.article_count = 42
        mock_stats.source_count = 15
        mock_stats.orphan_count = 3
        mock_stats.stuck_sources = 1
        mock_stats.compilation_success_rate = 0.95

        mock_ctx = AsyncMock()
        mock_session = AsyncMock()

        # Mock the contradiction count query
        mock_result = MagicMock()
        mock_result.scalar.return_value = 7
        mock_session.execute = AsyncMock(return_value=mock_result)

        with (
            _patch_user_and_session(mock_session),
            patch("wikimind.services.admin.AdminService") as mock_admin_cls,
        ):
            mock_admin_cls.return_value.get_stats = AsyncMock(return_value=mock_stats)

            result = await wiki_get_health(ctx=mock_ctx)

            assert result["article_count"] == 42
            assert result["source_count"] == 15
            assert result["orphan_count"] == 3
            assert result["contradiction_count"] == 7
            assert result["stuck_source_count"] == 1
            assert result["compilation_success_rate"] == 0.95


# ---------------------------------------------------------------------------
# Task 6: wiki_list_sources (rewritten)
# ---------------------------------------------------------------------------


class TestWikiListSourcesAnalysis:
    """Test the rewritten wiki_list_sources MCP tool."""

    async def test_returns_structured_list(self):
        from wikimind.mcp.tools_analysis import wiki_list_sources

        mock_source = MagicMock()
        mock_source.id = "src-1"
        mock_source.title = "Example Source"
        mock_source.source_type = "url"
        mock_source.status = "compiled"
        mock_source.ingested_at = "2026-01-01T00:00:00"

        with _patch_user_and_session(), patch("wikimind.services.ingest.IngestService") as mock_ingest_cls:
            mock_ingest_cls.return_value.list_sources = AsyncMock(return_value=[mock_source])

            result = await wiki_list_sources(status=None, limit=20)

            assert isinstance(result, list)
            assert len(result) == 1
            assert result[0]["id"] == "src-1"
            assert result[0]["title"] == "Example Source"
            assert result[0]["source_type"] == "url"
            assert result[0]["status"] == "compiled"

    async def test_rejects_invalid_status(self):
        from wikimind.mcp.tools_analysis import wiki_list_sources

        with pytest.raises(Exception, match="Invalid status"):
            await wiki_list_sources(status="bogus", limit=20)

    async def test_clamps_limit(self):
        from wikimind.mcp.tools_analysis import wiki_list_sources

        with _patch_user_and_session(), patch("wikimind.services.ingest.IngestService") as mock_ingest_cls:
            mock_ingest_cls.return_value.list_sources = AsyncMock(return_value=[])

            await wiki_list_sources(status=None, limit=999)

            call_kwargs = mock_ingest_cls.return_value.list_sources.call_args
            assert call_kwargs.kwargs["limit"] == 100


# ---------------------------------------------------------------------------
# Task 6: wiki_get_graph
# ---------------------------------------------------------------------------


class TestWikiGetGraph:
    """Test the wiki_get_graph MCP tool."""

    async def test_returns_nodes_and_edges(self):
        from wikimind.mcp.tools_analysis import wiki_get_graph

        mock_node = MagicMock()
        mock_node.id = "art-1"
        mock_node.label = "Test Article"
        mock_node.concept_cluster = "machine-learning"
        mock_node.confidence = "sourced"

        mock_edge = MagicMock()
        mock_edge.source = "art-1"
        mock_edge.target = "art-2"
        mock_edge.relation_type = MagicMock(value="references")

        mock_graph = MagicMock()
        mock_graph.nodes = [mock_node]
        mock_graph.edges = [mock_edge]

        with _patch_user_and_session(), patch("wikimind.services.wiki.WikiService") as mock_wiki_cls:
            mock_wiki_cls.return_value.get_graph = AsyncMock(return_value=mock_graph)

            result = await wiki_get_graph(article_slug=None)

            assert len(result["nodes"]) == 1
            assert result["nodes"][0]["id"] == "art-1"
            assert result["nodes"][0]["title"] == "Test Article"
            assert result["nodes"][0]["type"] == "machine-learning"
            assert result["nodes"][0]["confidence"] == "sourced"

            assert len(result["edges"]) == 1
            assert result["edges"][0]["source"] == "art-1"
            assert result["edges"][0]["target"] == "art-2"
            assert result["edges"][0]["relation"] == "references"

    async def test_filters_by_article_slug(self):
        from wikimind.mcp.tools_analysis import wiki_get_graph

        mock_graph = MagicMock()
        mock_graph.nodes = []
        mock_graph.edges = []

        with _patch_user_and_session(), patch("wikimind.services.wiki.WikiService") as mock_wiki_cls:
            mock_wiki_cls.return_value.get_graph = AsyncMock(return_value=mock_graph)

            await wiki_get_graph(article_slug="test-article")

            call_kwargs = mock_wiki_cls.return_value.get_graph.call_args
            assert call_kwargs.kwargs["from_article"] == "test-article"


# ---------------------------------------------------------------------------
# Task 7: Resources
# ---------------------------------------------------------------------------


class TestResourceIndex:
    """Test the wikimind://index resource."""

    async def test_returns_article_list(self):
        from wikimind.mcp.resources import resource_index

        mock_article = MagicMock()
        mock_article.slug = "test-article"
        mock_article.title = "Test Article"
        mock_article.page_type = "source"
        mock_article.concepts = ["machine-learning"]

        with _patch_resources_user_and_session(), patch("wikimind.services.wiki.WikiService") as mock_wiki_cls:
            mock_wiki_cls.return_value.list_articles = AsyncMock(return_value=[mock_article])

            result = await resource_index()
            parsed = json.loads(result)

            assert "articles" in parsed
            assert len(parsed["articles"]) == 1
            assert parsed["articles"][0]["slug"] == "test-article"
            assert parsed["articles"][0]["title"] == "Test Article"
            assert parsed["articles"][0]["page_type"] == "source"
            assert parsed["articles"][0]["concepts"] == ["machine-learning"]

    async def test_capped_at_500(self):
        from wikimind.mcp.resources import resource_index

        with _patch_resources_user_and_session(), patch("wikimind.services.wiki.WikiService") as mock_wiki_cls:
            mock_wiki_cls.return_value.list_articles = AsyncMock(return_value=[])

            await resource_index()

            call_kwargs = mock_wiki_cls.return_value.list_articles.call_args
            assert call_kwargs.kwargs["limit"] == 500


class TestResourceArticle:
    """Test the wikimind://articles/{slug} resource."""

    async def test_returns_markdown_content(self):
        from wikimind.mcp.resources import resource_article

        mock_article = MagicMock()
        mock_article.content = "# Hello World\n\nThis is article content."

        with _patch_resources_user_and_session(), patch("wikimind.services.wiki.WikiService") as mock_wiki_cls:
            mock_wiki_cls.return_value.get_article = AsyncMock(return_value=mock_article)

            result = await resource_article(slug="hello-world")

            assert result == "# Hello World\n\nThis is article content."

    async def test_returns_empty_string_when_no_content(self):
        from wikimind.mcp.resources import resource_article

        mock_article = MagicMock()
        mock_article.content = None

        with _patch_resources_user_and_session(), patch("wikimind.services.wiki.WikiService") as mock_wiki_cls:
            mock_wiki_cls.return_value.get_article = AsyncMock(return_value=mock_article)

            result = await resource_article(slug="empty")
            assert result == ""

    async def test_not_found_raises(self):
        from wikimind.errors import NotFoundError
        from wikimind.mcp.resources import resource_article

        with _patch_resources_user_and_session(), patch("wikimind.services.wiki.WikiService") as mock_wiki_cls:
            mock_wiki_cls.return_value.get_article = AsyncMock(side_effect=NotFoundError("Article not found"))

            with pytest.raises(NotFoundError):
                await resource_article(slug="nonexistent")


class TestResourceSource:
    """Test the wikimind://sources/{source_id} resource."""

    async def test_returns_metadata_json(self):
        from wikimind.mcp.resources import resource_source

        mock_source = MagicMock()
        mock_source.id = "src-123"
        mock_source.title = "Test Source"
        mock_source.source_type = "url"
        mock_source.status = "compiled"
        mock_source.source_url = "https://example.com"
        mock_source.ingested_at = "2026-01-01T00:00:00"

        with (
            _patch_resources_user_and_session(),
            patch("wikimind.services.ingest.IngestService") as mock_ingest_cls,
        ):
            mock_ingest_cls.return_value.get_source = AsyncMock(return_value=mock_source)

            result = await resource_source(source_id="src-123")
            parsed = json.loads(result)

            assert parsed["id"] == "src-123"
            assert parsed["title"] == "Test Source"
            assert parsed["source_type"] == "url"
            assert parsed["status"] == "compiled"
            assert parsed["url"] == "https://example.com"


# ---------------------------------------------------------------------------
# Task 8: Prompts
# ---------------------------------------------------------------------------


class TestPromptOnboarding:
    """Test the wiki_onboarding prompt."""

    async def test_returns_onboarding_instructions(self):
        from wikimind.mcp.prompts import prompt_onboarding

        result = await prompt_onboarding()

        assert "wiki_overview()" in result
        assert "knowledge base" in result
        assert "topic areas" in result
        assert "underdeveloped" in result

    async def test_has_numbered_steps(self):
        from wikimind.mcp.prompts import prompt_onboarding

        result = await prompt_onboarding()

        # Should have 6 numbered steps
        for i in range(1, 7):
            assert f"{i}." in result


class TestPromptResearchTopic:
    """Test the research_topic prompt."""

    async def test_includes_topic(self):
        from wikimind.mcp.prompts import prompt_research_topic

        result = await prompt_research_topic(topic="quantum computing")

        assert "quantum computing" in result
        assert 'wiki_search("quantum computing")' in result

    async def test_instructs_search_then_read(self):
        from wikimind.mcp.prompts import prompt_research_topic

        result = await prompt_research_topic(topic="AI safety")

        assert "wiki_search" in result
        assert "wiki_get_article" in result
        assert "Synthesize" in result


class TestPromptCompareArticles:
    """Test the compare_articles prompt."""

    async def test_includes_both_slugs(self):
        from wikimind.mcp.prompts import prompt_compare_articles

        result = await prompt_compare_articles(slug_a="article-one", slug_b="article-two")

        assert "article-one" in result
        assert "article-two" in result
        assert "wiki_get_article" in result

    async def test_mentions_agreements_and_disagreements(self):
        from wikimind.mcp.prompts import prompt_compare_articles

        result = await prompt_compare_articles(slug_a="a", slug_b="b")

        assert "agreements" in result
        assert "disagreements" in result or "contradictions" in result
        assert "synthesis" in result


class TestPromptKnowledgeGaps:
    """Test the knowledge_gaps prompt."""

    async def test_with_topic(self):
        from wikimind.mcp.prompts import prompt_knowledge_gaps

        result = await prompt_knowledge_gaps(topic="machine learning")

        assert "machine learning" in result
        assert "wiki_search" in result
        assert "wiki_get_health()" in result
        assert "gaps" in result.lower()

    async def test_without_topic(self):
        from wikimind.mcp.prompts import prompt_knowledge_gaps

        result = await prompt_knowledge_gaps(topic="")

        assert "wiki_overview()" in result
        assert "wiki_get_health()" in result
        assert "orphaned" in result
        assert "contradictions" in result

    async def test_default_topic_is_empty(self):
        from wikimind.mcp.prompts import prompt_knowledge_gaps

        result = await prompt_knowledge_gaps()

        # Should use the "without topic" variant
        assert "wiki_overview()" in result
        assert "overall health" in result.lower()
