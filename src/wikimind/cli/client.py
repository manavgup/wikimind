"""Shared HTTP client and configuration for the WikiMind CLI.

Provides a pre-configured httpx client that reads the server URL from
WIKIMIND_URL (default ``http://localhost:7842``) and attaches the saved
JWT token from ``~/.wikimind/token`` as a Bearer header.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click
import httpx

TOKEN_PATH = Path.home() / ".wikimind" / "token"
DEFAULT_URL = "http://localhost:7842"


def get_server_url() -> str:
    """Return the WikiMind server URL from env or default."""
    return os.environ.get("WIKIMIND_URL", DEFAULT_URL).rstrip("/")


def load_token() -> str | None:
    """Load the saved JWT token from disk, or None if absent."""
    if TOKEN_PATH.is_file():
        return TOKEN_PATH.read_text().strip()
    return None


def save_token(token: str) -> None:
    """Persist a JWT token to ``~/.wikimind/token``."""
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(token + "\n")
    TOKEN_PATH.chmod(0o600)


def clear_token() -> None:
    """Remove the saved token file."""
    if TOKEN_PATH.is_file():
        TOKEN_PATH.unlink()


def get_client() -> httpx.Client:
    """Build an httpx.Client with base URL and auth header."""
    base_url = get_server_url()
    headers: dict[str, str] = {"Accept": "application/json"}
    token = load_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(base_url=base_url, headers=headers, timeout=30.0)


def require_auth() -> str:
    """Return the saved token or exit with an error message."""
    token = load_token()
    if not token:
        click.echo("Error: Not authenticated. Run 'wikimind login' first.", err=True)
        sys.exit(1)
    return token


def handle_response_error(resp: httpx.Response) -> None:
    """Print a user-friendly error and exit for non-2xx responses."""
    if resp.is_success:
        return

    if resp.status_code == 401:
        click.echo("Error: Authentication required. Run 'wikimind login' first.", err=True)
        sys.exit(1)

    if resp.status_code == 404:
        click.echo("Error: Not found.", err=True)
        sys.exit(1)

    # Try to extract structured error message
    try:
        data = resp.json()
        if "error" in data:
            msg = data["error"].get("message", resp.text)
        elif "detail" in data:
            msg = data["detail"]
        else:
            msg = resp.text
    except Exception:
        msg = resp.text

    click.echo(f"Error ({resp.status_code}): {msg}", err=True)
    sys.exit(1)
