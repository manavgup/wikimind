"""Tests for WikiMind MCP server tools.

Tests each MCP tool function directly with an in-memory SQLite database,
bypassing the MCP transport layer to verify tool logic in isolation.
"""

from __future__ import annotations

import contextlib
import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from tests.conftest import TEST_USER_ID
from wikimind.cli.main import cli
from wikimind.mcp.server import (
    compare_articles,
    fact_check,
    knowledge_gaps,
    wiki_get_article,
    wiki_get_graph,
    wiki_get_health,
    wiki_list_contradictions,
    wiki_list_sources,
    wiki_search,
    wiki_synthesize,
)
from wikimind.mcp.server import (
    mcp as mcp_server,
)
from wikimind.models import Article, ConfidenceLevel, PageType, Source

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def _mock_session_ctx(session):
    """Build an async context manager that yields the given session."""
    yield session


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def sample_article(db_session: AsyncSession) -> Article:
    """Create a sample wiki article for testing."""
    article = Article(
        slug="test-article",
        title="Test Article",
        summary="A test article about testing.",
        file_path="articles/test-article.md",
        page_type=PageType.SOURCE,
        user_id=TEST_USER_ID,
        confidence=ConfidenceLevel.SOURCED,
        confidence_score=0.9,
    )
    db_session.add(article)
    await db_session.commit()
    await db_session.refresh(article)
    return article


@pytest.fixture
async def sample_source(db_session: AsyncSession) -> Source:
    """Create a sample ingested source for testing."""
    source = Source(
        source_type="url",
        title="Test Source",
        source_url="https://example.com/test",
        user_id=TEST_USER_ID,
    )
    db_session.add(source)
    await db_session.commit()
    await db_session.refresh(source)
    return source


# ---------------------------------------------------------------------------
# wiki_search
# ---------------------------------------------------------------------------


class TestWikiSearch:
    """Test the wiki_search MCP tool."""

    async def test_search_returns_results(self, db_session, sample_article):
        mock_result = AsyncMock(
            id=sample_article.id,
            slug=sample_article.slug,
            title=sample_article.title,
            summary=sample_article.summary,
            confidence=sample_article.confidence,
            source_count=0,
        )

        with (
            patch("wikimind.mcp.server._get_session", return_value=_mock_session_ctx(db_session)),
            patch("wikimind.mcp.server.WikiService") as mock_wiki_cls,
        ):
            mock_wiki_cls.return_value.search = AsyncMock(return_value=[mock_result])

            result = await wiki_search(query="test", limit=10)
            parsed = json.loads(result)

            assert isinstance(parsed, list)
            assert len(parsed) == 1
            assert parsed[0]["title"] == "Test Article"
            assert parsed[0]["slug"] == "test-article"

    async def test_search_short_query_returns_error(self):
        result = await wiki_search(query="a", limit=10)
        parsed = json.loads(result)
        assert "error" in parsed
        assert "2 characters" in parsed["error"]

    async def test_search_clamps_limit(self, db_session):
        with (
            patch("wikimind.mcp.server._get_session", return_value=_mock_session_ctx(db_session)),
            patch("wikimind.mcp.server.WikiService") as mock_wiki_cls,
        ):
            mock_wiki_cls.return_value.search = AsyncMock(return_value=[])

            result = await wiki_search(query="test", limit=999)
            parsed = json.loads(result)
            assert isinstance(parsed, list)

            # Verify the search was called with clamped limit of 50
            mock_wiki_cls.return_value.search.assert_called_once()
            call_kwargs = mock_wiki_cls.return_value.search.call_args
            assert call_kwargs.kwargs["limit"] == 50


# ---------------------------------------------------------------------------
# wiki_get_article
# ---------------------------------------------------------------------------


