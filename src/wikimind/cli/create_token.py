# ruff: noqa: T201, PLC0415
"""Generate a JWT API token for local development and testing.

Usage:
    python3 -m wikimind.cli.create_token --email dev@wikimind.dev
    python3 -m wikimind.cli.create_token --email dev@wikimind.dev --name my-token --exp-days 90

This is a server-side tool that reads the JWT secret from the environment
or .env file and mints a token directly. It does NOT call the API.

Similar to mcp-context-forge's ``create_jwt_token`` utility.

Security note:
    This tool has access to the JWT secret and can create tokens with ANY
    claims. Only use for development/testing. For production, users should
    authenticate via OAuth or magic link, then create API tokens via the
    ``POST /auth/token`` endpoint.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta

import jwt


async def _lookup_user_by_email(email: str) -> tuple[str, str | None]:
    """Look up a user by email and return (user_id, user_name).

    Raises SystemExit if the user is not found.
    """
    from sqlmodel import select

    from wikimind.database import get_async_engine, get_session_factory
    from wikimind.models import User

    engine = get_async_engine()

    # Ensure tables exist (engine may point at a fresh DB)
    async with engine.begin() as conn:
        from sqlmodel import SQLModel

        await conn.run_sync(SQLModel.metadata.create_all)

    factory = get_session_factory()
    async with factory() as session:
        result = await session.exec(select(User).where(User.email == email))
        user = result.one_or_none()

    if user is None:
        print(f"ERROR: No user found with email '{email}'.", file=sys.stderr)
        print(
            "  The user must log in via OAuth or magic link first to create an account.",
            file=sys.stderr,
        )
        print(
            "  Then re-run this command to generate a token with the correct user ID.",
            file=sys.stderr,
        )
        sys.exit(1)

    return user.id, user.name


def main() -> None:  # noqa: D103
    parser = argparse.ArgumentParser(
        description="Generate a WikiMind JWT API token for dev/testing.",
    )
    parser.add_argument(
        "--email",
        required=True,
        help="Email address for the token subject.",
    )
    parser.add_argument(
        "--name",
        default=None,
        help="Token name (default: user's name from DB, or 'cli-token').",
    )
    parser.add_argument(
        "--exp-days",
        type=int,
        default=30,
        help="Token expiration in days (default: 30).",
    )
    parser.add_argument(
        "--secret",
        default=None,
        help="JWT secret key. If not provided, reads from WIKIMIND_AUTH__JWT_SECRET_KEY env var.",
    )
    args = parser.parse_args()

    # Resolve the JWT secret
    secret = args.secret
    if not secret:
        import os

        secret = os.environ.get("WIKIMIND_AUTH__JWT_SECRET_KEY")
    if not secret:
        # Try loading from .env file
        try:
            from dotenv import dotenv_values

            env = dotenv_values(".env")
            secret = env.get("WIKIMIND_AUTH__JWT_SECRET_KEY")
        except ImportError:
            pass
    if not secret:
        print("ERROR: No JWT secret found.", file=sys.stderr)
        print(
            "  Set WIKIMIND_AUTH__JWT_SECRET_KEY in your environment or .env file,",
            file=sys.stderr,
        )
        print("  or pass --secret <key>.", file=sys.stderr)
        sys.exit(1)

    # Look up the user by email to get their actual UUID
    user_id, user_name = asyncio.run(_lookup_user_by_email(args.email))
    token_name = args.name or user_name or "cli-token"

    now = datetime.now(UTC)
    expire = now + timedelta(days=args.exp_days)

    payload = {
        "sub": user_id,
        "iss": "wikimind",
        "aud": "wikimind-api",
        "iat": now,
        "exp": expire,
        "jti": str(uuid.uuid4()),
        "token_use": "api",
        "user": {
            "id": user_id,
            "email": args.email,
            "name": token_name,
        },
    }

    token = jwt.encode(payload, secret, algorithm="HS256")

    print(token)
    print(f"\n# Expires: {expire.isoformat()}", file=sys.stderr)
    print(f"# User ID: {user_id}", file=sys.stderr)
    print(f"# Email: {args.email}", file=sys.stderr)
    print(f"# Name: {token_name}", file=sys.stderr)
    print("#", file=sys.stderr)
    print("# Usage:", file=sys.stderr)
    print(f'#   export TOKEN="{token}"', file=sys.stderr)
    print(
        '#   curl -H "Authorization: Bearer $TOKEN" http://localhost:7842/auth/me',
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
