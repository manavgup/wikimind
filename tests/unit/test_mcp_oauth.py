"""Tests for MCP OAuth 2.1 Authorization Server (issue #764).

Covers:
- OAuth metadata endpoint (RFC 8414)
- Authorization flow (request -> consent -> code -> redirect)
- Token exchange with PKCE verification
- Token revocation (RFC 7009)
- Expired authorization codes
- Invalid PKCE verifier
- OAuth access token validation for MCP
"""

import base64
import hashlib
import secrets
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind._datetime import utcnow_naive
from wikimind.api.routes.mcp_oauth import _pending_requests
from wikimind.models import OAuthAccessToken, OAuthAuthorizationCode


def _make_pkce_pair() -> tuple[str, str]:
    """Generate a PKCE code_verifier and its S256 code_challenge."""
    verifier = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


# ---------------------------------------------------------------------------
# OAuth Metadata
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_oauth_metadata_returns_valid_config(client: AsyncClient) -> None:
    """GET /.well-known/oauth-authorization-server returns RFC 8414 metadata."""
    resp = await client.get(
        "/.well-known/oauth-authorization-server",
        headers={"Accept": "application/json"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["response_types_supported"] == ["code"]
    assert data["grant_types_supported"] == ["authorization_code"]
    assert data["code_challenge_methods_supported"] == ["S256"]
    assert data["token_endpoint_auth_methods_supported"] == ["none"]
    assert "/mcp/authorize" in data["authorization_endpoint"]
    assert "/mcp/token" in data["token_endpoint"]
    assert "/mcp/revoke" in data["revocation_endpoint"]


# ---------------------------------------------------------------------------
# Authorization Flow
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_authorize_requires_response_type_code(client: AsyncClient) -> None:
    """GET /mcp/authorize with missing response_type returns 400."""
    resp = await client.get(
        "/mcp/authorize",
        params={"client_id": "test", "redirect_uri": "http://localhost/cb"},
        headers={"Accept": "application/json"},
    )
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_authorize_requires_pkce(client: AsyncClient) -> None:
    """GET /mcp/authorize without code_challenge returns 400."""
    resp = await client.get(
        "/mcp/authorize",
        params={
            "response_type": "code",
            "client_id": "test",
            "redirect_uri": "http://localhost/cb",
        },
        headers={"Accept": "application/json"},
    )
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_authorize_shows_consent_page_when_authenticated(
    client: AsyncClient,
) -> None:
    """GET /mcp/authorize shows consent page for authenticated user (dev mode)."""
    _, challenge = _make_pkce_pair()
    resp = await client.get(
        "/mcp/authorize",
        params={
            "response_type": "code",
            "client_id": "test-mcp-client",
            "redirect_uri": "http://localhost:9999/callback",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "abc123",
        },
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    body = resp.text
    assert "test-mcp-client" in body
    assert "Authorize Application" in body
    assert "Approve" in body
    assert "Deny" in body


# ---------------------------------------------------------------------------
# Full Authorization + Token Exchange
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_full_oauth_flow_with_pkce(client: AsyncClient) -> None:
    """Full flow: authorize -> approve -> token exchange with valid PKCE."""
    verifier, challenge = _make_pkce_pair()
    redirect_uri = "http://localhost:9999/callback"
    client_id = "test-mcp-client"
    state = "test-state-123"

    # Step 1: Start authorization
    resp = await client.get(
        "/mcp/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
        },
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert resp.status_code == 200

    # Extract the request_id from the consent page
    body = resp.text
    import re

    match = re.search(r'name="request_id" value="([^"]+)"', body)
    assert match, "Could not find request_id in consent page"
    request_id = match.group(1)

    # Step 2: Approve
    resp = await client.post(
        "/mcp/authorize/decide",
        data={"request_id": request_id, "decision": "approve"},
        headers={"Accept": "text/html", "Content-Type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert location.startswith(redirect_uri)
    assert f"state={state}" in location

    # Extract the authorization code from the redirect
    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(location)
    params = parse_qs(parsed.query)
    assert "code" in params
    code = params["code"][0]

    # Step 3: Exchange code for token
    resp = await client.post(
        "/mcp/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
            "client_id": client_id,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200
    token_data = resp.json()
    assert token_data["token_type"] == "bearer"
    assert token_data["expires_in"] == 3600
    assert token_data["access_token"].startswith("wmk_")


@pytest.mark.anyio
async def test_deny_redirects_with_error(client: AsyncClient) -> None:
    """Denying authorization redirects with error=access_denied."""
    _, challenge = _make_pkce_pair()
    redirect_uri = "http://localhost:9999/callback"

    # Start authorization
    resp = await client.get(
        "/mcp/authorize",
        params={
            "response_type": "code",
            "client_id": "test-client",
            "redirect_uri": redirect_uri,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "s1",
        },
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    import re

    match = re.search(r'name="request_id" value="([^"]+)"', resp.text)
    assert match
    request_id = match.group(1)

    # Deny
    resp = await client.post(
        "/mcp/authorize/decide",
        data={"request_id": request_id, "decision": "deny"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert "error=access_denied" in location
    assert "state=s1" in location


# ---------------------------------------------------------------------------
# Token Exchange Error Cases
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_token_exchange_invalid_grant_type(client: AsyncClient) -> None:
    """POST /mcp/token with unsupported grant_type returns error."""
    resp = await client.post(
        "/mcp/token",
        data={
            "grant_type": "client_credentials",
            "code": "fake",
            "redirect_uri": "http://localhost/cb",
            "code_verifier": "fake",
            "client_id": "test",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "unsupported_grant_type"


@pytest.mark.anyio
async def test_token_exchange_invalid_code(client: AsyncClient) -> None:
    """POST /mcp/token with non-existent code returns error."""
    resp = await client.post(
        "/mcp/token",
        data={
            "grant_type": "authorization_code",
            "code": "nonexistent-code",
            "redirect_uri": "http://localhost/cb",
            "code_verifier": "fake",
            "client_id": "test",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_grant"


@pytest.mark.anyio
async def test_token_exchange_wrong_pkce_verifier(client: AsyncClient) -> None:
    """POST /mcp/token with incorrect PKCE verifier returns error."""
    verifier, challenge = _make_pkce_pair()
    redirect_uri = "http://localhost:9999/callback"
    client_id = "test-client"

    # Get a valid authorization code
    resp = await client.get(
        "/mcp/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    import re

    match = re.search(r'name="request_id" value="([^"]+)"', resp.text)
    assert match
    request_id = match.group(1)

    resp = await client.post(
        "/mcp/authorize/decide",
        data={"request_id": request_id, "decision": "approve"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    from urllib.parse import parse_qs, urlparse

    code = parse_qs(urlparse(resp.headers["location"]).query)["code"][0]

    # Try to exchange with wrong verifier
    resp = await client.post(
        "/mcp/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": "wrong-verifier-value",
            "client_id": client_id,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 400
    data = resp.json()
    assert data["error"] == "invalid_grant"
    assert "PKCE" in data["error_description"]


@pytest.mark.anyio
async def test_token_exchange_code_already_used(client: AsyncClient) -> None:
    """POST /mcp/token with already-used code returns error."""
    verifier, challenge = _make_pkce_pair()
    redirect_uri = "http://localhost:9999/callback"
    client_id = "test-client"

    # Get authorization code
    resp = await client.get(
        "/mcp/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    import re

    match = re.search(r'name="request_id" value="([^"]+)"', resp.text)
    assert match
    request_id = match.group(1)

    resp = await client.post(
        "/mcp/authorize/decide",
        data={"request_id": request_id, "decision": "approve"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    from urllib.parse import parse_qs, urlparse

    code = parse_qs(urlparse(resp.headers["location"]).query)["code"][0]

    # First exchange — should succeed
    token_params = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
        "client_id": client_id,
    }
    resp1 = await client.post(
        "/mcp/token",
        data=token_params,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp1.status_code == 200

    # Second exchange — should fail (code already used)
    resp2 = await client.post(
        "/mcp/token",
        data=token_params,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp2.status_code == 400
    assert resp2.json()["error"] == "invalid_grant"
    assert "already used" in resp2.json()["error_description"]


# ---------------------------------------------------------------------------
# Expired Authorization Code
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_expired_authorization_code_rejected(
    db_session: AsyncSession,
    client: AsyncClient,
) -> None:
    """Token exchange rejects an expired authorization code."""
    verifier, challenge = _make_pkce_pair()
    now = utcnow_naive()

    # Insert an expired code directly
    expired_code = OAuthAuthorizationCode(
        code="expired-code-123",
        user_id="test-user",
        client_id="test-client",
        redirect_uri="http://localhost/cb",
        code_challenge=challenge,
        created_at=now - timedelta(minutes=10),
        expires_at=now - timedelta(minutes=5),
    )
    db_session.add(expired_code)
    await db_session.commit()

    resp = await client.post(
        "/mcp/token",
        data={
            "grant_type": "authorization_code",
            "code": "expired-code-123",
            "redirect_uri": "http://localhost/cb",
            "code_verifier": verifier,
            "client_id": "test-client",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 400
    assert "expired" in resp.json()["error_description"].lower()


# ---------------------------------------------------------------------------
# Token Revocation
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_token_revocation(client: AsyncClient) -> None:
    """POST /mcp/revoke revokes a valid access token."""
    verifier, challenge = _make_pkce_pair()
    redirect_uri = "http://localhost:9999/callback"
    client_id = "test-client"

    # Get a valid access token through the full flow
    resp = await client.get(
        "/mcp/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    import re

    match = re.search(r'name="request_id" value="([^"]+)"', resp.text)
    assert match
    request_id = match.group(1)

    resp = await client.post(
        "/mcp/authorize/decide",
        data={"request_id": request_id, "decision": "approve"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )
    from urllib.parse import parse_qs, urlparse

    code = parse_qs(urlparse(resp.headers["location"]).query)["code"][0]

    resp = await client.post(
        "/mcp/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
            "client_id": client_id,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    access_token = resp.json()["access_token"]

    # Revoke the token
    resp = await client.post(
        "/mcp/revoke",
        data={"token": access_token},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_revoke_unknown_token_returns_200(client: AsyncClient) -> None:
    """POST /mcp/revoke with unknown token still returns 200 (RFC 7009)."""
    resp = await client.post(
        "/mcp/revoke",
        data={"token": "wmk_nonexistent_token"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# MCP Token Validation
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_validate_mcp_token_valid(db_session: AsyncSession) -> None:
    """validate_mcp_token returns user_id for a valid OAuth token."""
    from wikimind.mcp.auth import validate_mcp_token

    raw_token = f"wmk_{secrets.token_urlsafe(32)}"
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    now = utcnow_naive()

    access_token = OAuthAccessToken(
        token_hash=token_hash,
        user_id="test-user",
        client_id="test-client",
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )
    db_session.add(access_token)
    await db_session.commit()

    user_id = await validate_mcp_token(raw_token, db_session)
    assert user_id == "test-user"


@pytest.mark.anyio
async def test_validate_mcp_token_revoked(db_session: AsyncSession) -> None:
    """validate_mcp_token returns None for a revoked token."""
    from wikimind.mcp.auth import validate_mcp_token

    raw_token = f"wmk_{secrets.token_urlsafe(32)}"
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    now = utcnow_naive()

    access_token = OAuthAccessToken(
        token_hash=token_hash,
        user_id="test-user",
        client_id="test-client",
        created_at=now,
        expires_at=now + timedelta(hours=1),
        revoked=True,
    )
    db_session.add(access_token)
    await db_session.commit()

    user_id = await validate_mcp_token(raw_token, db_session)
    assert user_id is None


@pytest.mark.anyio
async def test_validate_mcp_token_expired(db_session: AsyncSession) -> None:
    """validate_mcp_token returns None for an expired token."""
    from wikimind.mcp.auth import validate_mcp_token

    raw_token = f"wmk_{secrets.token_urlsafe(32)}"
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    now = utcnow_naive()

    access_token = OAuthAccessToken(
        token_hash=token_hash,
        user_id="test-user",
        client_id="test-client",
        created_at=now - timedelta(hours=2),
        expires_at=now - timedelta(hours=1),
    )
    db_session.add(access_token)
    await db_session.commit()

    user_id = await validate_mcp_token(raw_token, db_session)
    assert user_id is None


@pytest.mark.anyio
async def test_validate_mcp_token_wrong_prefix(db_session: AsyncSession) -> None:
    """validate_mcp_token returns None for tokens without wmk_ prefix."""
    from wikimind.mcp.auth import validate_mcp_token

    user_id = await validate_mcp_token("not_a_wmk_token", db_session)
    assert user_id is None


@pytest.fixture(autouse=True)
def _clear_pending_requests():
    """Clear the in-memory pending requests between tests."""
    _pending_requests.clear()
    yield
    _pending_requests.clear()
