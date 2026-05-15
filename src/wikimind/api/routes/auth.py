"""OAuth2 authentication routes — Google/GitHub login and magic link (passwordless email).

Thin route handlers that delegate to :class:`UserService` for all
business logic (token exchange, user upsert, JWT creation, magic link
token creation/verification, account deletion). The JWT is stored in
an HttpOnly cookie.

OAuth state tokens are HMAC-signed stateless values encoding
``provider:timestamp``, signed with the JWT secret key. On callback
the signature is verified and the timestamp checked against the
configured TTL. No shared server-side state is needed, so
multi-worker deployments work without coordination.
"""

import base64
import binascii
import hashlib
import hmac
import time
import uuid
from datetime import UTC, datetime, timedelta

import jwt as pyjwt
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.api.deps import ANONYMOUS_USER_ID, require_user_id
from wikimind.config import get_settings
from wikimind.database import get_session
from wikimind.models import (
    DeleteAccountResponse,
    MagicLinkRequest,
    MagicLinkResponse,
    MagicLinkVerifyRequest,
    MagicLinkVerifyResponse,
    TokenCreateRequest,
    TokenCreateResponse,
    UserProfileResponse,
)
from wikimind.services.user import UserService, get_user_service

log = structlog.get_logger()

router = APIRouter()


def _generate_oauth_state(provider: str) -> str:
    """Create an HMAC-signed stateless state token.

    The token encodes ``provider:timestamp`` and is signed with the JWT
    secret key. The result is base64url-encoded so it is URL-safe.
    """
    settings = get_settings()
    payload = f"{provider}:{int(time.time())}"
    sig = hmac.new(settings.auth.jwt_secret_key.encode(), payload.encode(), hashlib.sha384).hexdigest()
    raw = f"{payload}:{sig}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _consume_oauth_state(state: str) -> str | None:
    """Verify an HMAC-signed state token and return the provider.

    Returns the provider name if the signature is valid and the
    timestamp is within the configured TTL, or ``None`` otherwise.
    """
    settings = get_settings()
    try:
        raw = base64.urlsafe_b64decode(state.encode()).decode()
    except (ValueError, binascii.Error):
        return None

    parts = raw.rsplit(":", 2)
    if len(parts) != 3:
        return None

    provider, ts_str, sig = parts
    try:
        ts = int(ts_str)
    except ValueError:
        return None

    expected_payload = f"{provider}:{ts_str}"
    expected_sig = hmac.new(
        settings.auth.jwt_secret_key.encode(), expected_payload.encode(), hashlib.sha384
    ).hexdigest()

    if not hmac.compare_digest(sig, expected_sig):
        return None

    ttl = settings.auth.oauth_state_ttl_seconds
    if time.time() - ts > ttl:
        return None

    return provider


def _callback_url(request: Request) -> str:
    """Build the OAuth callback URL.

    Uses ``settings.auth.public_url`` when configured (recommended for
    production) so the redirect URI is deterministic and not derived from
    the request Host header.  Falls back to the Host header with
    ``X-Forwarded-Proto`` support for development.
    """
    settings = get_settings()
    base = settings.auth.public_url.rstrip("/")
    if base:
        return f"{base}/auth/callback"
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("host", request.url.netloc)
    return f"{scheme}://{host}/auth/callback"


_SAFE_REDIRECT_PATHS = ("/auth/tokens",)


