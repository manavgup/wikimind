"""User lifecycle management — OAuth upsert, JWT provisioning, account deletion.

Centralizes all user-related business logic: OAuth provider user upsert,
JWT-based auto-provisioning, JWT creation, magic link token generation/
verification, and cascade account deletion.
Route handlers in ``api/routes/auth.py`` are thin delegates.
"""

import base64
import binascii
import functools
import hashlib
import hmac
import time
from datetime import UTC, datetime, timedelta

import httpx
import jwt as pyjwt
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from wikimind.config import Settings
from wikimind.errors import NotFoundError
from wikimind.models import (
    Article,
    ArticleConcept,
    ArticleSource,
    Backlink,
    Concept,
    ContradictionFinding,
    Conversation,
    CostLog,
    Job,
    LintReport,
    OAuthTokenResponse,
    OAuthUserInfo,
    OrphanFinding,
    Query,
    Source,
    StructuralFinding,
    SyncLog,
    User,
    UserApiKey,
    UserPreference,
)


class UserService:
    """Manage user provisioning, OAuth flows, and account lifecycle."""

    # ------------------------------------------------------------------
    # OAuth token exchange
    # ------------------------------------------------------------------

    async def exchange_google_token(self, code: str, settings: Settings, redirect_uri: str) -> OAuthTokenResponse:
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
            return OAuthTokenResponse(**resp.json())

    async def exchange_github_token(self, code: str, settings: Settings) -> OAuthTokenResponse:
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
            return OAuthTokenResponse(**resp.json())

    # ------------------------------------------------------------------
    # OAuth user info
    # ------------------------------------------------------------------

    async def fetch_google_userinfo(self, access_token: str) -> OAuthUserInfo:
        """Fetch the authenticated user's profile from Google."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            return OAuthUserInfo(**resp.json())

    async def fetch_github_userinfo(self, access_token: str) -> OAuthUserInfo:
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
            user_data: dict[str, str | int | None] = user_resp.json()

            if not user_data.get("email"):
                email_resp = await client.get("https://api.github.com/user/emails", headers=headers)
                email_resp.raise_for_status()
                emails: list[dict[str, str | bool]] = email_resp.json()
                primary = next((e for e in emails if e.get("primary") and e.get("verified")), None)
                if primary:
                    user_data["email"] = primary["email"]

            return OAuthUserInfo(**user_data)

    # ------------------------------------------------------------------
    # User upsert + JWT creation
    # ------------------------------------------------------------------

    async def upsert_oauth_user(self, session: AsyncSession, provider: str, user_info: OAuthUserInfo) -> User:
        """Find or create a user from OAuth provider info.

        Looks up by ``(auth_provider, auth_provider_id)`` first, then falls
        back to email. This handles the case where a user logs in with
        Google first and GitHub second using the same email — they get the
        same User record.

        Args:
            session: Async database session.
            provider: OAuth provider name (``"google"`` or ``"github"``).
            user_info: Typed user profile from the provider API.

        Returns:
            The existing or newly created User record.
        """
        if provider == "google":
            provider_id = str(user_info.id)
            email = user_info.email
            name = user_info.name
            avatar_url = user_info.picture
        else:
            provider_id = str(user_info.id)
            email = user_info.email
            name = user_info.name or user_info.login
            avatar_url = user_info.avatar_url

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

    def create_jwt(self, user: User, settings: Settings) -> str:
        """Create a signed JWT for the given user.

        Args:
            user: The authenticated User record.
            settings: Application settings (for JWT secret, algorithm, expiry).

        Returns:
            Encoded JWT string.
        """
        now = datetime.now(UTC)
        payload = {
            "sub": user.id,
            "email": user.email,
            "exp": now + timedelta(minutes=settings.auth.jwt_expiry_minutes),
            "iat": now,
        }
        return pyjwt.encode(
            payload,
            settings.auth.jwt_secret_key,
            algorithm=settings.auth.jwt_algorithm,
        )

    # ------------------------------------------------------------------
    # JWT-based auto-provisioning
    # ------------------------------------------------------------------

    async def get_or_create(
        self,
        session: AsyncSession,
        user_id: str,
        email: str | None = None,
    ) -> User:
        """Return an existing user or auto-provision a new one.

        Used by ``GET /auth/me`` to ensure a valid JWT always maps to a
        user row, even without the full OAuth callback flow.

        Args:
            session: Async database session.
            user_id: The user ID from the JWT ``sub`` claim.
            email: Optional email from the JWT ``email`` claim.

        Returns:
            The existing or newly created User record.
        """
        user = await session.get(User, user_id)
        if user:
            return user

        user = User(
            id=user_id,
            email=email or f"{user_id}@jwt.local",
            name=user_id,
            auth_provider="jwt",
            auth_provider_id=user_id,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user

    # ------------------------------------------------------------------
    # Magic link (passwordless email) login
    # ------------------------------------------------------------------

    def create_magic_link_token(self, email: str, settings: Settings) -> str:
        """Create an HMAC-signed stateless magic link token.

        The token encodes ``email:timestamp`` and is signed with the JWT
        secret. No server-side state is needed.

        Args:
            email: The email address to encode in the token.
            settings: Application settings (for JWT secret and TTL).

        Returns:
            A URL-safe base64-encoded token string.
        """
        timestamp = str(int(time.time()))
        payload = f"{email}:{timestamp}"
        signature = hmac.new(
            settings.auth.jwt_secret_key.encode(),
            payload.encode(),
            hashlib.sha256,
        ).digest()
        token_bytes = f"{payload}:{base64.urlsafe_b64encode(signature).decode()}".encode()
        return base64.urlsafe_b64encode(token_bytes).decode()

    def verify_magic_link_token(self, token: str, settings: Settings) -> str:
        """Verify an HMAC-signed magic link token and return the email.

        Args:
            token: The base64-encoded magic link token.
            settings: Application settings (for JWT secret and TTL).

        Returns:
            The email address encoded in the token.

        Raises:
            ValueError: If the token is invalid, tampered, or expired.
        """
        try:
            decoded = base64.urlsafe_b64decode(token.encode()).decode()
        except (ValueError, binascii.Error) as exc:
            msg = "Invalid token encoding"
            raise ValueError(msg) from exc

        parts = decoded.rsplit(":", 2)
        if len(parts) != 3:
            msg = "Malformed token"
            raise ValueError(msg)

        email, timestamp_str, encoded_sig = parts

        # Verify HMAC signature
        payload = f"{email}:{timestamp_str}"
        expected_sig = hmac.new(
            settings.auth.jwt_secret_key.encode(),
            payload.encode(),
            hashlib.sha256,
        ).digest()
        try:
            actual_sig = base64.urlsafe_b64decode(encoded_sig.encode())
        except (ValueError, binascii.Error) as exc:
            msg = "Invalid signature encoding"
            raise ValueError(msg) from exc

        if not hmac.compare_digest(expected_sig, actual_sig):
            msg = "Invalid token signature"
            raise ValueError(msg)

        # Check TTL
        try:
            created_at = int(timestamp_str)
        except ValueError as exc:
            msg = "Invalid timestamp"
            raise ValueError(msg) from exc

        elapsed = int(time.time()) - created_at
        if elapsed > settings.auth.magic_link_ttl_seconds:
            msg = "Token has expired"
            raise ValueError(msg)

        return email

    async def get_or_create_by_email(
        self,
        session: AsyncSession,
        email: str,
    ) -> User:
        """Look up a user by email or create a new one for magic link login.

        Args:
            session: Async database session.
            email: The user's email address.

        Returns:
            The existing or newly created User record.
        """
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user:
            return user

        user = User(
            email=email,
            name=email.split("@", maxsplit=1)[0],
            auth_provider="magic_link",
            auth_provider_id=email,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user

    # ------------------------------------------------------------------
    # Account deletion
    # ------------------------------------------------------------------

    async def delete_account(self, session: AsyncSession, user_id: str) -> None:
        """Cascade-delete all data owned by a user, then remove the user row.

        Deletion order respects FK constraints: child/join rows that
        reference articles, conversations, or lint reports are removed
        before the parent rows.

        Args:
            session: Async database session.
            user_id: The user ID to delete.

        Raises:
            NotFoundError: If the user does not exist.
        """
        user = await session.get(User, user_id)
        if not user:
            msg = "User not found"
            raise NotFoundError(msg)

        # Collect IDs for join-table / child-table cleanup
        article_ids = [
            row[0] for row in (await session.execute(select(Article.id).where(Article.user_id == user_id))).all()
        ]
        report_ids = [
            row[0] for row in (await session.execute(select(LintReport.id).where(LintReport.user_id == user_id))).all()
        ]
        conv_ids = [
            row[0]
            for row in (await session.execute(select(Conversation.id).where(Conversation.user_id == user_id))).all()
        ]

        # 1. Delete child rows that reference articles
        if article_ids:
            await session.execute(
                delete(ArticleConcept).where(
                    ArticleConcept.article_id.in_(article_ids)  # type: ignore[attr-defined]
                )
            )
            await session.execute(
                delete(ArticleSource).where(
                    ArticleSource.article_id.in_(article_ids)  # type: ignore[attr-defined]
                )
            )
            await session.execute(
                delete(ContradictionFinding).where(
                    ContradictionFinding.article_a_id.in_(article_ids)  # type: ignore[attr-defined]
                )
            )
            await session.execute(
                delete(ContradictionFinding).where(
                    ContradictionFinding.article_b_id.in_(article_ids)  # type: ignore[attr-defined]
                )
            )
            await session.execute(
                delete(OrphanFinding).where(
                    OrphanFinding.article_id.in_(article_ids)  # type: ignore[attr-defined]
                )
            )
            await session.execute(
                delete(StructuralFinding).where(
                    StructuralFinding.article_id.in_(article_ids)  # type: ignore[attr-defined]
                )
            )

        # 2. Delete lint findings that reference reports
        if report_ids:
            await session.execute(
                delete(ContradictionFinding).where(
                    ContradictionFinding.report_id.in_(report_ids)  # type: ignore[attr-defined]
                )
            )
            await session.execute(
                delete(OrphanFinding).where(
                    OrphanFinding.report_id.in_(report_ids)  # type: ignore[attr-defined]
                )
            )
            await session.execute(
                delete(StructuralFinding).where(
                    StructuralFinding.report_id.in_(report_ids)  # type: ignore[attr-defined]
                )
            )

        # 3. Delete queries that reference conversations
        if conv_ids:
            await session.execute(
                delete(Query).where(
                    Query.conversation_id.in_(conv_ids)  # type: ignore[union-attr]
                )
            )

        # 4. Delete all user-owned rows
        await session.execute(delete(Backlink).where(Backlink.user_id == user_id))  # type: ignore[arg-type]
        await session.execute(delete(Article).where(Article.user_id == user_id))  # type: ignore[arg-type]
        await session.execute(delete(Source).where(Source.user_id == user_id))  # type: ignore[arg-type]
        await session.execute(delete(Concept).where(Concept.user_id == user_id))  # type: ignore[arg-type]
        await session.execute(delete(Conversation).where(Conversation.user_id == user_id))  # type: ignore[arg-type]
        await session.execute(delete(Job).where(Job.user_id == user_id))  # type: ignore[arg-type]
        await session.execute(delete(CostLog).where(CostLog.user_id == user_id))  # type: ignore[arg-type]
        await session.execute(delete(SyncLog).where(SyncLog.user_id == user_id))  # type: ignore[arg-type]
        await session.execute(delete(LintReport).where(LintReport.user_id == user_id))  # type: ignore[arg-type]
        await session.execute(delete(UserApiKey).where(UserApiKey.user_id == user_id))  # type: ignore[arg-type]
        await session.execute(delete(UserPreference).where(UserPreference.user_id == user_id))  # type: ignore[arg-type]

        # 5. Delete the user
        await session.delete(user)
        await session.commit()


@functools.lru_cache(maxsize=1)
def get_user_service() -> UserService:
    """Return a singleton UserService instance for FastAPI dependency injection."""
    return UserService()
