"""WikiMind CLI entry point.

Provides a terminal interface for interacting with the WikiMind API server.
All commands communicate with the server via HTTP (httpx).
"""

from __future__ import annotations

import click
import httpx

from wikimind.cli.auth import login, logout, whoami
from wikimind.cli.client import get_client, get_server_url, handle_response_error
from wikimind.cli.ingest import ingest
from wikimind.cli.query import ask
from wikimind.cli.wiki import wiki


@click.group()
@click.version_option(version="0.1.0", prog_name="wikimind")
def cli() -> None:
    """Run the WikiMind personal LLM-powered knowledge OS.

    Terminal interface for ingesting sources, browsing articles,
    and asking questions against your wiki.
    """


# Register subcommands
cli.add_command(login)
cli.add_command(logout)
cli.add_command(whoami)
cli.add_command(ingest)
cli.add_command(ask)
cli.add_command(wiki)


@cli.command()
def status() -> None:
    """Show wiki statistics (article count, source count, etc.)."""
    try:
        with get_client() as client:
            resp = client.get("/admin/stats")
            handle_response_error(resp)
            stats = resp.json()

        click.echo("WikiMind Status")
        click.echo("=" * 40)

        for key, value in stats.items():
            label = key.replace("_", " ").title()
            click.echo(f"  {label}: {value}")

    except httpx.ConnectError:
        click.echo(f"Error: Cannot connect to WikiMind server at {get_server_url()}", err=True)
        click.echo("Is the server running? Start it with 'make dev'.", err=True)
        raise SystemExit(1) from None