class TestWikiGetArticle:
    """Test the wiki_get_article MCP tool."""

    async def test_get_article_by_slug(self, db_session, sample_article):
        mock_response = AsyncMock()
        mock_response.id = sample_article.id
        mock_response.slug = sample_article.slug
        mock_response.title = sample_article.title
        mock_response.summary = sample_article.summary
        mock_response.content = "# Test Article\n\nSome content."
        mock_response.confidence = "sourced"
        mock_response.page_type = "source"
        mock_response.sources = []
        mock_response.created_at = "2026-01-01"
        mock_response.updated_at = "2026-01-02"

        with (
            patch("wikimind.mcp.server._get_session", return_value=_mock_session_ctx(db_session)),
            patch("wikimind.mcp.server.WikiService") as mock_wiki_cls,
        ):
            mock_wiki_cls.return_value.get_article = AsyncMock(return_value=mock_response)

            result = await wiki_get_article(id_or_slug="test-article")
            parsed = json.loads(result)

            assert parsed["title"] == "Test Article"
            assert parsed["content"] == "# Test Article\n\nSome content."
            assert parsed["sources"] == []

    async def test_get_article_not_found(self, db_session):
        with (
            patch("wikimind.mcp.server._get_session", return_value=_mock_session_ctx(db_session)),
            patch("wikimind.mcp.server.WikiService") as mock_wiki_cls,
        ):
            mock_wiki_cls.return_value.get_article = AsyncMock(
                side_effect=Exception("Article not found"),
            )

            result = await wiki_get_article(id_or_slug="nonexistent")
            parsed = json.loads(result)
            assert "error" in parsed
            assert "not found" in parsed["error"]


# ---------------------------------------------------------------------------
# wiki_list_sources
# ---------------------------------------------------------------------------


class TestWikiListSources:
    """Test the wiki_list_sources MCP tool."""

    async def test_list_sources_returns_results(self, db_session, sample_source):
        mock_source = AsyncMock()
        mock_source.id = sample_source.id
        mock_source.source_type = "url"
        mock_source.title = "Test Source"
        mock_source.source_url = "https://example.com/test"
        mock_source.ingested_at = "2026-01-01"
        mock_source.compiled_at = None

        with (
            patch("wikimind.mcp.server._get_session", return_value=_mock_session_ctx(db_session)),
            patch("wikimind.mcp.server.IngestService") as mock_ingest_cls,
        ):
            mock_ingest_cls.return_value.list_sources = AsyncMock(return_value=[mock_source])

            result = await wiki_list_sources(limit=20)
            parsed = json.loads(result)

            assert isinstance(parsed, list)
            assert len(parsed) == 1
            assert parsed[0]["title"] == "Test Source"
            assert parsed[0]["source_type"] == "url"

    async def test_list_sources_empty(self, db_session):
        with (
            patch("wikimind.mcp.server._get_session", return_value=_mock_session_ctx(db_session)),
            patch("wikimind.mcp.server.IngestService") as mock_ingest_cls,
        ):
            mock_ingest_cls.return_value.list_sources = AsyncMock(return_value=[])

            result = await wiki_list_sources(limit=20)
            parsed = json.loads(result)
            assert parsed == []

    async def test_list_sources_clamps_limit(self, db_session):
        with (
            patch("wikimind.mcp.server._get_session", return_value=_mock_session_ctx(db_session)),
            patch("wikimind.mcp.server.IngestService") as mock_ingest_cls,
        ):
            mock_ingest_cls.return_value.list_sources = AsyncMock(return_value=[])

            await wiki_list_sources(limit=999)
            call_kwargs = mock_ingest_cls.return_value.list_sources.call_args
            assert call_kwargs.kwargs["limit"] == 100


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------


class TestMCPCli:
    """Test MCP CLI commands."""

    def test_mcp_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["mcp", "--help"])
        assert result.exit_code == 0
        assert "serve" in result.output
        assert "config" in result.output

    def test_mcp_config(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["mcp", "config"])
        assert result.exit_code == 0
        assert "mcpServers" in result.output
        assert "wikimind" in result.output

    def test_mcp_serve_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["mcp", "serve", "--help"])
        assert result.exit_code == 0
        assert "transport" in result.output
        assert "stdio" in result.output
        assert "http" in result.output


# ---------------------------------------------------------------------------
# Server registration
# ---------------------------------------------------------------------------


