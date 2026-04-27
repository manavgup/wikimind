"""OAuth2 authentication routes — Google and GitHub login flows.

Thin route handlers that delegate to :class:`UserService` for all
business logic (token exchange, user upsert, JWT creation, account
deletion). The JWT is stored in an HttpOnly cookie.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from wikimind.api.deps import ANONYMOUS_USER_ID, get_current_user_id
from wikimind.config import get_settings
from wikimind.database import get_session
from wikimind.services.user import UserService, get_user_service

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
    user_id: str = Depends(get_current_user_id),
    service: UserService = Depends(get_user_service),
) -> dict:
    """Delete the current user's account and all owned data."""
    if user_id == ANONYMOUS_USER_ID:
        raise HTTPException(status_code=400, detail="Cannot delete the anonymous account")
    await service.delete_account(session, user_id)
    return {"deleted": user_id}
