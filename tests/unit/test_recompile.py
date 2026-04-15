"""Tests for the recompile article endpoint (POST /wiki/articles/{id}/recompile)."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.models import Article, PageType, Source, SourceType


async def test_recompile_source_article(client: AsyncClient, db_session: AsyncSession) -> None:
    """POST recompile for a source-type article returns 200 + scheduled."""
    src = Source(source_type=SourceType.TEXT, title="src")
    db_session.add(src)
    await db_session.commit()

    article = Article(
        slug="test-source-article",
        title="Test Source Article",
        file_path="/tmp/test.md",
        page_type=PageType.SOURCE,
        source_ids=json.dumps([src.id]),
    )
    db_session.add(article)
    await db_session.commit()

    with patch("wikimind.api.routes.wiki.get_background_compiler") as mock_bc:
        mock_compiler = mock_bc.return_value
        mock_compiler.schedule_recompile = AsyncMock(return_value="job-1")

        response = await client.post(f"/wiki/articles/{article.id}/recompile")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "scheduled"
    assert "job_id" in data


async def test_recompile_missing_article(client: AsyncClient) -> None:
    """POST recompile for a non-existent article returns 404."""
    fake_id = str(uuid.uuid4())
    response = await client.post(f"/wiki/articles/{fake_id}/recompile")
    assert response.status_code == 404


async def test_recompile_concept_article(client: AsyncClient, db_session: AsyncSession) -> None:
    """POST recompile for a concept-type article returns 200."""
    article = Article(
        slug="test-concept-article",
        title="Test Concept Article",
        file_path="/tmp/concept.md",
        page_type=PageType.CONCEPT,
        concept_ids=json.dumps(["concept-1"]),
    )
    db_session.add(article)
    await db_session.commit()

    with patch("wikimind.api.routes.wiki.get_background_compiler") as mock_bc:
        mock_compiler = mock_bc.return_value
        mock_compiler.schedule_recompile = AsyncMock(return_value="job-1")

        response = await client.post(f"/wiki/articles/{article.id}/recompile")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "scheduled"
    assert "job_id" in data


async def test_recompile_explicit_mode(client: AsyncClient, db_session: AsyncSession) -> None:
    """POST recompile with ?mode=source overrides inferred mode."""
    article = Article(
        slug="test-explicit-mode",
        title="Test Explicit Mode",
        file_path="/tmp/explicit.md",
        page_type=PageType.CONCEPT,
        source_ids=json.dumps(["src-1"]),
    )
    db_session.add(article)
    await db_session.commit()

    with patch("wikimind.api.routes.wiki.get_background_compiler") as mock_bc:
        mock_compiler = mock_bc.return_value
        mock_compiler.schedule_recompile = AsyncMock(return_value="job-1")

        response = await client.post(f"/wiki/articles/{article.id}/recompile?mode=source")

    assert response.status_code == 200
    # Verify the background compiler was called with mode="source"
    mock_compiler.schedule_recompile.assert_awaited_once()
    call_args = mock_compiler.schedule_recompile.call_args
    assert call_args[0][1] == "source"


async def test_recompile_invalid_mode(client: AsyncClient, db_session: AsyncSession) -> None:
    """POST recompile with ?mode=invalid returns 422."""
    article = Article(
        slug="test-invalid-mode",
        title="Test Invalid Mode",
        file_path="/tmp/invalid.md",
        page_type=PageType.SOURCE,
    )
    db_session.add(article)
    await db_session.commit()

    response = await client.post(f"/wiki/articles/{article.id}/recompile?mode=invalid")
    assert response.status_code == 422
