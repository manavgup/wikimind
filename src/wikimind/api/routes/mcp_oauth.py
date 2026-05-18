"""OAuth 2.1 Authorization Server for MCP remote connections.

Implements RFC 8414 (OAuth Authorization Server Metadata), the
authorization code grant with PKCE (RFC 7636), and token revocation
(RFC 7009).  MCP clients (Claude.ai, MCP Inspector) use this flow
to authenticate without manually copying PAT tokens.

Endpoints:
  GET  /.well-known/oauth-authorization-server  — metadata discovery
  GET  /mcp/authorize    — authorization request (browser redirect)
  POST /mcp/token        — exchange authorization code for access token
  POST /mcp/revoke       — revoke an access token

See issue #764.
"""

import base64
import hashlib
import secrets
import uuid
from datetime import timedelta

import structlog
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind._datetime import utcnow_naive
from wikimind.config import get_settings
from wikimind.database import get_session
from wikimind.models import OAuthAccessToken, OAuthAuthorizationCode

log = structlog.get_logger()

# Authorization codes expire after 5 minutes (OAuth 2.1 best practice).
AUTH_CODE_TTL_SECONDS = 300

# Access tokens expire after 1 hour.
ACCESS_TOKEN_TTL_SECONDS = 3600

# Router for /.well-known — mounted at root level in main.py.
metadata_router = APIRouter()

# Router for /mcp/* endpoints — mounted with prefix="/mcp" in main.py.
router = APIRouter()


# ---------------------------------------------------------------------------
# OAuth Metadata (RFC 8414)
# ---------------------------------------------------------------------------


@metadata_router.get("/.well-known/oauth-authorization-server")
async def oauth_metadata() -> JSONResponse:
    """Return OAuth 2.1 Authorization Server Metadata per RFC 8414."""
    settings = get_settings()
    issuer = settings.auth.public_url.rstrip("/") or "http://localhost:7842"
    return JSONResponse(
        content={
            "issuer": issuer,
            "authorization_endpoint": f"{issuer}/mcp/authorize",
            "token_endpoint": f"{issuer}/mcp/token",
            "revocation_endpoint": f"{issuer}/mcp/revoke",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
        }
    )


# ---------------------------------------------------------------------------
# Consent page HTML
# ---------------------------------------------------------------------------


