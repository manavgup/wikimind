"""Tests for WikiMind MCP discovery tools (Tier 1).

Tests wiki_overview, wiki_list_articles, and wiki_list_concepts
with mocked service layer dependencies.
"""

from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

from wikimind.mcp.tools_discovery import (
    wiki_list_articles,
    wiki_list_concepts,
    wiki_overview,
)

TEST_USER_ID = "test-user"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def _mock_session_ctx(session=None):
    """Build an async context manager that yields the given session."""
    yield session or MagicMock()


def _mock_ctx() -> MagicMock:
    """Create a mock MCP Context with async log method."""
    ctx = MagicMock()
    ctx.log = AsyncMock()
    return ctx


def _mock_stats(**overrides):
    """Create a mock SystemStats object."""
    defaults = {
        "article_count": 10,
        "source_count": 5,
        "concept_count": 3,
        "articles_by_page_type": {"source": 7, "concept": 2, "synthesis": 1},
    }
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


def _mock_concept(name: str, article_count: int = 2, concept_kind: str = "topic"):
    """Create a mock Concept object."""
    mock = MagicMock()
    mock.name = name
    mock.article_count = article_count
    mock.concept_kind = concept_kind
    return mock


def _mock_article(
    slug: str = "test-article",
    title: str = "Test Article",
    summary: str = "A summary",
    concepts: list | None = None,
    page_type: str = "source",
    source_count: int = 1,
    confidence: str = "sourced",
    updated_at: str = "2026-01-01T00:00:00",
):
    """Create a mock ArticleSummaryResponse object."""
    mock = MagicMock()
    mock.slug = slug
    mock.title = title
    mock.summary = summary
    mock.concepts = concepts or ["ml"]
    mock.page_type = page_type
    mock.source_count = source_count
    mock.confidence = confidence
    mock.updated_at = updated_at
    return mock


# ---------------------------------------------------------------------------
# wiki_overview
# ---------------------------------------------------------------------------


class TestWikiOverview:
    """Test the wiki_overview discovery tool."""

    @pytest.mark.asyncio
    async def test_returns_article_and_concept_counts(self):
        ctx = _mock_ctx()
        stats = _mock_stats(article_count=42, source_count=15)
        concepts = [
            _mock_concept("Machine Learning", article_count=10),
            _mock_concept("NLP", article_count=5),
        ]
        articles = [
            _mock_article(slug="recent-1", title="Recent One"),
            _mock_article(slug="recent-2", title="Recent Two"),
        ]

        mock_wiki_svc = MagicMock()
        mock_wiki_svc.get_concepts = AsyncMock(return_value=concepts)
        mock_wiki_svc.list_articles = AsyncMock(return_value=articles)

        mock_admin_svc = MagicMock()
        mock_admin_svc.get_stats = AsyncMock(return_value=stats)

        with (
            patch(
                "wikimind.mcp.tools_discovery._get_mcp_user_id",
                new_callable=AsyncMock,
                return_value=TEST_USER_ID,
            ),
            patch(
                "wikimind.mcp.tools_discovery._get_session",
                return_value=_mock_session_ctx(),
            ),
            patch(
                "wikimind.services.wiki.WikiService",
                return_value=mock_wiki_svc,
            ),
            patch(
                "wikimind.services.admin.AdminService",
                return_value=mock_admin_svc,
            ),
        ):
            result = await wiki_overview(ctx)

            assert result["article_count"] == 42
            assert result["source_count"] == 15
            assert result["concept_count"] == 2
            assert len(result["concepts"]) == 2
            assert result["concepts"][0]["name"] == "Machine Learning"
            assert result["concepts"][0]["article_count"] == 10
            assert result["page_type_breakdown"] == {
                "source": 7,
                "concept": 2,
                "synthesis": 1,
            }

    @pytest.mark.asyncio
    async def test_returns_max_5_recent_articles(self):
        ctx = _mock_ctx()
        stats = _mock_stats()
        concepts = [_mock_concept("Topic")]
        articles = [_mock_article(slug=f"article-{i}") for i in range(7)]

        mock_wiki_svc = MagicMock()
        mock_wiki_svc.get_concepts = AsyncMock(return_value=concepts)
        mock_wiki_svc.list_articles = AsyncMock(return_value=articles)

        mock_admin_svc = MagicMock()
        mock_admin_svc.get_stats = AsyncMock(return_value=stats)

        with (
            patch(
                "wikimind.mcp.tools_discovery._get_mcp_user_id",
                new_callable=AsyncMock,
                return_value=TEST_USER_ID,
            ),
            patch(
                "wikimind.mcp.tools_discovery._get_session",
                return_value=_mock_session_ctx(),
            ),
            patch(
                "wikimind.services.wiki.WikiService",
                return_value=mock_wiki_svc,
            ),
            patch(
                "wikimind.services.admin.AdminService",
                return_value=mock_admin_svc,
            ),
        ):
            result = await wiki_overview(ctx)

            assert len(result["recent_articles"]) == 5

    @pytest.mark.asyncio
    async def test_logs_info_message(self):
        ctx = _mock_ctx()
        stats = _mock_stats(article_count=3)
        concepts = [_mock_concept("A"), _mock_concept("B")]

        mock_wiki_svc = MagicMock()
        mock_wiki_svc.get_concepts = AsyncMock(return_value=concepts)
        mock_wiki_svc.list_articles = AsyncMock(return_value=[])

        mock_admin_svc = MagicMock()
        mock_admin_svc.get_stats = AsyncMock(return_value=stats)

        with (
            patch(
                "wikimind.mcp.tools_discovery._get_mcp_user_id",
                new_callable=AsyncMock,
                return_value=TEST_USER_ID,
            ),
            patch(
                "wikimind.mcp.tools_discovery._get_session",
                return_value=_mock_session_ctx(),
            ),
            patch(
                "wikimind.services.wiki.WikiService",
                return_value=mock_wiki_svc,
            ),
            patch(
                "wikimind.services.admin.AdminService",
                return_value=mock_admin_svc,
            ),
        ):
            await wiki_overview(ctx)

            ctx.log.assert_called_once_with("Wiki has 3 articles across 2 concepts", level="info")

    @pytest.mark.asyncio
    async def test_wraps_unexpected_errors_in_tool_error(self):
        ctx = _mock_ctx()

        mock_admin_svc = MagicMock()
        mock_admin_svc.get_stats = AsyncMock(side_effect=RuntimeError("DB connection lost"))

        with (
            patch(
                "wikimind.mcp.tools_discovery._get_mcp_user_id",
                new_callable=AsyncMock,
                return_value=TEST_USER_ID,
            ),
            patch(
                "wikimind.mcp.tools_discovery._get_session",
                return_value=_mock_session_ctx(),
            ),
            patch(
                "wikimind.services.admin.AdminService",
                return_value=mock_admin_svc,
            ),
            pytest.raises(ToolError, match="Failed to get wiki overview"),
        ):
            await wiki_overview(ctx)