class TestMCPServerRegistration:
    """Test that MCP tools are properly registered on the server."""

    def test_server_has_expected_name(self):
        assert mcp_server.name == "wikimind"

    def test_server_has_instructions(self):
        assert mcp_server.instructions is not None
        assert "WikiMind" in mcp_server.instructions

    async def test_server_lists_tools(self):
        tools = await mcp_server.list_tools()
        tool_names = {t.name for t in tools}
        assert "wiki_search" in tool_names
        assert "wiki_get_article" in tool_names
        assert "wiki_ask" in tool_names
        assert "wiki_list_sources" in tool_names
        assert "wiki_synthesize" in tool_names
        assert "wiki_list_contradictions" in tool_names
        assert "wiki_get_health" in tool_names
        assert "wiki_get_graph" in tool_names

    async def test_tool_descriptions_present(self):
        tools = await mcp_server.list_tools()
        for tool in tools:
            assert tool.description, f"Tool {tool.name} missing description"
            assert len(tool.description) > 20, f"Tool {tool.name} description too short"

    async def test_tool_schemas_have_parameters(self):
        tools = await mcp_server.list_tools()
        tools_by_name = {t.name: t for t in tools}

        # wiki_search should have query and limit params
        search_schema = tools_by_name["wiki_search"].parameters
        assert "query" in search_schema.get("properties", {})

        # wiki_get_article should have id_or_slug param
        article_schema = tools_by_name["wiki_get_article"].parameters
        assert "id_or_slug" in article_schema.get("properties", {})

        # wiki_ask should have question param
        ask_schema = tools_by_name["wiki_ask"].parameters
        assert "question" in ask_schema.get("properties", {})

    async def test_tool_parameter_descriptions_present(self):
        """Verify that Field-based parameter descriptions are exposed in schemas."""
        tools = await mcp_server.list_tools()
        tools_by_name = {t.name: t for t in tools}

        # wiki_search query param should have a description from Field()
        search_props = tools_by_name["wiki_search"].parameters.get("properties", {})
        assert "description" in search_props.get("query", {}), "query param missing Field description"

        # wiki_get_article id_or_slug param should have a description
        article_props = tools_by_name["wiki_get_article"].parameters.get("properties", {})
        assert "description" in article_props.get("id_or_slug", {}), "id_or_slug param missing Field description"

    async def test_server_lists_prompts(self):
        prompts = await mcp_server.list_prompts()
        prompt_names = {p.name for p in prompts}
        assert "compare_articles" in prompt_names
        assert "knowledge_gaps" in prompt_names
        assert "fact_check" in prompt_names

    async def test_prompt_descriptions_present(self):
        prompts = await mcp_server.list_prompts()
        for prompt in prompts:
            assert prompt.description, f"Prompt {prompt.name} missing description"
            assert len(prompt.description) > 20, f"Prompt {prompt.name} description too short"


# ---------------------------------------------------------------------------
# wiki_synthesize
# ---------------------------------------------------------------------------


class TestWikiSynthesize:
    """Test the wiki_synthesize MCP tool."""

    async def test_synthesize_too_few_articles(self):
        result = await wiki_synthesize(article_ids=["one"])
        parsed = json.loads(result)
        assert "error" in parsed
        assert "At least 2" in parsed["error"]

    async def test_synthesize_invalid_type(self):
        result = await wiki_synthesize(article_ids=["a", "b"], synthesis_type="invalid")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "Invalid synthesis_type" in parsed["error"]

    async def test_synthesize_success(self, db_session):
        mock_article = AsyncMock()
        mock_article.id = "synth-article-id"
        mock_article.slug = "synth-slug"

        mock_compilation = AsyncMock()
        mock_compilation.title = "Synthesis Title"
        mock_compilation.summary = "A synthesis summary"
        mock_compilation.themes = ["theme1", "theme2"]
        mock_compilation.gaps = ["gap1"]
        mock_compilation.open_questions = ["q1"]
        mock_compilation.source_article_ids = ["a", "b"]
        mock_compilation.article_body = "# Synthesis body"

        with (
            patch("wikimind.mcp.server._get_session", return_value=_mock_session_ctx(db_session)),
            patch("wikimind.mcp.server._get_mcp_user_id", return_value=TEST_USER_ID),
            patch("wikimind.mcp.server.SynthesisCompiler") as mock_compiler_cls,
        ):
            mock_compiler_cls.return_value.synthesize = AsyncMock(return_value=(mock_article, mock_compilation))

            result = await wiki_synthesize(
                article_ids=["a", "b"],
                synthesis_type="comparative",
                guidance="Focus on differences",
            )
            parsed = json.loads(result)

            assert parsed["title"] == "Synthesis Title"
            assert parsed["summary"] == "A synthesis summary"
            assert parsed["themes"] == ["theme1", "theme2"]
            assert parsed["gaps"] == ["gap1"]
            assert parsed["article_id"] == "synth-article-id"

    async def test_synthesize_returns_none(self, db_session):
        with (
            patch("wikimind.mcp.server._get_session", return_value=_mock_session_ctx(db_session)),
            patch("wikimind.mcp.server._get_mcp_user_id", return_value=TEST_USER_ID),
            patch("wikimind.mcp.server.SynthesisCompiler") as mock_compiler_cls,
        ):
            mock_compiler_cls.return_value.synthesize = AsyncMock(return_value=None)

            result = await wiki_synthesize(article_ids=["a", "b"], synthesis_type=None, guidance=None)
            parsed = json.loads(result)
            assert "error" in parsed
            assert "could not be performed" in parsed["error"]


