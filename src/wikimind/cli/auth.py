"""Authentication commands — login, logout, whoami."""

from __future__ import annotations

import click
import httpx

from wikimind.cli.client import (
    clear_token,
    get_client,
    get_server_url,
    handle_response_error,
    load_token,
    save_token,
)


@click.command()
@click.option("--email", prompt="Email address", help="Email address for magic link login.")
def login(email: str) -> None:
    """Authenticate via magic link and save the session token."""
    base_url = get_server_url()
    try:
        with httpx.Client(base_url=base_url, timeout=30.0) as client:
            # Step 1: Request magic link
            resp = client.post(
                "/auth/magic-link",
                json={"email": email},
                headers={"Accept": "application/json"},
            )
            handle_response_error(resp)
            data = resp.json()

            dev_token = data.get("dev_token")
            if not dev_token:
                click.echo("Magic link sent. Check your email for the login link.")
                click.echo("(In production, paste the token from the email.)")
                dev_token = click.prompt("Token")

            # Step 2: Verify the magic link token
            resp = client.post(
                "/auth/magic-link/verify",
                json={"token": dev_token},
                headers={"Accept": "application/json"},
            )
            handle_response_error(resp)
            verify_data = resp.json()

            access_token = verify_data.get("access_token")
            if not access_token:
                click.echo("Error: No access token in response.", err=True)
                raise SystemExit(1)

            save_token(access_token)
            user = verify_data.get("user", {})
            name = user.get("name") or user.get("email") or "unknown"
            click.echo(f"Logged in as {name}. Token saved to ~/.wikimind/token")

    except httpx.ConnectError:
        click.echo(f"Error: Cannot connect to WikiMind server at {base_url}", err=True)
        click.echo("Is the server running? Start it with 'make dev'.", err=True)
        raise SystemExit(1) from None


@click.command()
def logout() -> None:
    """Clear the saved authentication token."""
    if load_token():
        clear_token()
        click.echo("Logged out. Token removed from ~/.wikimind/token")
    else:
        click.echo("Not logged in.")


@click.command()
def whoami() -> None:
    """Show the current authenticated user."""
    try:
        with get_client() as client:
            resp = client.get("/auth/me")
            handle_response_error(resp)
            data = resp.json()

        email = data.get("email", "")
        name = data.get("name", "")
        user_id = data.get("id", "unknown")

        click.echo(f"User:  {name}")
        click.echo(f"Email: {email}")
        click.echo(f"ID:    {user_id}")

    except httpx.ConnectError:
        click.echo(f"Error: Cannot connect to WikiMind server at {get_server_url()}", err=True)
        click.echo("Is the server running? Start it with 'make dev'.", err=True)
        raise SystemExit(1) from None