# ---------------------------------------------------------------------------
# wiki_list_articles
# ---------------------------------------------------------------------------


class TestWikiListArticles:
    """Test the wiki_list_articles discovery tool."""

    @pytest.mark.asyncio
    async def test_returns_articles_with_pagination(self):
        ctx = _mock_ctx()
        articles = [
            _mock_article(slug="a1", title="Article 1"),
            _mock_article(slug="a2", title="Article 2"),
        ]

        mock_wiki_svc = MagicMock()
        mock_wiki_svc.list_articles = AsyncMock(return_value=articles)

        with (
            patch(
                "wikimind.mcp.tools_discovery._get_mcp_user_id",
                new_callable=AsyncMock,
                return_value=TEST_USER_ID,
            ),
            patch(
                "wikimind.mcp.tools_discovery._get_session",
                return_value=_mock_session_ctx(),
            ),
            patch(
                "wikimind.services.wiki.WikiService",
                return_value=mock_wiki_svc,
            ),
        ):
            result = await wiki_list_articles(ctx, limit=20, offset=0)

            assert len(result["articles"]) == 2
            assert result["articles"][0]["slug"] == "a1"
            assert result["articles"][1]["title"] == "Article 2"

    @pytest.mark.asyncio
    async def test_rejects_invalid_page_type(self):
        ctx = _mock_ctx()

        with pytest.raises(ToolError, match="Invalid page_type"):
            await wiki_list_articles(ctx, page_type="invalid_type")

    @pytest.mark.asyncio
    async def test_rejects_negative_offset(self):
        ctx = _mock_ctx()

        with pytest.raises(ToolError, match="offset must be >= 0"):
            await wiki_list_articles(ctx, offset=-1)

    @pytest.mark.asyncio
    async def test_clamps_limit_to_100(self):
        ctx = _mock_ctx()

        mock_wiki_svc = MagicMock()
        mock_wiki_svc.list_articles = AsyncMock(return_value=[])

        with (
            patch(
                "wikimind.mcp.tools_discovery._get_mcp_user_id",
                new_callable=AsyncMock,
                return_value=TEST_USER_ID,
            ),
            patch(
                "wikimind.mcp.tools_discovery._get_session",
                return_value=_mock_session_ctx(),
            ),
            patch(
                "wikimind.services.wiki.WikiService",
                return_value=mock_wiki_svc,
            ),
        ):
            result = await wiki_list_articles(ctx, limit=500)

            # Verify service was called with clamped limit
            call_kwargs = mock_wiki_svc.list_articles.call_args
            assert call_kwargs[1]["limit"] == 100
            # Verify warning in response
            assert "warning" in result
            assert "clamped" in result["warning"]

    @pytest.mark.asyncio
    async def test_clamps_limit_minimum_to_1(self):
        ctx = _mock_ctx()

        mock_wiki_svc = MagicMock()
        mock_wiki_svc.list_articles = AsyncMock(return_value=[])

        with (
            patch(
                "wikimind.mcp.tools_discovery._get_mcp_user_id",
                new_callable=AsyncMock,
                return_value=TEST_USER_ID,
            ),
            patch(
                "wikimind.mcp.tools_discovery._get_session",
                return_value=_mock_session_ctx(),
            ),
            patch(
                "wikimind.services.wiki.WikiService",
                return_value=mock_wiki_svc,
            ),
        ):
            result = await wiki_list_articles(ctx, limit=0)

            call_kwargs = mock_wiki_svc.list_articles.call_args
            assert call_kwargs[1]["limit"] == 1
            assert "warning" in result

    @pytest.mark.asyncio
    async def test_passes_concept_and_page_type_filters(self):
        ctx = _mock_ctx()

        mock_wiki_svc = MagicMock()
        mock_wiki_svc.list_articles = AsyncMock(return_value=[])

        with (
            patch(
                "wikimind.mcp.tools_discovery._get_mcp_user_id",
                new_callable=AsyncMock,
                return_value=TEST_USER_ID,
            ),
            patch(
                "wikimind.mcp.tools_discovery._get_session",
                return_value=_mock_session_ctx(),
            ),
            patch(
                "wikimind.services.wiki.WikiService",
                return_value=mock_wiki_svc,
            ),
        ):
            await wiki_list_articles(ctx, concept="Machine Learning", page_type="synthesis")

            call_kwargs = mock_wiki_svc.list_articles.call_args
            assert call_kwargs[1]["concept"] == "Machine Learning"
            assert call_kwargs[1]["page_type"] == "synthesis"

    @pytest.mark.asyncio
    async def test_accepts_all_valid_page_types(self):
        ctx = _mock_ctx()

        for pt in ("source", "concept", "synthesis", "answer"):
            mock_wiki_svc = MagicMock()
            mock_wiki_svc.list_articles = AsyncMock(return_value=[])

            with (
                patch(
                    "wikimind.mcp.tools_discovery._get_mcp_user_id",
                    new_callable=AsyncMock,
                    return_value=TEST_USER_ID,
                ),
                patch(
                    "wikimind.mcp.tools_discovery._get_session",
                    return_value=_mock_session_ctx(),
                ),
                patch(
                    "wikimind.services.wiki.WikiService",
                    return_value=mock_wiki_svc,
                ),
            ):
                # Should not raise
                await wiki_list_articles(ctx, page_type=pt)

    @pytest.mark.asyncio
    async def test_wraps_unexpected_errors_in_tool_error(self):
        ctx = _mock_ctx()

        mock_wiki_svc = MagicMock()
        mock_wiki_svc.list_articles = AsyncMock(side_effect=RuntimeError("timeout"))

        with (
            patch(
                "wikimind.mcp.tools_discovery._get_mcp_user_id",
                new_callable=AsyncMock,
                return_value=TEST_USER_ID,
            ),
            patch(
                "wikimind.mcp.tools_discovery._get_session",
                return_value=_mock_session_ctx(),
            ),
            patch(
                "wikimind.services.wiki.WikiService",
                return_value=mock_wiki_svc,
            ),
            pytest.raises(ToolError, match="Failed to list articles"),
        ):
            await wiki_list_articles(ctx)


