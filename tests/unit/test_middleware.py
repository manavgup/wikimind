"""Tests for security headers, error handling, and SPA fallback middleware."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.responses import JSONResponse

from wikimind.config import get_settings
from wikimind.main import SPAFallbackMiddleware


@pytest.mark.asyncio
async def test_security_headers_present(client):
    """Security headers should appear on every HTTP response."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-XSS-Protection"] == "1; mode=block"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "Content-Security-Policy" in response.headers
    csp = response.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp


@pytest.mark.asyncio
async def test_hsts_present_in_production(client, monkeypatch):
    """HSTS header should be present when not in development mode."""
    settings = get_settings()
    monkeypatch.setattr(settings, "env", "production")
    response = await client.get("/health")
    assert response.status_code == 200
    assert "Strict-Transport-Security" in response.headers
    hsts = response.headers["Strict-Transport-Security"]
    assert "max-age=63072000" in hsts
    assert "includeSubDomains" in hsts


@pytest.mark.asyncio
async def test_hsts_absent_in_development(client, monkeypatch):
    """HSTS header should be omitted in development mode to avoid breaking local HTTP."""
    settings = get_settings()
    monkeypatch.setattr(settings, "env", "development")
    response = await client.get("/health")
    assert response.status_code == 200
    assert "Strict-Transport-Security" not in response.headers


@pytest.mark.asyncio
async def test_error_handling_returns_json_on_404(client):
    """Known API routes with invalid sub-paths return JSON error responses."""
    # In dev mode, auth auto-passes and SPA catch-all serves unknown paths.
    # Test a known API prefix with an invalid method to trigger a real error.
    response = await client.delete("/api/wiki/articles")
    assert response.status_code == 405
    assert response.headers["content-type"].startswith("application/json")


# ---------------------------------------------------------------------------
# SPAFallbackMiddleware — unit tests with a minimal FastAPI app
# ---------------------------------------------------------------------------

_INDEX_CONTENT = "<html><body>SPA</body></html>"


@pytest.fixture
def spa_app(tmp_path: Path) -> FastAPI:
    """Minimal FastAPI app with SPAFallbackMiddleware and a test route."""
    index = tmp_path / "index.html"
    index.write_text(_INDEX_CONTENT)

    inner_app = FastAPI()

    @inner_app.get("/test-health")
    async def health():
        return JSONResponse({"status": "ok"})

    @inner_app.get("/settings")
    async def settings():
        return JSONResponse({"llm": "mock"})

    inner_app.add_middleware(SPAFallbackMiddleware, static_dir=tmp_path)
    return inner_app


@pytest.fixture
async def spa_client(spa_app: FastAPI):
    """Async test client for the minimal SPA app."""
    transport = ASGITransport(app=spa_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_spa_html_request_serves_index(spa_client: AsyncClient):
    """Browser navigation (Accept: text/html) to a known route should return the SPA."""
    resp = await spa_client.get("/test-health", headers={"Accept": "text/html"})
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "SPA" in resp.text


@pytest.mark.asyncio
async def test_spa_json_request_passes_through(spa_client: AsyncClient):
    """API call (Accept: application/json) to a known route should return JSON."""
    resp = await spa_client.get("/test-health", headers={"Accept": "application/json"})
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_spa_settings_html_serves_index(spa_client: AsyncClient):
    """Browser navigation to /settings should return the SPA."""
    resp = await spa_client.get("/settings", headers={"Accept": "text/html"})
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "SPA" in resp.text


@pytest.mark.asyncio
async def test_spa_settings_json_passes_through(spa_client: AsyncClient):
    """API call to /settings should return JSON."""
    resp = await spa_client.get("/settings", headers={"Accept": "application/json"})
    assert resp.status_code == 200
    assert resp.json() == {"llm": "mock"}


@pytest.mark.asyncio
async def test_spa_no_accept_header_passes_through(spa_client: AsyncClient):
    """Request with no Accept header should reach the API handler."""
    resp = await spa_client.get("/test-health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_spa_api_prefix_not_intercepted(spa_client: AsyncClient):
    """Paths under /api/ should never be intercepted by the SPA middleware."""
    resp = await spa_client.get("/api/anything", headers={"Accept": "text/html"})
    # No route registered at /api/anything, so FastAPI returns 404
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_spa_auth_prefix_not_intercepted(spa_client: AsyncClient):
    """Paths under /auth/ should pass through to FastAPI."""
    resp = await spa_client.get("/auth/login", headers={"Accept": "text/html"})
    assert resp.status_code == 404  # no route registered, but not intercepted


@pytest.mark.asyncio
async def test_spa_docs_not_intercepted(spa_client: AsyncClient):
    """The /docs path should pass through to FastAPI's built-in docs."""
    resp = await spa_client.get("/docs", headers={"Accept": "text/html"})
    # FastAPI serves its own HTML at /docs
    assert resp.status_code == 200
    assert "swagger" in resp.text.lower() or "openapi" in resp.text.lower()