# ---------------------------------------------------------------------------
# wiki_list_contradictions
# ---------------------------------------------------------------------------


class TestWikiListContradictions:
    """Test the wiki_list_contradictions MCP tool."""

    async def test_list_contradictions_returns_results(self, db_session):
        mock_contradiction = AsyncMock()
        mock_contradiction.id = "c-1"
        mock_contradiction.claim_a = "Claim A"
        mock_contradiction.claim_b = "Claim B"
        mock_contradiction.article_a_id = "art-a"
        mock_contradiction.article_b_id = "art-b"
        mock_contradiction.article_a_title = "Article A"
        mock_contradiction.article_b_title = "Article B"
        mock_contradiction.status = "active"
        mock_contradiction.detected_at = "2026-01-01"
        mock_contradiction.resolution = None

        with (
            patch("wikimind.mcp.server._get_session", return_value=_mock_session_ctx(db_session)),
            patch("wikimind.mcp.server._get_mcp_user_id", return_value=TEST_USER_ID),
            patch("wikimind.mcp.server.ContradictionService") as mock_cls,
        ):
            mock_cls.return_value.list_contradictions = AsyncMock(return_value=[mock_contradiction])

            result = await wiki_list_contradictions(status=None, limit=50)
            parsed = json.loads(result)

            assert isinstance(parsed, list)
            assert len(parsed) == 1
            assert parsed[0]["claim_a"] == "Claim A"
            assert parsed[0]["article_a_title"] == "Article A"

    async def test_list_contradictions_invalid_status(self):
        result = await wiki_list_contradictions(status="invalid", limit=50)
        parsed = json.loads(result)
        assert "error" in parsed
        assert "Invalid status" in parsed["error"]

    async def test_list_contradictions_empty(self, db_session):
        with (
            patch("wikimind.mcp.server._get_session", return_value=_mock_session_ctx(db_session)),
            patch("wikimind.mcp.server._get_mcp_user_id", return_value=TEST_USER_ID),
            patch("wikimind.mcp.server.ContradictionService") as mock_cls,
        ):
            mock_cls.return_value.list_contradictions = AsyncMock(return_value=[])

            result = await wiki_list_contradictions(status=None, limit=50)
            parsed = json.loads(result)
            assert parsed == []

    async def test_list_contradictions_clamps_limit(self, db_session):
        with (
            patch("wikimind.mcp.server._get_session", return_value=_mock_session_ctx(db_session)),
            patch("wikimind.mcp.server._get_mcp_user_id", return_value=TEST_USER_ID),
            patch("wikimind.mcp.server.ContradictionService") as mock_cls,
        ):
            mock_cls.return_value.list_contradictions = AsyncMock(return_value=[])

            await wiki_list_contradictions(status=None, limit=999)
            call_kwargs = mock_cls.return_value.list_contradictions.call_args
            assert call_kwargs.kwargs["limit"] == 100


# ---------------------------------------------------------------------------
# wiki_get_health
# ---------------------------------------------------------------------------


class TestWikiGetHealth:
    """Test the wiki_get_health MCP tool."""

    async def test_get_health_returns_report(self, db_session):
        mock_report = AsyncMock()
        mock_report.generated_at = "2026-01-01T00:00:00"
        mock_report.total_articles = 42
        mock_report.total_sources = 15
        mock_report.total_findings = 5
        mock_report.contradictions_count = 2
        mock_report.orphans_count = 3
        mock_report.status = "healthy"
        mock_report.message = None

        with (
            patch("wikimind.mcp.server._get_session", return_value=_mock_session_ctx(db_session)),
            patch("wikimind.mcp.server._get_mcp_user_id", return_value=TEST_USER_ID),
            patch("wikimind.mcp.server.WikiService") as mock_wiki_cls,
        ):
            mock_wiki_cls.return_value.get_health = AsyncMock(return_value=mock_report)

            result = await wiki_get_health()
            parsed = json.loads(result)

            assert parsed["total_articles"] == 42
            assert parsed["total_sources"] == 15
            assert parsed["contradictions_count"] == 2
            assert parsed["orphans_count"] == 3

    async def test_get_health_handles_error(self, db_session):
        with (
            patch("wikimind.mcp.server._get_session", return_value=_mock_session_ctx(db_session)),
            patch("wikimind.mcp.server._get_mcp_user_id", return_value=TEST_USER_ID),
            patch("wikimind.mcp.server.WikiService") as mock_wiki_cls,
        ):
            mock_wiki_cls.return_value.get_health = AsyncMock(side_effect=Exception("DB error"))

            result = await wiki_get_health()
            parsed = json.loads(result)
            assert "error" in parsed


