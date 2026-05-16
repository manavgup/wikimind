"""Tests for the article export service and route."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import TEST_USER_ID
from wikimind.models import (
    Article,
    CompletionResponse,
    Provider,
)
from wikimind.services.export import (
    ExportService,
    _inline_format,
    _markdown_to_html,
    _sanitize_url,
)

# ---------------------------------------------------------------------------
# Unit tests — ExportService (no DB, no LLM)
# ---------------------------------------------------------------------------


class TestMarkdownToHtml:
    def test_heading_levels(self):
        md = "# H1\n## H2\n### H3\n#### H4"
        html = _markdown_to_html(md)
        assert "<h1>H1</h1>" in html
        assert "<h2>H2</h2>" in html
        assert "<h3>H3</h3>" in html
        assert "<h4>H4</h4>" in html

    def test_bold_and_italic(self):
        md = "This is **bold** and *italic* text."
        html = _markdown_to_html(md)
        assert "<strong>bold</strong>" in html
        assert "<em>italic</em>" in html

    def test_inline_code(self):
        md = "Use `pip install` to install."
        html = _markdown_to_html(md)
        assert "<code>pip install</code>" in html

    def test_code_block(self):
        md = "```\nprint('hello')\n```"
        html = _markdown_to_html(md)
        assert "<pre><code>" in html
        assert "print(&#x27;hello&#x27;)" in html or "print(" in html
        assert "</code></pre>" in html

    def test_unordered_list(self):
        md = "- item one\n- item two\n- item three"
        html = _markdown_to_html(md)
        assert "<ul>" in html
        assert "<li>item one</li>" in html
        assert "<li>item two</li>" in html
        assert "</ul>" in html

    def test_ordered_list(self):
        md = "1. first\n2. second"
        html = _markdown_to_html(md)
        assert "<ol>" in html
        assert "<li>first</li>" in html
        assert "</ol>" in html

    def test_blockquote(self):
        md = "> This is a quote."
        html = _markdown_to_html(md)
        assert "<blockquote>This is a quote.</blockquote>" in html

    def test_horizontal_rule(self):
        md = "---"
        html = _markdown_to_html(md)
        assert "<hr>" in html

    def test_paragraph(self):
        md = "Just a normal paragraph."
        html = _markdown_to_html(md)
        assert "<p>Just a normal paragraph.</p>" in html

    def test_link(self):
        md = "Visit [Google](https://google.com) today."
        html = _markdown_to_html(md)
        assert '<a href="https://google.com">Google</a>' in html

    def test_html_escaping(self):
        md = "Use <script> tags & stuff."
        html = _markdown_to_html(md)
        assert "&lt;script&gt;" in html
        assert "&amp;" in html


class TestInlineFormat:
    def test_escapes_html_first(self):
        result = _inline_format("a < b & c > d")
        assert "&lt;" in result
        assert "&amp;" in result
        assert "&gt;" in result


class TestSanitizeUrl:
    """URL scheme validation for XSS prevention."""

    def test_allows_http(self):
        assert _sanitize_url("http://example.com") == "http://example.com"

    def test_allows_https(self):
        assert _sanitize_url("https://example.com") == "https://example.com"

    def test_allows_mailto(self):
        assert _sanitize_url("mailto:user@example.com") == "mailto:user@example.com"

    def test_blocks_javascript(self):
        assert _sanitize_url("javascript:alert(1)") is None

    def test_blocks_javascript_mixed_case(self):
        assert _sanitize_url("JaVaScRiPt:alert(1)") is None

    def test_blocks_data_url(self):
        assert _sanitize_url("data:text/html,<script>alert(1)</script>") is None

    def test_blocks_vbscript(self):
        assert _sanitize_url("vbscript:MsgBox('XSS')") is None

    def test_blocks_javascript_with_whitespace_bypass(self):
        assert _sanitize_url(" \t\njavascript:alert(1)") is None

    def test_blocks_javascript_with_control_chars(self):
        assert _sanitize_url("\x00javascript:alert(1)") is None

    def test_blocks_bare_path(self):
        assert _sanitize_url("/etc/passwd") is None

    def test_blocks_empty_string(self):
        assert _sanitize_url("") is None


class TestLinkSanitization:
    """Verify that _inline_format and _markdown_to_html strip dangerous URLs."""

    def test_inline_format_blocks_javascript_link(self):
        result = _inline_format("[click](javascript:alert(1))")
        assert "javascript:" not in result
        assert "<a" not in result
        assert "click" in result

    def test_inline_format_allows_https_link(self):
        result = _inline_format("[Google](https://google.com)")
        assert '<a href="https://google.com">Google</a>' in result

    def test_inline_format_allows_mailto_link(self):
        result = _inline_format("[Email](mailto:user@example.com)")
        assert '<a href="mailto:user@example.com">Email</a>' in result

    def test_inline_format_blocks_mixed_case_javascript(self):
        result = _inline_format("[xss](JaVaScRiPt:alert(document.cookie))")
        assert "javascript:" not in result.lower()
        assert "<a" not in result

    def test_inline_format_blocks_data_url(self):
        result = _inline_format("[xss](data:text/html,<script>alert(1)</script>)")
        assert "<a" not in result

    def test_markdown_to_html_blocks_javascript_link(self):
        html = _markdown_to_html("[click me](javascript:alert('XSS'))")
        assert "javascript:" not in html
        assert "<a" not in html
        assert "click me" in html

    def test_markdown_to_html_allows_safe_link(self):
        html = _markdown_to_html("[safe](https://safe.example.com)")
        assert '<a href="https://safe.example.com">safe</a>' in html


class TestExportServicePdf:
    def test_export_pdf_html_returns_complete_document(self):
        service = ExportService(llm_router=MagicMock())
        html = service.export_pdf_html("Test Title", "# Hello\n\nWorld")
        assert "<!DOCTYPE html>" in html
        assert "<title>Test Title</title>" in html
        assert "<h1>Hello</h1>" in html
        assert "<p>World</p>" in html

    def test_export_pdf_html_escapes_title(self):
        service = ExportService(llm_router=MagicMock())
        html = service.export_pdf_html("Title & <Special>", "content")
        assert "Title &amp; &lt;Special&gt;" in html


class TestExportServiceLinkedin:
    @pytest.mark.asyncio
    async def test_export_linkedin_calls_llm(self):
        mock_router = MagicMock()
        mock_response = CompletionResponse(
            content="Hook line!\n\nInsight here.\n\nWhat do you think?",
            provider_used=Provider.MOCK,
            model_used="mock",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.0,
            latency_ms=100,
        )
        mock_router.complete = AsyncMock(return_value=mock_response)

        service = ExportService(llm_router=mock_router)
        result = await service.export_linkedin("Test Article", "# Content\n\nBody text.", user_id=TEST_USER_ID)

        assert result == "Hook line!\n\nInsight here.\n\nWhat do you think?"
        mock_router.complete.assert_called_once()
        call_args = mock_router.complete.call_args[0][0]
        assert call_args.task_type == "export"
        assert call_args.response_format == "text"


class TestExportServiceSlides:
    @pytest.mark.asyncio
    async def test_export_slides_calls_llm(self):
        mock_router = MagicMock()
        marp_content = "---\nmarp: true\n---\n# Title\n---\n## Slide 1\n- Point"
        mock_response = CompletionResponse(
            content=marp_content,
            provider_used=Provider.MOCK,
            model_used="mock",
            input_tokens=100,
            output_tokens=80,
            cost_usd=0.0,
            latency_ms=150,
        )
        mock_router.complete = AsyncMock(return_value=mock_response)

        service = ExportService(llm_router=mock_router)
        result = await service.export_slides("Test Article", "# Content\n\nBody text.", user_id=TEST_USER_ID)

        assert "marp: true" in result
        mock_router.complete.assert_called_once()
        call_args = mock_router.complete.call_args[0][0]
        assert call_args.task_type == "export"


# ---------------------------------------------------------------------------
# Integration tests — route handler (uses test client + in-memory DB)
# ---------------------------------------------------------------------------


async def _seed_article(db_session, tmp_path: Path) -> Article:
    """Create an article on disk and in the database."""
    from wikimind.config import get_settings as _gs

    wiki_dir = Path(_gs().data_dir) / "wiki" / TEST_USER_ID
    wiki_dir.mkdir(parents=True, exist_ok=True)
    (wiki_dir / "test-export.md").write_text(
        "# Test Export Article\n\n"
        "This article covers AI agents and their architecture.\n\n"
        "## Key Points\n\n"
        "- Agents use tools to interact with the world.\n"
        "- LLMs provide reasoning capabilities.\n",
        encoding="utf-8",
    )

    article = Article(
        slug="test-export",
        title="Test Export Article",
        file_path="test-export.md",
        summary="An article about AI agents.",
        user_id=TEST_USER_ID,
    )
    db_session.add(article)
    await db_session.commit()
    await db_session.refresh(article)
    return article


@pytest.mark.asyncio
class TestExportRoute:
    async def test_export_pdf_returns_html(self, client, db_session, tmp_path):
        article = await _seed_article(db_session, tmp_path)
        resp = await client.post(
            f"/api/wiki/articles/{article.slug}/export?format=pdf",
        )
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "<!DOCTYPE html>" in resp.text
        assert "Test Export Article" in resp.text

    async def test_export_pdf_by_id(self, client, db_session, tmp_path):
        article = await _seed_article(db_session, tmp_path)
        resp = await client.post(
            f"/api/wiki/articles/{article.id}/export?format=pdf",
        )
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    async def test_export_linkedin_returns_json(self, client, db_session, tmp_path):
        article = await _seed_article(db_session, tmp_path)

        with patch(
            "wikimind.services.export.ExportService.export_linkedin",
            new_callable=AsyncMock,
            return_value="Great hook!\n\nInsight paragraph.\n\nWhat are your thoughts?",
        ):
            resp = await client.post(
                f"/api/wiki/articles/{article.slug}/export?format=linkedin",
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["format"] == "linkedin"
        assert data["article_id"] == article.id
        assert "Great hook!" in data["content"]

    async def test_export_slides_returns_json(self, client, db_session, tmp_path):
        article = await _seed_article(db_session, tmp_path)

        with patch(
            "wikimind.services.export.ExportService.export_slides",
            new_callable=AsyncMock,
            return_value="---\nmarp: true\n---\n# Slides",
        ):
            resp = await client.post(
                f"/api/wiki/articles/{article.slug}/export?format=slides",
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["format"] == "slides"
        assert "marp: true" in data["content"]

    async def test_export_article_not_found(self, client):
        resp = await client.post(
            "/api/wiki/articles/nonexistent-slug/export?format=pdf",
        )
        assert resp.status_code == 404

    async def test_export_invalid_format(self, client, db_session, tmp_path):
        article = await _seed_article(db_session, tmp_path)
        resp = await client.post(
            f"/api/wiki/articles/{article.slug}/export?format=docx",
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Single-article download endpoint (GET)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestArticleDownloadRoute:
    async def test_download_markdown_returns_md_file(self, client, db_session, tmp_path):
        article = await _seed_article(db_session, tmp_path)
        resp = await client.get(
            f"/api/wiki/articles/{article.slug}/export?format=markdown",
        )
        assert resp.status_code == 200
        assert "text/markdown" in resp.headers["content-type"]
        assert "attachment" in resp.headers["content-disposition"]
        assert "test-export.md" in resp.headers["content-disposition"]
        assert "# Test Export Article" in resp.text

    async def test_download_markdown_by_id(self, client, db_session, tmp_path):
        article = await _seed_article(db_session, tmp_path)
        resp = await client.get(
            f"/api/wiki/articles/{article.id}/export?format=markdown",
        )
        assert resp.status_code == 200
        assert "text/markdown" in resp.headers["content-type"]
        assert "test-export.md" in resp.headers["content-disposition"]

    async def test_download_json_returns_structured_data(self, client, db_session, tmp_path):
        article = await _seed_article(db_session, tmp_path)
        resp = await client.get(
            f"/api/wiki/articles/{article.slug}/export?format=json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == article.id
        assert data["slug"] == "test-export"
        assert data["title"] == "Test Export Article"
        assert data["summary"] == "An article about AI agents."
        assert "# Test Export Article" in data["content"]
        assert data["page_type"] == "source"
        assert isinstance(data["concepts"], list)
        assert isinstance(data["sources"], list)
        assert "created_at" in data
        assert "updated_at" in data

    async def test_download_article_not_found(self, client):
        resp = await client.get(
            "/api/wiki/articles/nonexistent-slug/export?format=markdown",
        )
        assert resp.status_code == 404

    async def test_download_invalid_format(self, client, db_session, tmp_path):
        article = await _seed_article(db_session, tmp_path)
        resp = await client.get(
            f"/api/wiki/articles/{article.slug}/export?format=docx",
        )
        assert resp.status_code == 422
