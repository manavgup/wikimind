"""Tests for WikiMind MCP write tools (Tier 3).

Tests wiki_ingest_url, wiki_ingest_text, and wiki_get_source_status
with mocked service layer.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

from wikimind.mcp.tools_write import (
    wiki_get_source_status,
    wiki_ingest_text,
    wiki_ingest_url,
)
from wikimind.models.enums import IngestStatus

TEST_USER_ID = "test-user-123"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_source(
    source_id: str = "src-001",
    title: str | None = "Test Source",
    status: IngestStatus = IngestStatus.PENDING,
    compiled_at: datetime | None = None,
    error_message: str | None = None,
) -> MagicMock:
    """Create a mock Source object."""
    source = MagicMock()
    source.id = source_id
    source.title = title
    source.status = status
    source.compiled_at = compiled_at
    source.error_message = error_message
    return source


# ---------------------------------------------------------------------------
# wiki_ingest_url
# ---------------------------------------------------------------------------


class TestWikiIngestUrl:
    """Test the wiki_ingest_url tool."""

    @pytest.mark.asyncio
    async def test_ingest_url_returns_source_id_and_queued(self):
        source = _make_source(compiled_at=None)

        with (
            patch("wikimind.mcp.tools_write._get_session") as mock_session_ctx,
            patch("wikimind.mcp.tools_write.get_ingest_service") as mock_factory,
        ):
            session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_factory.return_value.ingest_url = AsyncMock(return_value=source)

            result = await wiki_ingest_url(
                url="https://example.com/article",
                title="",
                user_id=TEST_USER_ID,
            )

            assert result == {"source_id": "src-001", "status": "queued"}

    @pytest.mark.asyncio
    async def test_ingest_url_rejects_file_scheme(self):
        with pytest.raises(ToolError, match="Only http:// and https://"):
            await wiki_ingest_url(
                url="file:///etc/passwd",
                title="",
                user_id=TEST_USER_ID,
            )

    @pytest.mark.asyncio
    async def test_ingest_url_rejects_ftp_scheme(self):
        with pytest.raises(ToolError, match="Only http:// and https://"):
            await wiki_ingest_url(
                url="ftp://example.com/file",
                title="",
                user_id=TEST_USER_ID,
            )

    @pytest.mark.asyncio
    async def test_ingest_url_rejects_long_title(self):
        with pytest.raises(ToolError, match="200 characters"):
            await wiki_ingest_url(
                url="https://example.com",
                title="x" * 201,
                user_id=TEST_USER_ID,
            )

    @pytest.mark.asyncio
    async def test_ingest_url_applies_title_override(self):
        source = _make_source(compiled_at=None)

        with (
            patch("wikimind.mcp.tools_write._get_session") as mock_session_ctx,
            patch("wikimind.mcp.tools_write.get_ingest_service") as mock_factory,
        ):
            session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_factory.return_value.ingest_url = AsyncMock(return_value=source)

            await wiki_ingest_url(
                url="https://example.com/article",
                title="Custom Title",
                user_id=TEST_USER_ID,
            )

            # Verify title was set on the source object
            assert source.title == "Custom Title"
            # Verify session.commit() was called
            session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_ingest_url_dedup_returns_already_exists(self):
        source = _make_source(
            compiled_at=datetime(2026, 1, 1),
            status=IngestStatus.COMPILED,
        )

        with (
            patch("wikimind.mcp.tools_write._get_session") as mock_session_ctx,
            patch("wikimind.mcp.tools_write.get_ingest_service") as mock_factory,
            patch(
                "wikimind.mcp.tools_write._find_article_slug_for_source",
                new_callable=AsyncMock,
                return_value="existing-article",
            ),
        ):
            session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_factory.return_value.ingest_url = AsyncMock(return_value=source)

            result = await wiki_ingest_url(
                url="https://example.com/duplicate",
                title="",
                user_id=TEST_USER_ID,
            )

            assert result["status"] == "already_exists"
            assert result["source_id"] == "src-001"
            assert result["article_slug"] == "existing-article"

    @pytest.mark.asyncio
    async def test_ingest_url_dedup_without_article_slug(self):
        source = _make_source(compiled_at=datetime(2026, 1, 1))

        with (
            patch("wikimind.mcp.tools_write._get_session") as mock_session_ctx,
            patch("wikimind.mcp.tools_write.get_ingest_service") as mock_factory,
            patch(
                "wikimind.mcp.tools_write._find_article_slug_for_source",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_factory.return_value.ingest_url = AsyncMock(return_value=source)

            result = await wiki_ingest_url(
                url="https://example.com/duplicate",
                title="",
                user_id=TEST_USER_ID,
            )

            assert result["status"] == "already_exists"
            assert "article_slug" not in result

    @pytest.mark.asyncio
    async def test_ingest_url_wraps_ingest_error(self):
        from wikimind.errors import IngestError

        with (
            patch("wikimind.mcp.tools_write._get_session") as mock_session_ctx,
            patch("wikimind.mcp.tools_write.get_ingest_service") as mock_factory,
        ):
            session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_factory.return_value.ingest_url = AsyncMock(side_effect=IngestError("Network timeout"))

            with pytest.raises(ToolError, match="Ingestion failed"):
                await wiki_ingest_url(
                    url="https://example.com/timeout",
                    title="",
                    user_id=TEST_USER_ID,
                )


# ---------------------------------------------------------------------------
# wiki_ingest_text
# ---------------------------------------------------------------------------


class TestWikiIngestText:
    """Test the wiki_ingest_text tool."""

    @pytest.mark.asyncio
    async def test_ingest_text_returns_source_id_and_queued(self):
        source = _make_source(compiled_at=None)

        with (
            patch("wikimind.mcp.tools_write._get_session") as mock_session_ctx,
            patch("wikimind.mcp.tools_write.get_ingest_service") as mock_factory,
        ):
            session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_factory.return_value.ingest_text = AsyncMock(return_value=source)

            result = await wiki_ingest_text(
                text="Some interesting content to ingest.",
                title="My Note",
                user_id=TEST_USER_ID,
            )

            assert result == {"source_id": "src-001", "status": "queued"}

    @pytest.mark.asyncio
    async def test_ingest_text_rejects_empty_text(self):
        with pytest.raises(ToolError, match="at least 1 character"):
            await wiki_ingest_text(
                text="",
                title="Title",
                user_id=TEST_USER_ID,
            )

    @pytest.mark.asyncio
    async def test_ingest_text_rejects_too_long_text(self):
        with pytest.raises(ToolError, match="100000 characters"):
            await wiki_ingest_text(
                text="x" * 100001,
                title="Title",
                user_id=TEST_USER_ID,
            )

    @pytest.mark.asyncio
    async def test_ingest_text_rejects_empty_title(self):
        with pytest.raises(ToolError, match="Title is required"):
            await wiki_ingest_text(
                text="Some content",
                title="",
                user_id=TEST_USER_ID,
            )

    @pytest.mark.asyncio
    async def test_ingest_text_rejects_long_title(self):
        with pytest.raises(ToolError, match="200 characters"):
            await wiki_ingest_text(
                text="Some content",
                title="x" * 201,
                user_id=TEST_USER_ID,
            )

    @pytest.mark.asyncio
    async def test_ingest_text_dedup_returns_already_exists(self):
        source = _make_source(
            compiled_at=datetime(2026, 1, 1),
            status=IngestStatus.COMPILED,
        )

        with (
            patch("wikimind.mcp.tools_write._get_session") as mock_session_ctx,
            patch("wikimind.mcp.tools_write.get_ingest_service") as mock_factory,
            patch(
                "wikimind.mcp.tools_write._find_article_slug_for_source",
                new_callable=AsyncMock,
                return_value="dedup-article",
            ),
        ):
            session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_factory.return_value.ingest_text = AsyncMock(return_value=source)

            result = await wiki_ingest_text(
                text="Duplicate content",
                title="Duplicate Title",
                user_id=TEST_USER_ID,
            )

            assert result["status"] == "already_exists"
            assert result["source_id"] == "src-001"
            assert result["article_slug"] == "dedup-article"

    @pytest.mark.asyncio
    async def test_ingest_text_wraps_ingest_error(self):
        from wikimind.errors import IngestError

        with (
            patch("wikimind.mcp.tools_write._get_session") as mock_session_ctx,
            patch("wikimind.mcp.tools_write.get_ingest_service") as mock_factory,
        ):
            session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_factory.return_value.ingest_text = AsyncMock(side_effect=IngestError("Parse error"))

            with pytest.raises(ToolError, match="Ingestion failed"):
                await wiki_ingest_text(
                    text="Some content",
                    title="Title",
                    user_id=TEST_USER_ID,
                )


# ---------------------------------------------------------------------------
# wiki_get_source_status
# ---------------------------------------------------------------------------


class TestWikiGetSourceStatus:
    """Test the wiki_get_source_status tool."""

    @pytest.mark.asyncio
    async def test_status_pending_returns_queued(self):
        source = _make_source(status=IngestStatus.PENDING)

        with (
            patch("wikimind.mcp.tools_write._get_session") as mock_session_ctx,
            patch("wikimind.mcp.tools_write.get_ingest_service") as mock_factory,
        ):
            session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_factory.return_value.get_source = AsyncMock(return_value=source)

            result = await wiki_get_source_status(
                source_id="src-001",
                user_id=TEST_USER_ID,
            )

            assert result["source_id"] == "src-001"
            assert result["status"] == "queued"
            assert result["title"] == "Test Source"

    @pytest.mark.asyncio
    async def test_status_processing(self):
        source = _make_source(status=IngestStatus.PROCESSING)

        with (
            patch("wikimind.mcp.tools_write._get_session") as mock_session_ctx,
            patch("wikimind.mcp.tools_write.get_ingest_service") as mock_factory,
        ):
            session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_factory.return_value.get_source = AsyncMock(return_value=source)

            result = await wiki_get_source_status(
                source_id="src-001",
                user_id=TEST_USER_ID,
            )

            assert result["status"] == "processing"

    @pytest.mark.asyncio
    async def test_status_compiled_includes_article_slug(self):
        source = _make_source(status=IngestStatus.COMPILED)

        with (
            patch("wikimind.mcp.tools_write._get_session") as mock_session_ctx,
            patch("wikimind.mcp.tools_write.get_ingest_service") as mock_factory,
            patch(
                "wikimind.mcp.tools_write._find_article_slug_for_source",
                new_callable=AsyncMock,
                return_value="compiled-article",
            ),
        ):
            session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_factory.return_value.get_source = AsyncMock(return_value=source)

            result = await wiki_get_source_status(
                source_id="src-001",
                user_id=TEST_USER_ID,
            )

            assert result["status"] == "compiled"
            assert result["article_slug"] == "compiled-article"

    @pytest.mark.asyncio
    async def test_status_failed_includes_error(self):
        source = _make_source(
            status=IngestStatus.FAILED,
            error_message="LLM rate limit exceeded",
        )

        with (
            patch("wikimind.mcp.tools_write._get_session") as mock_session_ctx,
            patch("wikimind.mcp.tools_write.get_ingest_service") as mock_factory,
        ):
            session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_factory.return_value.get_source = AsyncMock(return_value=source)

            result = await wiki_get_source_status(
                source_id="src-001",
                user_id=TEST_USER_ID,
            )

            assert result["status"] == "failed"
            assert result["error"] == "LLM rate limit exceeded"

    @pytest.mark.asyncio
    async def test_status_not_found_raises_tool_error(self):
        from wikimind.errors import NotFoundError

        with (
            patch("wikimind.mcp.tools_write._get_session") as mock_session_ctx,
            patch("wikimind.mcp.tools_write.get_ingest_service") as mock_factory,
        ):
            session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_factory.return_value.get_source = AsyncMock(side_effect=NotFoundError("Source not found"))

            with pytest.raises(ToolError, match="Source not found"):
                await wiki_get_source_status(
                    source_id="nonexistent",
                    user_id=TEST_USER_ID,
                )

    @pytest.mark.asyncio
    async def test_status_compiled_without_article_slug(self):
        source = _make_source(status=IngestStatus.COMPILED)

        with (
            patch("wikimind.mcp.tools_write._get_session") as mock_session_ctx,
            patch("wikimind.mcp.tools_write.get_ingest_service") as mock_factory,
            patch(
                "wikimind.mcp.tools_write._find_article_slug_for_source",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_factory.return_value.get_source = AsyncMock(return_value=source)

            result = await wiki_get_source_status(
                source_id="src-001",
                user_id=TEST_USER_ID,
            )

            assert result["status"] == "compiled"
            assert "article_slug" not in result

    @pytest.mark.asyncio
    async def test_status_failed_without_error_message(self):
        source = _make_source(
            status=IngestStatus.FAILED,
            error_message=None,
        )

        with (
            patch("wikimind.mcp.tools_write._get_session") as mock_session_ctx,
            patch("wikimind.mcp.tools_write.get_ingest_service") as mock_factory,
        ):
            session = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=session)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_factory.return_value.get_source = AsyncMock(return_value=source)

            result = await wiki_get_source_status(
                source_id="src-001",
                user_id=TEST_USER_ID,
            )

            assert result["status"] == "failed"
            assert "error" not in result
