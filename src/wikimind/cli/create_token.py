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
import sys
import uuid
from datetime import UTC, datetime, timedelta

import jwt


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
        default="cli-token",
        help="Token name (default: cli-token).",
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

    now = datetime.now(UTC)
    expire = now + timedelta(days=args.exp_days)

    # Use email as a stable user ID (matches get_or_create_by_email behavior)
    user_id = args.email

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
            "name": args.name,
        },
    }

    token = jwt.encode(payload, secret, algorithm="HS256")

    print(token)
    print(f"\n# Expires: {expire.isoformat()}", file=sys.stderr)
    print(f"# Email: {args.email}", file=sys.stderr)
    print(f"# Name: {args.name}", file=sys.stderr)
    print("#", file=sys.stderr)
    print("# Usage:", file=sys.stderr)
    print(f'#   export TOKEN="{token}"', file=sys.stderr)
    print(
        '#   curl -H "Authorization: Bearer $TOKEN" http://localhost:7842/auth/me',
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