_CONSENT_PAGE_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WikiMind — Authorize Application</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         background: #f8fafc; color: #1e293b; min-height: 100vh;
         display: flex; justify-content: center; align-items: center; }}
  .card {{ background: white; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,.1);
          padding: 32px; max-width: 420px; width: 100%; }}
  h1 {{ font-size: 20px; margin-bottom: 8px; }}
  .subtitle {{ font-size: 13px; color: #64748b; margin-bottom: 24px; }}
  .client-name {{ font-weight: 600; color: #6366f1; }}
  .permissions {{ background: #f1f5f9; border-radius: 8px; padding: 16px; margin: 16px 0; }}
  .permissions h3 {{ font-size: 13px; color: #64748b; margin-bottom: 8px; }}
  .permissions ul {{ list-style: none; padding: 0; }}
  .permissions li {{ font-size: 13px; padding: 4px 0; }}
  .permissions li::before {{ content: "\\2713 "; color: #22c55e; font-weight: bold; }}
  .btn-row {{ display: flex; gap: 8px; margin-top: 20px; }}
  .btn {{ flex: 1; padding: 10px; border: none; border-radius: 6px;
         font-weight: 600; font-size: 13px; cursor: pointer; }}
  .btn-approve {{ background: #6366f1; color: white; }}
  .btn-approve:hover {{ background: #4f46e5; }}
  .btn-deny {{ background: #e2e8f0; color: #475569; }}
  .btn-deny:hover {{ background: #cbd5e1; }}
</style>
</head>
<body>
<div class="card">
  <h1>Authorize Application</h1>
  <p class="subtitle">
    <span class="client-name">{client_id}</span> wants to access your WikiMind knowledge base.
  </p>
  <div class="permissions">
    <h3>This application will be able to:</h3>
    <ul>
      <li>Search your wiki articles</li>
      <li>Read article content</li>
      <li>Ask questions against your wiki</li>
      <li>List your ingested sources</li>
    </ul>
  </div>
  <div class="btn-row">
    <form method="POST" action="/mcp/authorize/decide" style="flex:1;display:flex;">
      <input type="hidden" name="request_id" value="{request_id}">
      <input type="hidden" name="decision" value="deny">
      <button type="submit" class="btn btn-deny" style="flex:1;">Deny</button>
    </form>
    <form method="POST" action="/mcp/authorize/decide" style="flex:1;display:flex;">
      <input type="hidden" name="request_id" value="{request_id}">
      <input type="hidden" name="decision" value="approve">
      <button type="submit" class="btn btn-approve" style="flex:1;">Approve</button>
    </form>
  </div>
</div>
</body>
</html>
"""

_LOGIN_REDIRECT_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WikiMind — Sign In Required</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         background: #f8fafc; color: #1e293b; min-height: 100vh;
         display: flex; justify-content: center; align-items: center; }}
  .card {{ background: white; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,.1);
          padding: 32px; max-width: 420px; width: 100%; text-align: center; }}
  h1 {{ font-size: 20px; margin-bottom: 8px; }}
  .subtitle {{ font-size: 13px; color: #64748b; margin-bottom: 24px; }}
  .btn {{ display: block; width: 100%; padding: 10px; border: none; border-radius: 6px;
         font-weight: 600; font-size: 13px; cursor: pointer; color: white;
         text-decoration: none; margin-bottom: 8px; }}
  .btn-google {{ background: #4285f4; }}
  .btn-google:hover {{ background: #3367d6; }}
  .btn-github {{ background: #374151; }}
  .btn-github:hover {{ background: #1f2937; }}
</style>
</head>
<body>
<div class="card">
  <h1>Sign In Required</h1>
  <p class="subtitle">Sign in to authorize the application.</p>
  <a href="/auth/login/google?next=/mcp/authorize/resume?rid={request_id}" class="btn btn-google">
    Sign in with Google
  </a>
  <a href="/auth/login/github?next=/mcp/authorize/resume?rid={request_id}" class="btn btn-github">
    Sign in with GitHub
  </a>
</div>
</body>
</html>
"""

# In-memory store for pending authorization requests. These are ephemeral
# and short-lived (5 minutes). A database table would survive restarts but
# is unnecessary for authorization requests that expire quickly.
_pending_requests: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Authorization Endpoint
# ---------------------------------------------------------------------------


@router.get("/authorize")
async def authorize(
    request: Request,
    response_type: str | None = None,
    client_id: str | None = None,
    redirect_uri: str | None = None,
    code_challenge: str | None = None,
    code_challenge_method: str | None = None,
    state: str | None = None,
) -> HTMLResponse:
    """OAuth 2.1 authorization endpoint.

    Validates the authorization request parameters, stores them, and
    either shows the consent screen (if logged in) or redirects to login.
    """
    # Validate required parameters
    if response_type != "code":
        raise HTTPException(status_code=400, detail="response_type must be 'code'")
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id is required")
    if not redirect_uri:
        raise HTTPException(status_code=400, detail="redirect_uri is required")
    if not code_challenge:
        raise HTTPException(status_code=400, detail="code_challenge is required (PKCE)")
    if code_challenge_method != "S256":
        raise HTTPException(status_code=400, detail="code_challenge_method must be 'S256'")

    # Store the authorization request
    request_id = str(uuid.uuid4())
    _pending_requests[request_id] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "state": state,
        "created_at": utcnow_naive(),
    }

    # Check if user is authenticated (has session cookie)
    settings = get_settings()
    user_id = _extract_user_id(request, settings)

    if user_id:
        # User is logged in — show consent screen
        return HTMLResponse(
            content=_CONSENT_PAGE_HTML.format(
                client_id=_escape_html(client_id),
                request_id=request_id,
            )
        )

    # Not logged in — show login page
    return HTMLResponse(content=_LOGIN_REDIRECT_HTML.format(request_id=request_id))


@router.get("/authorize/resume")
async def authorize_resume(
    request: Request,
    rid: str,
) -> HTMLResponse:
    """Resume authorization flow after login.

    The user was redirected to login, and after successful login they
    are sent back here. We now show the consent screen.
    """
    pending = _pending_requests.get(rid)
    if not pending:
        raise HTTPException(status_code=400, detail="Authorization request not found or expired")

    # Verify the request hasn't expired (5 minutes)
    age = (utcnow_naive() - pending["created_at"]).total_seconds()
    if age > AUTH_CODE_TTL_SECONDS:
        _pending_requests.pop(rid, None)
        raise HTTPException(status_code=400, detail="Authorization request expired")

    settings = get_settings()
    user_id = _extract_user_id(request, settings)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    return HTMLResponse(
        content=_CONSENT_PAGE_HTML.format(
            client_id=_escape_html(pending["client_id"]),
            request_id=rid,
        )
    )


@router.post("/authorize/decide")
async def authorize_decide(
    request: Request,
    request_id: str = Form(...),
    decision: str = Form(...),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    """Handle consent decision (approve or deny).

    On approval, generates an authorization code, stores it, and
    redirects to the client's redirect_uri with the code and state.
    """
    pending = _pending_requests.pop(request_id, None)
    if not pending:
        raise HTTPException(status_code=400, detail="Authorization request not found or expired")

    # Verify the request hasn't expired
    age = (utcnow_naive() - pending["created_at"]).total_seconds()
    if age > AUTH_CODE_TTL_SECONDS:
        raise HTTPException(status_code=400, detail="Authorization request expired")

    redirect_uri = pending["redirect_uri"]

    if decision != "approve":
        # Denied — redirect with error
        sep = "&" if "?" in redirect_uri else "?"
        deny_url = f"{redirect_uri}{sep}error=access_denied"
        if pending.get("state"):
            deny_url += f"&state={pending['state']}"
        return RedirectResponse(url=deny_url, status_code=302)

    # Get the authenticated user
    settings = get_settings()
    user_id = _extract_user_id(request, settings)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Generate authorization code
    code = secrets.token_urlsafe(32)
    now = utcnow_naive()
    auth_code = OAuthAuthorizationCode(
        code=code,
        user_id=user_id,
        client_id=pending["client_id"],
        redirect_uri=redirect_uri,
        code_challenge=pending["code_challenge"],
        state=pending.get("state"),
        created_at=now,
        expires_at=now + timedelta(seconds=AUTH_CODE_TTL_SECONDS),
    )
    session.add(auth_code)
    await session.commit()

    log.info(
        "oauth_code_issued",
        client_id=pending["client_id"],
        user_id=user_id,
    )

    # Redirect to client with code
    sep = "&" if "?" in redirect_uri else "?"
    approve_url = f"{redirect_uri}{sep}code={code}"
    if pending.get("state"):
        approve_url += f"&state={pending['state']}"

    return RedirectResponse(url=approve_url, status_code=302)


# ---------------------------------------------------------------------------
# Token Endpoint
# ---------------------------------------------------------------------------


def _validate_auth_code(
    auth_code: OAuthAuthorizationCode | None,
    client_id: str,
    redirect_uri: str,
    code_verifier: str,
) -> str | None:
    """Validate an authorization code for token exchange.

    Returns an error description string if validation fails, or None if valid.
    """
    if not auth_code:
        return "Invalid authorization code"

    # Check code state and binding
    checks: list[tuple[bool, str]] = [
        (utcnow_naive() > auth_code.expires_at, "Authorization code expired"),
        (auth_code.used, "Authorization code already used"),
        (auth_code.client_id != client_id, "client_id mismatch"),
        (auth_code.redirect_uri != redirect_uri, "redirect_uri mismatch"),
    ]
    for failed, msg in checks:
        if failed:
            return msg

    # Verify PKCE: S256 — hash the verifier and compare to stored challenge
    verifier_hash = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    )
    if verifier_hash != auth_code.code_challenge:
        return "PKCE verification failed"

    return None


@router.post("/token")
async def token_exchange(
    grant_type: str = Form(...),
    code: str = Form(...),
    redirect_uri: str = Form(...),
    code_verifier: str = Form(...),
    client_id: str = Form(...),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Exchange an authorization code for an access token (PKCE).

    Validates the grant type, code, redirect_uri match, PKCE verifier,
    and that the code hasn't expired or been used. Returns a short-lived
    access token with ``wmk_`` prefix.
    """
    if grant_type != "authorization_code":
        return JSONResponse(
            status_code=400,
            content={"error": "unsupported_grant_type"},
        )

    # Look up and validate the authorization code
    result = await session.exec(select(OAuthAuthorizationCode).where(OAuthAuthorizationCode.code == code))
    auth_code = result.one_or_none()

    error = _validate_auth_code(auth_code, client_id, redirect_uri, code_verifier)
    if error:
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_grant", "error_description": error},
        )
    assert auth_code is not None  # validated above

    # Mark code as used
    auth_code.used = True
    session.add(auth_code)

    # Generate access token with wmk_ prefix
    raw_token = f"wmk_{secrets.token_urlsafe(32)}"
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    now = utcnow_naive()
    access_token = OAuthAccessToken(
        token_hash=token_hash,
        user_id=auth_code.user_id,
        client_id=client_id,
        created_at=now,
        expires_at=now + timedelta(seconds=ACCESS_TOKEN_TTL_SECONDS),
    )
    session.add(access_token)
    await session.commit()

    log.info(
        "oauth_token_issued",
        client_id=client_id,
        user_id=auth_code.user_id,
    )

    return JSONResponse(
        content={
            "access_token": raw_token,
            "token_type": "bearer",
            "expires_in": ACCESS_TOKEN_TTL_SECONDS,
        }
    )


# ---------------------------------------------------------------------------
# Token Revocation (RFC 7009)
# ---------------------------------------------------------------------------


@router.post("/revoke")
async def revoke_token(
    token: str = Form(...),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    """Revoke an access token.

    Per RFC 7009, always returns 200 even if the token is not found.
    """
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    result = await session.exec(select(OAuthAccessToken).where(OAuthAccessToken.token_hash == token_hash))
    access_token = result.one_or_none()

    if access_token:
        access_token.revoked = True
        session.add(access_token)
        await session.commit()
        log.info("oauth_token_revoked", client_id=access_token.client_id)

    # RFC 7009: always return 200
    return JSONResponse(content={})


# ---------------------------------------------------------------------------
# Token validation helper (used by MCP auth)
# ---------------------------------------------------------------------------


async def validate_oauth_token(token: str, session: AsyncSession) -> str | None:
    """Validate an OAuth access token and return the user_id if valid.

    Returns None if the token is invalid, expired, or revoked.
    """
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    result = await session.exec(select(OAuthAccessToken).where(OAuthAccessToken.token_hash == token_hash))
    access_token = result.one_or_none()

    if not access_token:
        return None
    if access_token.revoked:
        return None
    if utcnow_naive() > access_token.expires_at:
        return None

    return access_token.user_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_user_id(request: Request, settings) -> str | None:
    """Extract user_id from the session cookie JWT, if present.

    Returns None if not authenticated. Does not raise.
    """
    import jwt  # noqa: PLC0415 — deferred to keep module-level imports clean

    # In dev mode with auto-auth, the middleware sets request.state.user_id
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return user_id

    token = request.cookies.get(settings.auth.cookie_name, "")
    if not token:
        return None

    try:
        payload = jwt.decode(
            token,
            settings.auth.jwt_secret_key,
            algorithms=[settings.auth.jwt_algorithm],
            options={"verify_aud": False},
        )
        return payload.get("sub")
    except jwt.InvalidTokenError:
        return None


def _escape_html(text: str) -> str:
    """Escape HTML special characters to prevent XSS in the consent page."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )
