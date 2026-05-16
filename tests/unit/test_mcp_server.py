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
from wikimind.mcp.server import mcp as mcp_server
from wikimind.mcp.server import (
    wiki_get_article,
    wiki_ingest_text,
    wiki_ingest_url,
    wiki_list_articles,
    wiki_list_sources,
    wiki_recompile,
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
# wiki_ingest_url
# ---------------------------------------------------------------------------


class TestWikiIngestUrl:
    """Test the wiki_ingest_url MCP tool."""

    async def test_ingest_url_success(self, db_session):
        mock_source = AsyncMock()
        mock_source.id = "src-123"
        mock_source.source_type = "url"
        mock_source.title = "Example Page"
        mock_source.source_url = "https://example.com/page"

        with (
            patch("wikimind.mcp.server._get_session", return_value=_mock_session_ctx(db_session)),
            patch("wikimind.mcp.server.IngestService") as mock_ingest_cls,
        ):
            mock_ingest_cls.return_value.ingest_url = AsyncMock(return_value=mock_source)

            result = await wiki_ingest_url(url="https://example.com/page", title=None)
            parsed = json.loads(result)

            assert parsed["id"] == "src-123"
            assert parsed["source_type"] == "url"
            assert parsed["title"] == "Example Page"
            assert parsed["status"] == "scheduled_for_compilation"

    async def test_ingest_url_empty_returns_error(self):
        result = await wiki_ingest_url(url="", title=None)
        parsed = json.loads(result)
        assert "error" in parsed
        assert "empty" in parsed["error"]

    async def test_ingest_url_invalid_scheme_returns_error(self):
        result = await wiki_ingest_url(url="ftp://example.com", title=None)
        parsed = json.loads(result)
        assert "error" in parsed
        assert "http" in parsed["error"]

    async def test_ingest_url_handles_exception(self, db_session):
        with (
            patch("wikimind.mcp.server._get_session", return_value=_mock_session_ctx(db_session)),
            patch("wikimind.mcp.server.IngestService") as mock_ingest_cls,
        ):
            mock_ingest_cls.return_value.ingest_url = AsyncMock(
                side_effect=Exception("Network error"),
            )

            result = await wiki_ingest_url(url="https://example.com/bad", title=None)
            parsed = json.loads(result)
            assert "error" in parsed
            assert "Network error" in parsed["error"]


# ---------------------------------------------------------------------------
# wiki_ingest_text
# ---------------------------------------------------------------------------


class TestWikiIngestText:
    """Test the wiki_ingest_text MCP tool."""

    async def test_ingest_text_success(self, db_session):
        mock_source = AsyncMock()
        mock_source.id = "src-456"
        mock_source.source_type = "text"
        mock_source.title = "My Notes"

        with (
            patch("wikimind.mcp.server._get_session", return_value=_mock_session_ctx(db_session)),
            patch("wikimind.mcp.server.IngestService") as mock_ingest_cls,
        ):
            mock_ingest_cls.return_value.ingest_text = AsyncMock(return_value=mock_source)

            result = await wiki_ingest_text(text="Some important content", title="My Notes")
            parsed = json.loads(result)

            assert parsed["id"] == "src-456"
            assert parsed["source_type"] == "text"
            assert parsed["title"] == "My Notes"
            assert parsed["status"] == "scheduled_for_compilation"

    async def test_ingest_text_empty_text_returns_error(self):
        result = await wiki_ingest_text(text="", title="Title")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "Text content" in parsed["error"]

    async def test_ingest_text_empty_title_returns_error(self):
        result = await wiki_ingest_text(text="Some content", title="")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "Title" in parsed["error"]

    async def test_ingest_text_handles_exception(self, db_session):
        with (
            patch("wikimind.mcp.server._get_session", return_value=_mock_session_ctx(db_session)),
            patch("wikimind.mcp.server.IngestService") as mock_ingest_cls,
        ):
            mock_ingest_cls.return_value.ingest_text = AsyncMock(
                side_effect=Exception("Storage full"),
            )

            result = await wiki_ingest_text(text="Content", title="Title")
            parsed = json.loads(result)
            assert "error" in parsed
            assert "Storage full" in parsed["error"]


# ---------------------------------------------------------------------------
# wiki_list_articles
# ---------------------------------------------------------------------------


class TestWikiListArticles:
    """Test the wiki_list_articles MCP tool."""

    async def test_list_articles_returns_results(self, db_session):
        mock_article = AsyncMock()
        mock_article.id = "art-123"
        mock_article.slug = "test-article"
        mock_article.title = "Test Article"
        mock_article.summary = "A summary"
        mock_article.confidence = "sourced"
        mock_article.confidence_score = 0.85
        mock_article.source_count = 2
        mock_article.page_type = "source"
        mock_article.created_at = "2026-01-01"
        mock_article.updated_at = "2026-01-02"

        with (
            patch("wikimind.mcp.server._get_session", return_value=_mock_session_ctx(db_session)),
            patch("wikimind.mcp.server.WikiService") as mock_wiki_cls,
        ):
            mock_wiki_cls.return_value.list_articles = AsyncMock(return_value=[mock_article])

            result = await wiki_list_articles(limit=20, offset=0)
            parsed = json.loads(result)

            assert isinstance(parsed, list)
            assert len(parsed) == 1
            assert parsed[0]["title"] == "Test Article"
            assert parsed[0]["slug"] == "test-article"
            assert parsed[0]["source_count"] == 2

    async def test_list_articles_empty(self, db_session):
        with (
            patch("wikimind.mcp.server._get_session", return_value=_mock_session_ctx(db_session)),
            patch("wikimind.mcp.server.WikiService") as mock_wiki_cls,
        ):
            mock_wiki_cls.return_value.list_articles = AsyncMock(return_value=[])

            result = await wiki_list_articles(limit=20, offset=0)
            parsed = json.loads(result)
            assert parsed == []

    async def test_list_articles_clamps_limit(self, db_session):
        with (
            patch("wikimind.mcp.server._get_session", return_value=_mock_session_ctx(db_session)),
            patch("wikimind.mcp.server.WikiService") as mock_wiki_cls,
        ):
            mock_wiki_cls.return_value.list_articles = AsyncMock(return_value=[])

            await wiki_list_articles(limit=999, offset=0)
            call_kwargs = mock_wiki_cls.return_value.list_articles.call_args
            assert call_kwargs.kwargs["limit"] == 100

    async def test_list_articles_clamps_negative_offset(self, db_session):
        with (
            patch("wikimind.mcp.server._get_session", return_value=_mock_session_ctx(db_session)),
            patch("wikimind.mcp.server.WikiService") as mock_wiki_cls,
        ):
            mock_wiki_cls.return_value.list_articles = AsyncMock(return_value=[])

            await wiki_list_articles(limit=20, offset=-5)
            call_kwargs = mock_wiki_cls.return_value.list_articles.call_args
            assert call_kwargs.kwargs["offset"] == 0


# ---------------------------------------------------------------------------
# wiki_recompile
# ---------------------------------------------------------------------------


class TestWikiRecompile:
    """Test the wiki_recompile MCP tool."""

    async def test_recompile_success(self, db_session):
        mock_result = AsyncMock()
        mock_result.status = "scheduled"
        mock_result.job_id = "job-789"

        with (
            patch("wikimind.mcp.server._get_session", return_value=_mock_session_ctx(db_session)),
            patch("wikimind.mcp.server.WikiService") as mock_wiki_cls,
        ):
            mock_wiki_cls.return_value._resolve_article_id = AsyncMock(return_value="art-123")
            mock_wiki_cls.return_value.recompile_article = AsyncMock(return_value=mock_result)

            result = await wiki_recompile(article_slug="test-article")
            parsed = json.loads(result)

            assert parsed["status"] == "scheduled"
            assert parsed["job_id"] == "job-789"
            assert parsed["article_slug"] == "test-article"

    async def test_recompile_empty_slug_returns_error(self):
        result = await wiki_recompile(article_slug="")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "empty" in parsed["error"]

    async def test_recompile_article_not_found(self, db_session):
        with (
            patch("wikimind.mcp.server._get_session", return_value=_mock_session_ctx(db_session)),
            patch("wikimind.mcp.server.WikiService") as mock_wiki_cls,
        ):
            mock_wiki_cls.return_value._resolve_article_id = AsyncMock(return_value=None)

            result = await wiki_recompile(article_slug="nonexistent")
            parsed = json.loads(result)
            assert "error" in parsed
            assert "not found" in parsed["error"]

    async def test_recompile_handles_exception(self, db_session):
        with (
            patch("wikimind.mcp.server._get_session", return_value=_mock_session_ctx(db_session)),
            patch("wikimind.mcp.server.WikiService") as mock_wiki_cls,
        ):
            mock_wiki_cls.return_value._resolve_article_id = AsyncMock(return_value="art-123")
            mock_wiki_cls.return_value.recompile_article = AsyncMock(
                side_effect=Exception("Article has manual edits"),
            )

            result = await wiki_recompile(article_slug="test-article")
            parsed = json.loads(result)
            assert "error" in parsed
            assert "manual edits" in parsed["error"]


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
        assert "wiki_ingest_url" in tool_names
        assert "wiki_ingest_text" in tool_names
        assert "wiki_list_articles" in tool_names
        assert "wiki_recompile" in tool_names

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
