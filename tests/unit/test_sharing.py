"""Tests for the per-article share link feature and wiki export."""

from __future__ import annotations

import json
import zipfile
from io import BytesIO
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlmodel import select

from wikimind.api.deps import ANONYMOUS_USER_ID
from wikimind.models import Article, ShareLink
from wikimind.services.sharing import SharingService

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_article(db_session, tmp_path: Path, slug: str = "shared-article") -> Article:
    """Create a test article on disk and in the database."""
    wiki_dir = tmp_path / "wikimind" / "wiki"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    md_path = wiki_dir / f"{slug}.md"
    md_path.write_text(
        f"# {slug.replace('-', ' ').title()}\n\n"
        "This is a test article for sharing.\n\n"
        "## Key Points\n\n"
        "- Point one\n"
        "- Point two\n",
        encoding="utf-8",
    )

    article = Article(
        slug=slug,
        title=slug.replace("-", " ").title(),
        file_path=str(md_path),
        summary="A test article.",
        user_id=ANONYMOUS_USER_ID,
    )
    db_session.add(article)
    await db_session.commit()
    await db_session.refresh(article)
    return article


# ---------------------------------------------------------------------------
# Unit tests — SharingService
# ---------------------------------------------------------------------------


class TestSharingServiceUnit:
    @pytest.mark.asyncio
    async def test_create_share_link(self, db_session, tmp_path):
        article = await _seed_article(db_session, tmp_path)
        service = SharingService()

        result = await service.create_share_link(
            db_session,
            article_id=article.id,
            user_id=ANONYMOUS_USER_ID,
        )

        assert result.article_id == article.id
        assert result.token
        assert len(result.token) > 20  # URL-safe base64 of 32 bytes
        assert not result.revoked
        assert result.view_count == 0
        assert result.article_title == article.title

    @pytest.mark.asyncio
    async def test_create_share_link_with_expiry(self, db_session, tmp_path):
        article = await _seed_article(db_session, tmp_path)
        service = SharingService()

        result = await service.create_share_link(
            db_session,
            article_id=article.id,
            user_id=ANONYMOUS_USER_ID,
            expires_in_days=7,
        )

        assert result.expires_at is not None

    @pytest.mark.asyncio
    async def test_create_share_link_article_not_found(self, db_session):
        service = SharingService()

        with pytest.raises(HTTPException, match="Article not found"):
            await service.create_share_link(
                db_session,
                article_id="nonexistent",
                user_id=ANONYMOUS_USER_ID,
            )

    @pytest.mark.asyncio
    async def test_revoke_share_link(self, db_session, tmp_path):
        article = await _seed_article(db_session, tmp_path)
        service = SharingService()

        created = await service.create_share_link(
            db_session,
            article_id=article.id,
            user_id=ANONYMOUS_USER_ID,
        )
        await db_session.commit()

        await service.revoke_share_link(db_session, created.id, ANONYMOUS_USER_ID)
        await db_session.commit()

        # Verify it's revoked
        result = await db_session.execute(select(ShareLink).where(ShareLink.id == created.id))
        link = result.scalar_one()
        assert link.revoked is True

    @pytest.mark.asyncio
    async def test_list_share_links(self, db_session, tmp_path):
        article = await _seed_article(db_session, tmp_path)
        service = SharingService()

        await service.create_share_link(db_session, article_id=article.id, user_id=ANONYMOUS_USER_ID)
        await service.create_share_link(db_session, article_id=article.id, user_id=ANONYMOUS_USER_ID)
        await db_session.commit()

        links = await service.list_share_links(db_session, ANONYMOUS_USER_ID)
        assert len(links) == 2

    @pytest.mark.asyncio
    async def test_list_share_links_filtered_by_article(self, db_session, tmp_path):
        article1 = await _seed_article(db_session, tmp_path, slug="article-one")
        article2 = await _seed_article(db_session, tmp_path, slug="article-two")
        service = SharingService()

        await service.create_share_link(db_session, article_id=article1.id, user_id=ANONYMOUS_USER_ID)
        await service.create_share_link(db_session, article_id=article2.id, user_id=ANONYMOUS_USER_ID)
        await db_session.commit()

        links = await service.list_share_links(db_session, ANONYMOUS_USER_ID, article_id=article1.id)
        assert len(links) == 1
        assert links[0].article_id == article1.id

    @pytest.mark.asyncio
    async def test_get_public_article(self, db_session, tmp_path):
        article = await _seed_article(db_session, tmp_path)
        service = SharingService()

        created = await service.create_share_link(db_session, article_id=article.id, user_id=ANONYMOUS_USER_ID)
        await db_session.commit()

        with patch("wikimind.services.sharing.read_article_content") as mock_read:
            mock_read.return_value = "# Test\n\nContent here."
            public = await service.get_public_article(db_session, created.token)

        assert public.title == article.title
        assert public.content_html
        assert "Content here" in public.content_html

    @pytest.mark.asyncio
    async def test_get_public_article_revoked(self, db_session, tmp_path):
        article = await _seed_article(db_session, tmp_path)
        service = SharingService()

        created = await service.create_share_link(db_session, article_id=article.id, user_id=ANONYMOUS_USER_ID)
        await db_session.commit()

        await service.revoke_share_link(db_session, created.id, ANONYMOUS_USER_ID)
        await db_session.commit()

        with pytest.raises(HTTPException) as exc_info:
            await service.get_public_article(db_session, created.token)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_public_article_invalid_token(self, db_session):
        service = SharingService()

        with pytest.raises(HTTPException) as exc_info:
            await service.get_public_article(db_session, "bogus-token")
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Integration tests — route handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestShareLinkRoutes:
    async def test_create_share_link(self, client, db_session, tmp_path):
        article = await _seed_article(db_session, tmp_path)

        resp = await client.post(
            "/api/wiki/share-links",
            json={"article_id": article.id},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["article_id"] == article.id
        assert data["token"]
        assert data["revoked"] is False

    async def test_list_share_links(self, client, db_session, tmp_path):
        article = await _seed_article(db_session, tmp_path)

        await client.post(
            "/api/wiki/share-links",
            json={"article_id": article.id},
        )

        resp = await client.get("/api/wiki/share-links")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1

    async def test_revoke_share_link(self, client, db_session, tmp_path):
        article = await _seed_article(db_session, tmp_path)

        create_resp = await client.post(
            "/api/wiki/share-links",
            json={"article_id": article.id},
        )
        link_id = create_resp.json()["id"]

        resp = await client.delete(f"/api/wiki/share-links/{link_id}")
        assert resp.status_code == 204

    async def test_public_article_html(self, client, db_session, tmp_path):
        article = await _seed_article(db_session, tmp_path)

        create_resp = await client.post(
            "/api/wiki/share-links",
            json={"article_id": article.id},
        )
        token = create_resp.json()["token"]

        with patch("wikimind.services.sharing.read_article_content") as mock_read:
            mock_read.return_value = "# Test\n\nShared content."
            resp = await client.get(f"/public/articles/{token}")

        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "Shared content" in resp.text
        assert "WikiMind" in resp.text

    async def test_public_article_json(self, client, db_session, tmp_path):
        article = await _seed_article(db_session, tmp_path)

        create_resp = await client.post(
            "/api/wiki/share-links",
            json={"article_id": article.id},
        )
        token = create_resp.json()["token"]

        with patch("wikimind.services.sharing.read_article_content") as mock_read:
            mock_read.return_value = "# Test\n\nShared content."
            resp = await client.get(f"/public/articles/{token}/json")

        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == article.title
        assert "Shared content" in data["content_html"]

    async def test_public_article_revoked_returns_404(self, client, db_session, tmp_path):
        article = await _seed_article(db_session, tmp_path)

        create_resp = await client.post(
            "/api/wiki/share-links",
            json={"article_id": article.id},
        )
        data = create_resp.json()

        await client.delete(f"/api/wiki/share-links/{data['id']}")

        resp = await client.get(f"/public/articles/{data['token']}")
        assert resp.status_code == 404

    async def test_public_article_bad_token_returns_404(self, client):
        resp = await client.get("/public/articles/totally-invalid-token")
        assert resp.status_code == 404

    async def test_create_share_link_article_not_found(self, client):
        resp = await client.post(
            "/api/wiki/share-links",
            json={"article_id": "nonexistent-id"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Wiki export tests
# ---------------------------------------------------------------------------


async def _seed_articles_for_export(db_session, tmp_path: Path) -> list[Article]:
    """Create multiple articles for wiki export testing."""
    articles = []
    for i in range(3):
        slug = f"export-test-{i}"
        wiki_dir = tmp_path / "wikimind" / "wiki"
        wiki_dir.mkdir(parents=True, exist_ok=True)
        md_path = wiki_dir / f"{slug}.md"
        md_path.write_text(
            f"---\ntitle: Article {i}\nslug: {slug}\n---\n\n# Article {i}\n\nContent for article {i}.\n",
            encoding="utf-8",
        )

        article = Article(
            slug=slug,
            title=f"Article {i}",
            file_path=str(md_path),
            summary=f"Summary for article {i}.",
            user_id=ANONYMOUS_USER_ID,
            page_type="source",
        )
        db_session.add(article)
        articles.append(article)

    await db_session.commit()
    for a in articles:
        await db_session.refresh(a)
    return articles


@pytest.mark.asyncio
class TestWikiExportRoutes:
    async def test_export_obsidian_returns_zip(self, client, db_session, tmp_path):
        await _seed_articles_for_export(db_session, tmp_path)

        resp = await client.post("/api/wiki/export/wiki?format=obsidian")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"
        assert "attachment" in resp.headers.get("content-disposition", "")

        zf = zipfile.ZipFile(BytesIO(resp.content))
        names = zf.namelist()
        assert len(names) == 3
        # Each file should have Obsidian frontmatter
        for name in names:
            content = zf.read(name).decode("utf-8")
            assert content.startswith("---")
            assert "title:" in content

    async def test_export_markdown_json_returns_zip(self, client, db_session, tmp_path):
        await _seed_articles_for_export(db_session, tmp_path)

        resp = await client.post("/api/wiki/export/wiki?format=markdown_json")
        assert resp.status_code == 200

        zf = zipfile.ZipFile(BytesIO(resp.content))
        names = zf.namelist()
        assert "metadata.json" in names

        metadata = json.loads(zf.read("metadata.json"))
        assert metadata["format"] == "wikimind-export-v1"
        assert metadata["article_count"] == 3
        assert len(metadata["articles"]) == 3

    async def test_export_empty_wiki(self, client):
        resp = await client.post("/api/wiki/export/wiki?format=obsidian")
        assert resp.status_code == 200
        zf = zipfile.ZipFile(BytesIO(resp.content))
        assert len(zf.namelist()) == 0
