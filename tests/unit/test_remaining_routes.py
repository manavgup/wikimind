"""Route-level tests for admin, jobs, ingest, query, and wiki endpoints.

These tests hit the FastAPI app via the test client to cover the thin
route handler functions that delegate to the service layer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wikimind.api.deps import ANONYMOUS_USER_ID
from wikimind.models import (
    Article,
    PageType,
    Source,
    SourceType,
)

if TYPE_CHECKING:
    from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------


class TestAdminRoutes:
    @pytest.mark.asyncio
    async def test_get_stats(self, client: AsyncClient):
        resp = await client.get("/api/admin/stats")
        assert resp.status_code == 200
        assert isinstance(resp.json(), dict)

    @pytest.mark.asyncio
    async def test_get_orphans(self, client: AsyncClient):
        resp = await client.get("/api/admin/orphans")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_eligible_concepts(self, client: AsyncClient):
        resp = await client.get("/api/admin/concepts/eligible")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_trigger_sweep(self, client: AsyncClient):
        mock_bg = MagicMock()
        mock_bg.schedule_lint = AsyncMock()
        with patch("wikimind.services.admin.get_background_compiler", return_value=mock_bg):
            resp = await client.post("/api/admin/sweep")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_trigger_reindex(self, client: AsyncClient):
        resp = await client.post("/api/admin/reindex")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Jobs routes
# ---------------------------------------------------------------------------


class TestJobsRoutes:
    @pytest.mark.asyncio
    async def test_list_jobs(self, client: AsyncClient):
        resp = await client.get("/api/jobs")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_get_job_not_found(self, client: AsyncClient):
        resp = await client.get("/api/jobs/nonexistent-id")
        assert resp.status_code == 200
        assert resp.json() is None

    @pytest.mark.asyncio
    async def test_trigger_compile(self, client: AsyncClient):
        mock_bg = MagicMock()
        mock_bg.schedule_compile = AsyncMock(return_value="job-123")
        with patch("wikimind.services.compiler.get_background_compiler", return_value=mock_bg):
            resp = await client.post("/api/jobs/compile/some-source-id")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_trigger_lint(self, client: AsyncClient):
        mock_bg = MagicMock()
        mock_bg.schedule_lint = AsyncMock(return_value="job-456")
        with patch("wikimind.services.linter.get_background_compiler", return_value=mock_bg):
            resp = await client.post("/api/jobs/lint")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_trigger_reindex(self, client: AsyncClient):
        resp = await client.post("/api/jobs/reindex")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Ingest routes
# ---------------------------------------------------------------------------


class TestIngestRoutes:
    @pytest.mark.asyncio
    async def test_ingest_text(self, client: AsyncClient):
        with patch("wikimind.services.ingest.get_background_compiler") as mock_bg:
            mock_bg.return_value.schedule_compile = AsyncMock()
            resp = await client.post(
                "/api/ingest/text",
                json={
                    "content": "Test content for coverage.",
                    "title": "Coverage Test",
                    "auto_compile": False,
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Coverage Test"

    @pytest.mark.asyncio
    async def test_ingest_url(self, client: AsyncClient):
        mock_source = Source(
            source_type=SourceType.URL,
            source_url="http://example.com",
            title="Example",
            user_id=ANONYMOUS_USER_ID,
        )
        with patch.object(
            __import__("wikimind.services.ingest", fromlist=["IngestService"]).IngestService,
            "ingest_url",
            new_callable=AsyncMock,
            return_value=mock_source,
        ):
            resp = await client.post(
                "/api/ingest/url",
                json={"url": "http://example.com", "auto_compile": False},
            )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_sources(self, client: AsyncClient):
        resp = await client.get("/api/ingest/sources")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_source_not_found(self, client: AsyncClient):
        resp = await client.get("/api/ingest/sources/nonexistent")
        assert resp.status_code in (404, 422)

    @pytest.mark.asyncio
    async def test_delete_source_not_found(self, client: AsyncClient):
        resp = await client.delete("/api/ingest/sources/nonexistent")
        assert resp.status_code in (404, 422)

    @pytest.mark.asyncio
    async def test_ingest_pdf_invalid(self, client: AsyncClient):
        """Uploading a non-PDF should return 400."""
        resp = await client.post(
            "/api/ingest/pdf",
            files={"file": ("test.txt", b"not a pdf", "text/plain")},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_source_content_not_found(self, client: AsyncClient):
        resp = await client.get("/api/ingest/sources/nonexistent/content")
        assert resp.status_code in (404, 422)

    @pytest.mark.asyncio
    async def test_source_original_not_found(self, client: AsyncClient):
        resp = await client.get("/api/ingest/sources/nonexistent/original")
        assert resp.status_code in (404, 422)

    @pytest.mark.asyncio
    async def test_source_images_not_found(self, client: AsyncClient):
        resp = await client.get("/api/ingest/sources/nonexistent/images")
        assert resp.status_code in (404, 422)


# ---------------------------------------------------------------------------
# Query routes
# ---------------------------------------------------------------------------


class TestQueryRoutes:
    @pytest.mark.asyncio
    async def test_query_history(self, client: AsyncClient):
        resp = await client.get("/api/query/history")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_conversations(self, client: AsyncClient):
        resp = await client.get("/api/query/conversations")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_get_conversation_not_found(self, client: AsyncClient):
        resp = await client.get("/api/query/conversations/nonexistent")
        assert resp.status_code in (404, 422)

    @pytest.mark.asyncio
    async def test_ask_requires_body(self, client: AsyncClient):
        resp = await client.post("/api/query")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_export_conversation_not_found(self, client: AsyncClient):
        resp = await client.get("/api/query/conversations/nonexistent/export")
        assert resp.status_code in (404, 422)

    @pytest.mark.asyncio
    async def test_file_back_conversation_not_found(self, client: AsyncClient):
        resp = await client.post("/api/query/conversations/nonexistent/file-back")
        assert resp.status_code in (404, 422)


# ---------------------------------------------------------------------------
# Wiki routes
# ---------------------------------------------------------------------------


class TestWikiRoutes:
    @pytest.mark.asyncio
    async def test_list_articles(self, client: AsyncClient):
        resp = await client.get("/api/wiki/articles")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_article_not_found(self, client: AsyncClient):
        resp = await client.get("/api/wiki/articles/nonexistent-slug")
        assert resp.status_code in (404, 422)

    @pytest.mark.asyncio
    async def test_search_articles(self, client: AsyncClient):
        resp = await client.get("/api/wiki/search", params={"q": "test"})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_graph(self, client: AsyncClient):
        resp = await client.get("/api/wiki/graph")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_random_article_empty(self, client: AsyncClient):
        resp = await client.get("/api/wiki/random")
        assert resp.status_code in (200, 404)

    @pytest.mark.asyncio
    async def test_list_contradiction_resolutions(self, client: AsyncClient):
        resp = await client.get("/api/wiki/contradiction-resolutions")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0

    @pytest.mark.asyncio
    async def test_list_contradictions(self, client: AsyncClient):
        resp = await client.get("/api/wiki/contradictions")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_concepts(self, client: AsyncClient):
        resp = await client.get("/api/wiki/concepts")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_concept_not_found(self, client: AsyncClient):
        resp = await client.get("/api/wiki/concepts/nonexistent-concept")
        assert resp.status_code in (404, 200)

    @pytest.mark.asyncio
    async def test_get_concept_articles(self, client: AsyncClient):
        resp = await client.get("/api/wiki/concepts/test/articles")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_health_no_reports(self, client: AsyncClient):
        """Health endpoint falls back when no lint reports exist."""
        resp = await client.get("/api/wiki/health")
        assert resp.status_code in (200, 404)

    @pytest.mark.asyncio
    async def test_rebuild_concepts(self, client: AsyncClient):
        with patch("wikimind.api.routes.wiki.rebuild_taxonomy", new_callable=AsyncMock):
            resp = await client.post("/api/wiki/concepts/rebuild")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_wikilinks_resolve(self, client: AsyncClient):
        resp = await client.get("/api/wiki/wikilinks/resolve", params={"q": "test"})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_recompile_article_not_found(self, client: AsyncClient):
        mock_bg = MagicMock()
        mock_bg.schedule_recompile = AsyncMock()
        with patch("wikimind.api.routes.wiki.get_background_compiler", return_value=mock_bg):
            resp = await client.post("/api/wiki/articles/nonexistent-id/recompile")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_recompile_invalid_mode(self, client: AsyncClient):
        resp = await client.post(
            "/api/wiki/articles/some-id/recompile",
            params={"mode": "invalid"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Wiki routes with seeded data
# ---------------------------------------------------------------------------


class TestWikiRoutesWithData:
    """Route tests that create data in the database via the same engine as the client."""

    @staticmethod
    async def _seed_article(async_engine, **kwargs):
        from sqlalchemy.ext.asyncio import async_sessionmaker

        factory = async_sessionmaker(async_engine, expire_on_commit=False)
        async with factory() as session:
            art = Article(**kwargs)
            session.add(art)
            await session.commit()
            await session.refresh(art)
            return art

    @pytest.mark.asyncio
    async def test_recompile_existing_article(self, client: AsyncClient, async_engine):
        """Recompile route should create a job and schedule recompile."""
        art = await self._seed_article(
            async_engine,
            slug="recompile-test",
            title="Recompile Test",
            file_path="wiki/recompile-test.md",
            page_type=PageType.SOURCE,
            user_id=ANONYMOUS_USER_ID,
        )

        mock_bg = MagicMock()
        mock_bg.schedule_recompile = AsyncMock()
        with patch("wikimind.api.routes.wiki.get_background_compiler", return_value=mock_bg):
            resp = await client.post(f"/api/wiki/articles/{art.id}/recompile")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "scheduled"
        assert data["job_id"] is not None

    @pytest.mark.asyncio
    async def test_refresh_existing_article(self, client: AsyncClient, async_engine):
        """Refresh route should mark article as still-current."""
        art = await self._seed_article(
            async_engine,
            slug="refresh-test",
            title="Refresh Test",
            file_path="wiki/refresh-test.md",
            page_type=PageType.SOURCE,
            user_id=ANONYMOUS_USER_ID,
        )

        resp = await client.post(f"/api/wiki/articles/{art.slug}/refresh")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "refreshed"

    @pytest.mark.asyncio
    async def test_get_article_tags(self, client: AsyncClient, async_engine):
        """Get tags for an article."""
        art = await self._seed_article(
            async_engine,
            slug="tagged-art",
            title="Tagged Art",
            file_path="wiki/tagged-art.md",
            page_type=PageType.SOURCE,
            user_id=ANONYMOUS_USER_ID,
        )

        resp = await client.get(f"/api/wiki/articles/{art.id}/tags")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_export_existing_article_pdf(self, client: AsyncClient, async_engine):
        """Export an existing article as PDF HTML."""
        art = await self._seed_article(
            async_engine,
            slug="export-test",
            title="Export Test",
            file_path="wiki/export-test.md",
            page_type=PageType.SOURCE,
            user_id=ANONYMOUS_USER_ID,
        )

        with patch(
            "wikimind.api.routes.export.read_article_content",
            new_callable=AsyncMock,
            return_value="# Export Test\n\nContent here.",
        ):
            resp = await client.post(
                f"/api/wiki/articles/{art.slug}/export",
                params={"format": "pdf"},
            )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Export routes
# ---------------------------------------------------------------------------


class TestExportRoutes:
    @pytest.mark.asyncio
    async def test_export_article_not_found(self, client: AsyncClient):
        resp = await client.post(
            "/api/wiki/articles/nonexistent-slug/export",
            params={"format": "pdf"},
        )
        assert resp.status_code == 404
