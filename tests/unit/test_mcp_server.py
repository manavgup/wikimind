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
    mcp as mcp_server,
)
from wikimind.mcp.server import (
    wiki_get_article,
    wiki_search,
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
        # Tier 1: Discovery
        assert "wiki_overview" in tool_names
        assert "wiki_list_articles" in tool_names
        assert "wiki_list_concepts" in tool_names
        # Tier 2: Read/Search
        assert "wiki_search" in tool_names
        assert "wiki_get_article" in tool_names
        assert "wiki_ask" in tool_names
        # Tier 3: Write
        assert "wiki_ingest_url" in tool_names
        assert "wiki_ingest_text" in tool_names
        assert "wiki_get_source_status" in tool_names
        # Tier 4: Analysis
        assert "wiki_synthesize" in tool_names
        assert "wiki_get_health" in tool_names
        assert "wiki_list_sources" in tool_names
        assert "wiki_get_graph" in tool_names

    async def test_server_has_13_tools(self):
        tools = await mcp_server.list_tools()
        assert len(tools) == 13

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


# ---------------------------------------------------------------------------
# MCP Resources
# ---------------------------------------------------------------------------


class TestMCPResourceRegistration:
    """Test that MCP resources are properly registered on the server."""

    async def test_server_lists_resource_templates(self):
        templates = await mcp_server.list_resource_templates()
        template_names = {t.name for t in templates}
        assert "article" in template_names
        assert "source" in template_names

    async def test_article_resource_template_uri(self):
        templates = await mcp_server.list_resource_templates()
        by_name = {t.name: t for t in templates}
        assert "wikimind://articles/{slug}" in by_name["article"].uri_template

    async def test_source_resource_template_uri(self):
        templates = await mcp_server.list_resource_templates()
        by_name = {t.name: t for t in templates}
        assert "wikimind://sources/{source_id}" in by_name["source"].uri_template

    async def test_resource_descriptions_present(self):
        templates = await mcp_server.list_resource_templates()
        for t in templates:
            assert t.description, f"Resource template {t.name} missing description"


# ---------------------------------------------------------------------------
# MCP Prompts
# ---------------------------------------------------------------------------


class TestMCPPromptRegistration:
    """Test that MCP prompts are properly registered on the server."""

    async def test_server_lists_prompts(self):
        prompts = await mcp_server.list_prompts()
        prompt_names = {p.name for p in prompts}
        assert "wiki_onboarding" in prompt_names
        assert "research_topic" in prompt_names
        assert "compare_articles" in prompt_names
        assert "knowledge_gaps" in prompt_names

    async def test_server_has_4_prompts(self):
        prompts = await mcp_server.list_prompts()
        assert len(prompts) == 4

    async def test_prompt_descriptions_present(self):
        prompts = await mcp_server.list_prompts()
        for p in prompts:
            assert p.description, f"Prompt {p.name} missing description"
            assert len(p.description) > 20, f"Prompt {p.name} description too short"
