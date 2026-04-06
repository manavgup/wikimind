"""Tests for security headers and error handling middleware."""

import pytest


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