@router.get("/login/{provider}")
async def login(provider: str, request: Request) -> RedirectResponse:
    """Redirect to OAuth2 provider's authorize URL."""
    settings = get_settings()
    callback_url = _callback_url(request)

    state = _generate_oauth_state(provider)

    if provider == "google":
        authorize_url = (
            "https://accounts.google.com/o/oauth2/v2/auth"
            f"?client_id={settings.auth.google_client_id}"
            f"&redirect_uri={callback_url}"
            "&response_type=code"
            "&scope=openid email profile"
            f"&state={state}"
        )
    elif provider == "github":
        authorize_url = (
            "https://github.com/login/oauth/authorize"
            f"?client_id={settings.auth.github_client_id}"
            f"&redirect_uri={callback_url}"
            "&scope=user:email"
            f"&state={state}"
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")

    # The authorize URL redirects to Google/GitHub OAuth whose registered
    # redirect_uri whitelist prevents open-redirect abuse.
    response = RedirectResponse(
        url=authorize_url
    )  # CodeQL: py/url-redirection — safe, OAuth provider validates redirect_uri

    # If a ?next= param was provided, store it in a short-lived cookie
    # so the callback can redirect back after login.
    next_url = request.query_params.get("next", "")
    if next_url and next_url in _SAFE_REDIRECT_PATHS:
        response.set_cookie(
            "wikimind_next",
            next_url,
            max_age=600,
            httponly=True,
            samesite="lax",
            secure=settings.auth.cookie_secure,
            path="/",
        )

    return response


@router.get("/callback", name="auth_callback")
async def callback(
    code: str,
    state: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    service: UserService = Depends(get_user_service),
) -> RedirectResponse:
    """Handle OAuth2 callback — exchange code for token, upsert user, set cookie."""
    settings = get_settings()
    provider = _consume_oauth_state(state)
    if provider is None:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    callback_url = _callback_url(request)

    if provider == "google":
        token_resp = await service.exchange_google_token(code, settings, callback_url)
        user_info = await service.fetch_google_userinfo(token_resp.access_token)
    elif provider == "github":
        token_resp = await service.exchange_github_token(code, settings)
        user_info = await service.fetch_github_userinfo(token_resp.access_token)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")

    user = await service.upsert_oauth_user(session, provider, user_info)
    jwt_token = service.create_jwt(user, settings)

    # Redirect to the stored return URL or the default SPA callback page.
    # The cookie value is validated against a strict allowlist to prevent
    # open redirect attacks (CodeQL py/url-redirection).
    next_url = request.cookies.get("wikimind_next", "")
    if next_url not in _SAFE_REDIRECT_PATHS:
        next_url = "/callback"
    response = RedirectResponse(url=next_url, status_code=302)
    response.delete_cookie("wikimind_next", path="/")
    response.set_cookie(
        key=settings.auth.cookie_name,
        value=jwt_token,
        httponly=True,
        secure=settings.auth.cookie_secure,
        samesite="lax",
        max_age=settings.auth.jwt_expiry_minutes * 60,
        path="/",
        domain=settings.auth.cookie_domain,
    )
    return response


@router.get("/me")
async def me(
    request: Request,
    session: AsyncSession = Depends(get_session),
    service: UserService = Depends(get_user_service),
) -> UserProfileResponse:
    """Return current user profile, auto-provisioning if needed."""
    settings = get_settings()
    if not request.state.user_id:
        if not settings.auth.enabled:
            return UserProfileResponse(id=ANONYMOUS_USER_ID, email="", name="Anonymous", avatar_url=None)
        raise HTTPException(status_code=401)

    email = getattr(request.state, "user_email", None)
    user = await service.get_or_create(session, request.state.user_id, email=email)

    return UserProfileResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        avatar_url=user.avatar_url,
    )


@router.post("/magic-link")
async def request_magic_link(
    body: MagicLinkRequest,
    service: UserService = Depends(get_user_service),
) -> MagicLinkResponse:
    """Request a magic link for passwordless email login.

    Generates an HMAC-signed token encoding the email and timestamp.
    In non-production mode, the token is returned in the response for
    CLI/testing use. In production, an email would be sent (not yet
    implemented).
    """
    settings = get_settings()
    if not settings.auth.magic_link_enabled:
        raise HTTPException(status_code=400, detail="Magic link login is disabled")

    token = service.create_magic_link_token(body.email, settings)
    log.info("magic_link_requested", email=body.email)

    # Always return the same message to avoid leaking whether the email exists.
    # Only include dev_token in development mode (secure by default).
    return MagicLinkResponse(
        status="ok",
        message="If that email is registered, a login link has been sent",
        dev_token=token if settings.is_dev else None,
    )


@router.post("/magic-link/verify")
async def verify_magic_link(
    body: MagicLinkVerifyRequest,
    session: AsyncSession = Depends(get_session),
    service: UserService = Depends(get_user_service),
) -> MagicLinkVerifyResponse:
    """Verify a magic link token and create a session JWT.

    Decodes and verifies the HMAC-signed token, looks up or creates
    the user, and returns a JWT access token.
    """
    settings = get_settings()
    if not settings.auth.magic_link_enabled:
        raise HTTPException(status_code=400, detail="Magic link login is disabled")

    try:
        email = service.verify_magic_link_token(body.token, settings)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    user = await service.get_or_create_by_email(session, email)
    jwt_token = service.create_jwt(user, settings)

    return MagicLinkVerifyResponse(
        access_token=jwt_token,
        user={
            "id": user.id,
            "email": user.email,
            "name": user.name,
        },
    )