# ---------------------------------------------------------------------------
# wiki_get_graph
# ---------------------------------------------------------------------------


class TestWikiGetGraph:
    """Test the wiki_get_graph MCP tool."""

    async def test_get_graph_returns_nodes_and_edges(self, db_session):
        mock_node = AsyncMock()
        mock_node.id = "node-1"
        mock_node.label = "Article One"
        mock_node.concept_cluster = "testing"
        mock_node.connection_count = 2
        mock_node.confidence = "sourced"
        mock_node.effective_confidence = 0.85

        mock_edge = AsyncMock()
        mock_edge.source = "node-1"
        mock_edge.target = "node-2"
        mock_edge.relation_type = "references"
        mock_edge.context = "Related topic"

        mock_graph = AsyncMock()
        mock_graph.nodes = [mock_node]
        mock_graph.edges = [mock_edge]

        with (
            patch("wikimind.mcp.server._get_session", return_value=_mock_session_ctx(db_session)),
            patch("wikimind.mcp.server._get_mcp_user_id", return_value=TEST_USER_ID),
            patch("wikimind.mcp.server.WikiService") as mock_wiki_cls,
        ):
            mock_wiki_cls.return_value.get_graph = AsyncMock(return_value=mock_graph)

            result = await wiki_get_graph(article_slug=None)
            parsed = json.loads(result)

            assert parsed["node_count"] == 1
            assert parsed["edge_count"] == 1
            assert parsed["nodes"][0]["label"] == "Article One"
            assert parsed["edges"][0]["relation_type"] == "references"

    async def test_get_graph_with_article_filter(self, db_session):
        mock_graph = AsyncMock()
        mock_graph.nodes = []
        mock_graph.edges = []

        with (
            patch("wikimind.mcp.server._get_session", return_value=_mock_session_ctx(db_session)),
            patch("wikimind.mcp.server._get_mcp_user_id", return_value=TEST_USER_ID),
            patch("wikimind.mcp.server.WikiService") as mock_wiki_cls,
        ):
            mock_wiki_cls.return_value.get_graph = AsyncMock(return_value=mock_graph)

            result = await wiki_get_graph(article_slug="test-article")
            parsed = json.loads(result)

            assert parsed["node_count"] == 0
            assert parsed["edge_count"] == 0

            # Verify from_article was passed
            call_kwargs = mock_wiki_cls.return_value.get_graph.call_args
            assert call_kwargs.kwargs["from_article"] == "test-article"


# ---------------------------------------------------------------------------
# compare_articles prompt
# ---------------------------------------------------------------------------


class TestCompareArticlesPrompt:
    """Test the compare_articles MCP prompt."""

    async def test_compare_articles_builds_prompt(self, db_session):
        mock_a = AsyncMock()
        mock_a.title = "Article A"
        mock_a.content = "Content of article A"

        mock_b = AsyncMock()
        mock_b.title = "Article B"
        mock_b.content = "Content of article B"

        with (
            patch("wikimind.mcp.server._get_session", return_value=_mock_session_ctx(db_session)),
            patch("wikimind.mcp.server._get_mcp_user_id", return_value=TEST_USER_ID),
            patch("wikimind.mcp.server.WikiService") as mock_wiki_cls,
        ):
            mock_wiki_cls.return_value.get_article = AsyncMock(side_effect=[mock_a, mock_b])

            result = await compare_articles(slug_a="slug-a", slug_b="slug-b")

            assert "Article A" in result
            assert "Article B" in result
            assert "agreements" in result
            assert "disagreements" in result
            assert "Synthesis opportunities" in result

    async def test_compare_articles_handles_error(self, db_session):
        with (
            patch("wikimind.mcp.server._get_session", return_value=_mock_session_ctx(db_session)),
            patch("wikimind.mcp.server._get_mcp_user_id", return_value=TEST_USER_ID),
            patch("wikimind.mcp.server.WikiService") as mock_wiki_cls,
        ):
            mock_wiki_cls.return_value.get_article = AsyncMock(side_effect=Exception("Not found"))

            result = await compare_articles(slug_a="bad", slug_b="also-bad")
            assert "Error" in result