# ---------------------------------------------------------------------------
# wiki_list_concepts
# ---------------------------------------------------------------------------


class TestWikiListConcepts:
    """Test the wiki_list_concepts discovery tool."""

    @pytest.mark.asyncio
    async def test_returns_concepts_with_article_counts(self):
        ctx = _mock_ctx()
        concepts = [
            _mock_concept("Machine Learning", article_count=10, concept_kind="topic"),
            _mock_concept("NLP", article_count=5, concept_kind="domain"),
        ]

        mock_wiki_svc = MagicMock()
        mock_wiki_svc.get_concepts = AsyncMock(return_value=concepts)

        with (
            patch(
                "wikimind.mcp.tools_discovery._get_mcp_user_id",
                new_callable=AsyncMock,
                return_value=TEST_USER_ID,
            ),
            patch(
                "wikimind.mcp.tools_discovery._get_session",
                return_value=_mock_session_ctx(),
            ),
            patch(
                "wikimind.services.wiki.WikiService",
                return_value=mock_wiki_svc,
            ),
        ):
            result = await wiki_list_concepts(ctx)

            assert len(result["concepts"]) == 2
            assert result["concepts"][0]["name"] == "Machine Learning"
            assert result["concepts"][0]["article_count"] == 10
            assert result["concepts"][0]["concept_kind"] == "topic"
            assert result["concepts"][1]["name"] == "NLP"
            assert result["concepts"][1]["concept_kind"] == "domain"

    @pytest.mark.asyncio
    async def test_excludes_empty_concepts_by_default(self):
        ctx = _mock_ctx()

        mock_wiki_svc = MagicMock()
        mock_wiki_svc.get_concepts = AsyncMock(return_value=[])

        with (
            patch(
                "wikimind.mcp.tools_discovery._get_mcp_user_id",
                new_callable=AsyncMock,
                return_value=TEST_USER_ID,
            ),
            patch(
                "wikimind.mcp.tools_discovery._get_session",
                return_value=_mock_session_ctx(),
            ),
            patch(
                "wikimind.services.wiki.WikiService",
                return_value=mock_wiki_svc,
            ),
        ):
            await wiki_list_concepts(ctx)

            call_kwargs = mock_wiki_svc.get_concepts.call_args
            assert call_kwargs[1]["include_empty"] is False

    @pytest.mark.asyncio
    async def test_includes_empty_concepts_when_requested(self):
        ctx = _mock_ctx()

        mock_wiki_svc = MagicMock()
        mock_wiki_svc.get_concepts = AsyncMock(return_value=[])

        with (
            patch(
                "wikimind.mcp.tools_discovery._get_mcp_user_id",
                new_callable=AsyncMock,
                return_value=TEST_USER_ID,
            ),
            patch(
                "wikimind.mcp.tools_discovery._get_session",
                return_value=_mock_session_ctx(),
            ),
            patch(
                "wikimind.services.wiki.WikiService",
                return_value=mock_wiki_svc,
            ),
        ):
            await wiki_list_concepts(ctx, include_empty=True)

            call_kwargs = mock_wiki_svc.get_concepts.call_args
            assert call_kwargs[1]["include_empty"] is True

    @pytest.mark.asyncio
    async def test_logs_concept_count(self):
        ctx = _mock_ctx()
        concepts = [_mock_concept("A"), _mock_concept("B"), _mock_concept("C")]

        mock_wiki_svc = MagicMock()
        mock_wiki_svc.get_concepts = AsyncMock(return_value=concepts)

        with (
            patch(
                "wikimind.mcp.tools_discovery._get_mcp_user_id",
                new_callable=AsyncMock,
                return_value=TEST_USER_ID,
            ),
            patch(
                "wikimind.mcp.tools_discovery._get_session",
                return_value=_mock_session_ctx(),
            ),
            patch(
                "wikimind.services.wiki.WikiService",
                return_value=mock_wiki_svc,
            ),
        ):
            await wiki_list_concepts(ctx)

            ctx.log.assert_called_once_with("Found 3 concepts", level="info")

    @pytest.mark.asyncio
    async def test_wraps_unexpected_errors_in_tool_error(self):
        ctx = _mock_ctx()

        mock_wiki_svc = MagicMock()
        mock_wiki_svc.get_concepts = AsyncMock(side_effect=RuntimeError("connection refused"))

        with (
            patch(
                "wikimind.mcp.tools_discovery._get_mcp_user_id",
                new_callable=AsyncMock,
                return_value=TEST_USER_ID,
            ),
            patch(
                "wikimind.mcp.tools_discovery._get_session",
                return_value=_mock_session_ctx(),
            ),
            patch(
                "wikimind.services.wiki.WikiService",
                return_value=mock_wiki_svc,
            ),
            pytest.raises(ToolError, match="Failed to list concepts"),
        ):
            await wiki_list_concepts(ctx)