_TOKEN_PAGE_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WikiMind — API Token</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         background: #f8fafc; color: #1e293b; min-height: 100vh;
         display: flex; justify-content: center; align-items: center; }
  .card { background: white; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,.1);
          padding: 32px; max-width: 420px; width: 100%; }
  h1 { font-size: 20px; margin-bottom: 4px; }
  .subtitle { font-size: 13px; color: #64748b; margin-bottom: 24px; }
  label { display: block; font-size: 12px; font-weight: 600; color: #64748b;
          margin-bottom: 4px; }
  input, select { width: 100%; padding: 8px; border: 1px solid #cbd5e1;
         border-radius: 6px; font-size: 13px; outline: none; margin-bottom: 12px; }
  input:focus, select:focus { border-color: #6366f1; }
  .btn { width: 100%; padding: 10px; border: none; border-radius: 6px;
         font-weight: 600; font-size: 13px; cursor: pointer; color: white;
         transition: background-color .15s; }
  .btn-primary { background: #6366f1; }
  .btn-primary:hover { background: #4f46e5; }
  .btn-primary:disabled { background: #a5b4fc; cursor: not-allowed; }
  .btn-login { background: #374151; margin-bottom: 8px; }
  .btn-login:hover { background: #1f2937; }
  .btn-copy { background: #22c55e; margin-top: 8px; }
  .btn-copy:hover { background: #16a34a; }
  .token-box { background: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 6px;
               padding: 12px; font-family: monospace; font-size: 12px;
               word-break: break-all; margin: 12px 0 4px; }
  .warn { font-size: 11px; color: #dc2626; margin-bottom: 12px; }
  .info { font-size: 12px; color: #64748b; margin-top: 8px; text-align: center; }
  .error { color: #dc2626; font-size: 12px; margin-bottom: 12px; }
  .hidden { display: none; }
  .divider { border: none; border-top: 1px solid #e2e8f0; margin: 16px 0; }
</style>
</head>
<body>
<div class="card">
  <h1>WikiMind API Token</h1>
  <p class="subtitle">Generate a token for the browser extension or API access.</p>

  <!-- Login section (shown when not authenticated) -->
  <div id="login-section" class="hidden">
    <p style="font-size:13px; color:#64748b; margin-bottom:16px;">
      Sign in to generate a token.
    </p>
    <button class="btn btn-login" id="login-google">
      Sign in with Google
    </button>
    <button class="btn btn-login" id="login-github">
      Sign in with GitHub
    </button>
  </div>

  <!-- Token form (shown when authenticated) -->
  <div id="token-section" class="hidden">
    <p id="user-info" style="font-size:13px; color:#64748b; margin-bottom:16px;"></p>
    <label for="token-name">Token name</label>
    <input id="token-name" type="text" placeholder="e.g. browser-extension" value="browser-extension">
    <label for="token-expiry">Expires in</label>
    <select id="token-expiry">
      <option value="30">30 days</option>
      <option value="90">90 days</option>
      <option value="180">180 days</option>
      <option value="365">1 year</option>
    </select>
    <div id="form-error" class="error hidden"></div>
    <button id="generate-btn" class="btn btn-primary">
      Generate Token
    </button>
  </div>

  <!-- Token result (shown after generation) -->
  <div id="result-section" class="hidden">
    <p class="warn">Copy this token now. You will not be able to see it again.</p>
    <div class="token-box" id="token-value"></div>
    <button class="btn btn-copy" id="copy-btn">Copy to Clipboard</button>
    <hr class="divider">
    <button class="btn btn-primary" id="reset-btn">Generate Another</button>
  </div>

  <div id="loading" class="info">Checking authentication...</div>
</div>

<script src="/auth/tokens.js"></script>
</body>
</html>
"""

_TOKEN_PAGE_JS = """\
async function checkAuth() {
  try {
    var resp = await fetch('/auth/me', {
      headers: { 'Accept': 'application/json' },
      credentials: 'same-origin'
    });
    if (resp.ok) {
      var user = await resp.json();
      if (user.id === 'anonymous' || !user.email) {
        showLogin();
      } else {
        showTokenForm(user);
      }
    } else {
      showLogin();
    }
  } catch (e) {
    showLogin();
  }
}

function showLogin() {
  document.getElementById('loading').classList.add('hidden');
  document.getElementById('login-section').classList.remove('hidden');
}

function showTokenForm(user) {
  document.getElementById('loading').classList.add('hidden');
  document.getElementById('token-section').classList.remove('hidden');
  document.getElementById('user-info').textContent = 'Signed in as ' + user.email;
}

async function generateToken() {
  var btn = document.getElementById('generate-btn');
  var errEl = document.getElementById('form-error');
  errEl.classList.add('hidden');
  btn.disabled = true;
  btn.textContent = 'Generating...';

  try {
    var resp = await fetch('/auth/token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({
        name: document.getElementById('token-name').value || 'api-token',
        expires_in_days: parseInt(document.getElementById('token-expiry').value)
      })
    });
    if (!resp.ok) {
      var data = await resp.json().catch(function() { return null; });
      throw new Error((data && data.error && data.error.message) || \
(data && data.detail) || 'Failed to create token');
    }
    var data = await resp.json();
    document.getElementById('token-value').textContent = data.access_token;
    document.getElementById('token-section').classList.add('hidden');
    document.getElementById('result-section').classList.remove('hidden');
  } catch (err) {
    errEl.textContent = err.message;
    errEl.classList.remove('hidden');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Generate Token';
  }
}

function copyToken() {
  var token = document.getElementById('token-value').textContent;
  navigator.clipboard.writeText(token).then(function() {
    var btn = document.querySelector('.btn-copy');
    btn.textContent = 'Copied!';
    btn.style.backgroundColor = '#16a34a';
    setTimeout(function() { btn.textContent = 'Copy to Clipboard'; \
btn.style.backgroundColor = ''; }, 2000);
  });
}

function resetForm() {
  document.getElementById('result-section').classList.add('hidden');
  document.getElementById('token-section').classList.remove('hidden');
}

// Bind event handlers (no inline onclick — CSP blocks unsafe-inline)
document.getElementById('login-google').addEventListener('click', function() {
  location.href = '/auth/login/google?next=/auth/tokens';
});
document.getElementById('login-github').addEventListener('click', function() {
  location.href = '/auth/login/github?next=/auth/tokens';
});
document.getElementById('generate-btn').addEventListener('click', generateToken);
document.getElementById('copy-btn').addEventListener('click', copyToken);
document.getElementById('reset-btn').addEventListener('click', resetForm);

checkAuth();
"""


@router.get("/tokens", response_class=HTMLResponse)
async def token_page() -> HTMLResponse:
    """Serve the API token generation page.

    This is a self-contained HTML page that lets authenticated users
    create API tokens for the browser extension or other API clients.
    Authentication is handled client-side via the session cookie.
    """
    return HTMLResponse(content=_TOKEN_PAGE_HTML)


@router.get("/tokens.js")
async def token_page_js() -> PlainTextResponse:
    """Serve the JavaScript for the token generation page.

    Extracted from the HTML page so that Content-Security-Policy can
    use ``script-src 'self'`` without ``'unsafe-inline'``.
    """
    return PlainTextResponse(content=_TOKEN_PAGE_JS, media_type="application/javascript")


@router.post("/token")
async def create_api_token(
    body: TokenCreateRequest,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(require_user_id),
    service: UserService = Depends(get_user_service),
) -> TokenCreateResponse:
    """Create a long-lived API token for CLI/automation use.

    Requires an existing session (cookie or Bearer token). Users must
    authenticate first via OAuth or magic link, then create API tokens.

    The raw JWT is returned only once in the response. The caller must
    store it securely. The token includes a ``token_use: api`` claim to
    distinguish it from session JWTs.
    """
    settings = get_settings()
    user = await service.get_or_create(session, user_id)

    now = datetime.now(UTC)
    expire = now + timedelta(days=body.expires_in_days)

    payload = {
        "sub": user.id,
        "iss": "wikimind",
        "aud": "wikimind-api",
        "iat": now,
        "exp": expire,
        "jti": str(uuid.uuid4()),
        "token_use": "api",
        "user": {"id": user.id, "email": user.email, "name": user.name},
    }

    access_token = pyjwt.encode(
        payload,
        settings.auth.jwt_secret_key,
        algorithm=settings.auth.jwt_algorithm,
    )

    return TokenCreateResponse(
        access_token=access_token,
        name=body.name,
        expires_at=expire.isoformat(),
    )


@router.post("/logout")
async def logout() -> JSONResponse:
    """Clear the session cookie."""
    settings = get_settings()
    response = JSONResponse(content={"status": "ok"})
    response.delete_cookie(
        key=settings.auth.cookie_name,
        path="/",
        domain=settings.auth.cookie_domain,
    )
    return response


@router.delete("/account")
async def delete_account(
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(require_user_id),
    service: UserService = Depends(get_user_service),
) -> DeleteAccountResponse:
    """Delete the current user's account and all owned data."""
    await service.delete_account(session, user_id)
    return DeleteAccountResponse(deleted=user_id)
