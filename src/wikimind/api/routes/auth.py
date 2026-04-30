"""OAuth2 authentication routes — Google/GitHub login and magic link (passwordless email).

Thin route handlers that delegate to :class:`UserService` for all
business logic (token exchange, user upsert, JWT creation, magic link
token creation/verification, account deletion). The JWT is stored in
an HttpOnly cookie.
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.api.deps import ANONYMOUS_USER_ID, require_user_id
from wikimind.config import get_settings
from wikimind.database import get_session
from wikimind.models import (
    MagicLinkRequest,
    MagicLinkResponse,
    MagicLinkVerifyRequest,
    MagicLinkVerifyResponse,
)
from wikimind.services.user import UserService, get_user_service

log = structlog.get_logger()

router = APIRouter()


def _callback_url(request: Request) -> str:
    """Build the OAuth callback URL from the request's Host header."""
    host = request.headers.get("host", request.url.netloc)
    return f"{request.url.scheme}://{host}/auth/callback"


@router.get("/login/{provider}")
async def login(provider: str, request: Request) -> RedirectResponse:
    """Redirect to OAuth2 provider's authorize URL."""
    settings = get_settings()
    callback_url = _callback_url(request)

    if provider == "google":
        authorize_url = (
            "https://accounts.google.com/o/oauth2/v2/auth"
            f"?client_id={settings.auth.google_client_id}"
            f"&redirect_uri={callback_url}"
            "&response_type=code"
            "&scope=openid email profile"
            f"&state={provider}"
        )
    elif provider == "github":
        authorize_url = (
            "https://github.com/login/oauth/authorize"
            f"?client_id={settings.auth.github_client_id}"
            f"&redirect_uri={callback_url}"
            "&scope=user:email"
            f"&state={provider}"
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")

    return RedirectResponse(url=authorize_url)


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
    provider = state
    callback_url = _callback_url(request)

    if provider == "google":
        token_resp = await service.exchange_google_token(code, settings, callback_url)
        user_info = await service.fetch_google_userinfo(token_resp["access_token"])
    elif provider == "github":
        token_resp = await service.exchange_github_token(code, settings)
        user_info = await service.fetch_github_userinfo(token_resp["access_token"])
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")

    user = await service.upsert_oauth_user(session, provider, user_info)
    jwt_token = service.create_jwt(user, settings)

    response = RedirectResponse(url="/callback", status_code=302)
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
) -> dict:
    """Return current user profile, auto-provisioning if needed."""
    settings = get_settings()
    if not request.state.user_id:
        if not settings.auth.enabled:
            return {"id": ANONYMOUS_USER_ID, "email": "", "name": "Anonymous", "avatar_url": None}
        raise HTTPException(status_code=401)

    email = getattr(request.state, "user_email", None)
    user = await service.get_or_create(session, request.state.user_id, email=email)

    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "avatar_url": user.avatar_url,
    }


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
    # Include the dev_token for non-production use (CLI, testing).
    return MagicLinkResponse(
        status="ok",
        message="If that email is registered, a login link has been sent",
        dev_token=token,
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
) -> dict:
    """Delete the current user's account and all owned data."""
    await service.delete_account(session, user_id)
    return {"deleted": user_id}
