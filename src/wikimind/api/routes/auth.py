"""OAuth2 authentication routes — Google and GitHub login flows.

Provides ``/auth/login/{provider}`` to redirect users to the OAuth2
provider's authorization page, ``/auth/callback`` to handle the code
exchange and JWT issuance, and ``/auth/me`` to return the current
user's profile.
"""

from datetime import UTC, datetime, timedelta

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from wikimind.config import Settings, get_settings
from wikimind.database import get_session
from wikimind.models import User

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
# Route handlers
# ---------------------------------------------------------------------------


@router.get("/login/{provider}")
async def login(provider: str, request: Request) -> RedirectResponse:
    """Redirect to OAuth2 provider's authorize URL."""
    settings = get_settings()
    callback_url = str(request.url_for("auth_callback"))

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
    callback_url = str(request.url_for("auth_callback"))

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

    return RedirectResponse(url=f"/?token={jwt_token}")


@router.get("/me")
async def me(request: Request, session: AsyncSession = Depends(get_session)) -> dict:
    """Return current user profile."""
    if not request.state.user_id:
        raise HTTPException(status_code=401)
    user = await session.get(User, request.state.user_id)
    if not user:
        raise HTTPException(status_code=404)
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "avatar_url": user.avatar_url,
    }
