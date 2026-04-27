"""OAuth2 authentication routes — Google and GitHub login flows.

Provides ``/auth/login/{provider}`` to redirect users to the OAuth2
provider's authorization page, ``/auth/callback`` to handle the code
exchange, JWT issuance, and HttpOnly cookie setting, ``/auth/me`` to
return the current user's profile, and ``/auth/logout`` to clear the
session cookie.

The JWT is stored in an HttpOnly cookie (not exposed to JavaScript).
After the OAuth callback sets the cookie, the browser is redirected to
``/callback`` on the frontend where the SPA calls ``/auth/me``
(cookie sent automatically) to confirm the session.
"""

from datetime import UTC, datetime, timedelta

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from wikimind.api.deps import ANONYMOUS_USER_ID, get_current_user_id
from wikimind.config import Settings, get_settings
from wikimind.database import get_session
from wikimind.models import User
from wikimind.services.user import UserService, get_user_service

router = APIRouter()


# ---------------------------------------------------------------------------
# OAuth2 token exchange helpers
# ---------------------------------------------------------------------------


async def _exchange_google_token(code: str, settings: Settings, redirect_uri: str) -> dict:
    """Exchange a Google authorization code for an access token."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.auth.google_client_id,
                "client_secret": settings.auth.google_client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        resp.raise_for_status()
        return resp.json()


async def _exchange_github_token(code: str, settings: Settings) -> dict:
    """Exchange a GitHub authorization code for an access token."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://github.com/login/oauth/access_token",
            json={
                "client_id": settings.auth.github_client_id,
                "client_secret": settings.auth.github_client_secret,
                "code": code,
            },
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# OAuth2 user-info helpers
# ---------------------------------------------------------------------------


async def _fetch_google_userinfo(access_token: str) -> dict:
    """Fetch the authenticated user's profile from Google."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json()


async def _fetch_github_userinfo(access_token: str) -> dict:
    """Fetch the authenticated user's profile from GitHub.

    GitHub's ``/user`` endpoint may not include a public email, so we
    also hit ``/user/emails`` and pick the primary verified address.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient() as client:
        user_resp = await client.get("https://api.github.com/user", headers=headers)
        user_resp.raise_for_status()
        user_data = user_resp.json()

        if not user_data.get("email"):
            email_resp = await client.get("https://api.github.com/user/emails", headers=headers)
            email_resp.raise_for_status()
            emails = email_resp.json()
            primary = next((e for e in emails if e.get("primary") and e.get("verified")), None)
            if primary:
                user_data["email"] = primary["email"]

        return user_data


# ---------------------------------------------------------------------------
# User upsert + JWT creation
# ---------------------------------------------------------------------------


async def _upsert_user(session: AsyncSession, provider: str, user_info: dict) -> User:
    """Find or create a user by (auth_provider, auth_provider_id)."""
    if provider == "google":
        provider_id = str(user_info["id"])
        email = user_info["email"]
        name = user_info.get("name")
        avatar_url = user_info.get("picture")
    else:
        provider_id = str(user_info["id"])
        email = user_info["email"]
        name = user_info.get("name") or user_info.get("login")
        avatar_url = user_info.get("avatar_url")

    # Look up by provider identity first, then fall back to email.
    # This handles the case where a user logs in with Google first and
    # GitHub second using the same email — they get the same User record.
    result = await session.execute(
        select(User).where(User.auth_provider == provider, User.auth_provider_id == provider_id)
    )
    user = result.scalar_one_or_none()

    if not user and email:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

    if user:
        user.name = name
        user.avatar_url = avatar_url
        user.updated_at = datetime.now(UTC).replace(tzinfo=None)
        session.add(user)
    else:
        user = User(
            email=email,
            name=name,
            avatar_url=avatar_url,
            auth_provider=provider,
            auth_provider_id=provider_id,
        )
        session.add(user)

    await session.commit()
    await session.refresh(user)
    return user


def _create_jwt(user: User, settings: Settings) -> str:
    """Create a signed JWT for the given user."""
    now = datetime.now(UTC)
    payload = {
        "sub": user.id,
        "email": user.email,
        "exp": now + timedelta(minutes=settings.auth.jwt_expiry_minutes),
        "iat": now,
    }
    return jwt.encode(
        payload,
        settings.auth.jwt_secret_key,
        algorithm=settings.auth.jwt_algorithm,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _callback_url(request: Request) -> str:
    """Build the OAuth callback URL from the request's Host header.

    ``request.url_for()`` uses the ASGI scope's server address which
    ignores reverse proxies (Vite dev proxy, nginx, Fly.io).  Reading
    the ``Host`` header directly produces the correct origin in all
    environments.
    """
    host = request.headers.get("host", request.url.netloc)
    return f"{request.url.scheme}://{host}/auth/callback"


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


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
    code: str, state: str, request: Request, session: AsyncSession = Depends(get_session)
) -> RedirectResponse:
    """Handle OAuth2 callback — exchange code for token, upsert user, return JWT."""
    settings = get_settings()
    provider = state
    # Google requires the exact redirect_uri used in the authorize request
    callback_url = _callback_url(request)

    if provider == "google":
        token_resp = await _exchange_google_token(code, settings, callback_url)
        user_info = await _fetch_google_userinfo(token_resp["access_token"])
    elif provider == "github":
        token_resp = await _exchange_github_token(code, settings)
        user_info = await _fetch_github_userinfo(token_resp["access_token"])
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")

    user = await _upsert_user(session, provider, user_info)
    jwt_token = _create_jwt(user, settings)

    # Set JWT as HttpOnly cookie and redirect to the frontend callback page.
    # The redirect is relative — in both dev (Vite proxy) and prod (same origin)
    # the browser stays on the frontend origin.  The AuthCallback component
    # calls /auth/me (cookie sent automatically) to confirm the session.
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