# ---------------------------------------------------------------------------
# knowledge_gaps prompt
# ---------------------------------------------------------------------------


class TestKnowledgeGapsPrompt:
    """Test the knowledge_gaps MCP prompt."""

    async def test_knowledge_gaps_general(self, db_session):
        mock_health = AsyncMock()
        mock_health.total_articles = 10
        mock_health.total_sources = 5
        mock_health.total_findings = 3
        mock_health.contradictions_count = 1
        mock_health.orphans_count = 2
        mock_health.message = None

        with (
            patch("wikimind.mcp.server._get_session", return_value=_mock_session_ctx(db_session)),
            patch("wikimind.mcp.server._get_mcp_user_id", return_value=TEST_USER_ID),
            patch("wikimind.mcp.server.WikiService") as mock_wiki_cls,
        ):
            mock_wiki_cls.return_value.get_health = AsyncMock(return_value=mock_health)

            result = await knowledge_gaps(topic=None)

            assert "Total articles: 10" in result
            assert "knowledge gaps" in result.lower()
            assert "missing" in result.lower()

    async def test_knowledge_gaps_with_topic(self, db_session):
        mock_health = AsyncMock()
        mock_health.total_articles = 10
        mock_health.total_sources = 5
        mock_health.total_findings = None
        mock_health.contradictions_count = None
        mock_health.orphans_count = None
        mock_health.message = "Run the linter"

        mock_result = AsyncMock()
        mock_result.title = "ML Overview"
        mock_result.confidence = "sourced"
        mock_result.summary = "Overview of machine learning"
        mock_result.source_count = 3

        with (
            patch("wikimind.mcp.server._get_session", return_value=_mock_session_ctx(db_session)),
            patch("wikimind.mcp.server._get_mcp_user_id", return_value=TEST_USER_ID),
            patch("wikimind.mcp.server.WikiService") as mock_wiki_cls,
        ):
            mock_wiki_cls.return_value.get_health = AsyncMock(return_value=mock_health)
            mock_wiki_cls.return_value.search = AsyncMock(return_value=[mock_result])

            result = await knowledge_gaps(topic="machine learning")

            assert "machine learning" in result
            assert "ML Overview" in result


# ---------------------------------------------------------------------------
# fact_check prompt
# ---------------------------------------------------------------------------


class TestFactCheckPrompt:
    """Test the fact_check MCP prompt."""

    async def test_fact_check_with_evidence(self, db_session):
        mock_result = AsyncMock()
        mock_result.title = "Climate Science"
        mock_result.confidence = "sourced"
        mock_result.summary = "An article about climate science"
        mock_result.source_count = 5

        with (
            patch("wikimind.mcp.server._get_session", return_value=_mock_session_ctx(db_session)),
            patch("wikimind.mcp.server._get_mcp_user_id", return_value=TEST_USER_ID),
            patch("wikimind.mcp.server.WikiService") as mock_wiki_cls,
        ):
            mock_wiki_cls.return_value.search = AsyncMock(return_value=[mock_result])

            result = await fact_check(claim="The earth is warming")

            assert "The earth is warming" in result
            assert "Climate Science" in result
            assert "Supported" in result
            assert "Contradicted" in result
            assert "Verdict" in result

    async def test_fact_check_no_evidence(self, db_session):
        with (
            patch("wikimind.mcp.server._get_session", return_value=_mock_session_ctx(db_session)),
            patch("wikimind.mcp.server._get_mcp_user_id", return_value=TEST_USER_ID),
            patch("wikimind.mcp.server.WikiService") as mock_wiki_cls,
        ):
            mock_wiki_cls.return_value.search = AsyncMock(return_value=[])

            result = await fact_check(claim="Aliens built the pyramids")

            assert "Aliens built the pyramids" in result
            assert "No relevant articles" in result
