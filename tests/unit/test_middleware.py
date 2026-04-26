"""Tests for security headers, error handling, and SPA fallback middleware."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.responses import JSONResponse

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


@pytest.mark.asyncio
async def test_error_handling_returns_json_on_404(client):
    """Non-existent routes should still return well-formed responses."""
    response = await client.get("/nonexistent")
    assert response.status_code == 404
    # FastAPI's default 404 is JSON — middleware should not interfere
    assert response.headers["content-type"].startswith("application/json")


# ---------------------------------------------------------------------------
# SPAFallbackMiddleware — unit tests with a minimal FastAPI app
# ---------------------------------------------------------------------------

_INDEX_CONTENT = "<html><body>SPA</body></html>"


@pytest.fixture
def spa_app(tmp_path: Path) -> FastAPI:
    """Minimal FastAPI app with SPAFallbackMiddleware and a /health route."""
    index = tmp_path / "index.html"
    index.write_text(_INDEX_CONTENT)

    inner_app = FastAPI()

    @inner_app.get("/health")
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
    """Browser navigation (Accept: text/html) to /health should return the SPA."""
    resp = await spa_client.get("/health", headers={"Accept": "text/html"})
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "SPA" in resp.text


@pytest.mark.asyncio
async def test_spa_json_request_passes_through(spa_client: AsyncClient):
    """API call (Accept: application/json) to /health should return JSON."""
    resp = await spa_client.get("/health", headers={"Accept": "application/json"})
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
    resp = await spa_client.get("/health")
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
