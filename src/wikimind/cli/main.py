"""WikiMind CLI entry point.

Provides a terminal interface for interacting with the WikiMind API server.
All commands communicate with the server via HTTP (httpx).
"""

from __future__ import annotations

import json
import sys

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


# ---------------------------------------------------------------------------
# MCP sub-group
# ---------------------------------------------------------------------------


@cli.group()
def mcp() -> None:
    """Model Context Protocol server commands."""


@mcp.command()
@click.option(
    "--transport",
    type=click.Choice(["stdio", "http"]),
    default="stdio",
    help="Transport protocol (default: stdio).",
)
@click.option("--host", default="127.0.0.1", help="Host for HTTP transport (default: 127.0.0.1).")
@click.option("--port", type=int, default=9100, help="Port for HTTP transport (default: 9100).")
def serve(transport: str, host: str, port: int) -> None:
    r"""Start the WikiMind MCP server.

    Runs the MCP server over stdin/stdout (default) or HTTP so MCP
    clients like Claude Desktop or Cursor can connect to the wiki.

    Add this to your Claude Desktop config (claude_desktop_config.json):

    \b
      {
        "mcpServers": {
          "wikimind": {
            "command": "wikimind",
            "args": ["mcp", "serve"]
          }
        }
      }
    """
    from wikimind.mcp.server import run_server  # noqa: PLC0415

    # Build sys.argv so argparse in run_server() picks up the options.
    sys.argv = ["wikimind-mcp", "--transport", transport, "--host", host, "--port", str(port)]
    run_server()


@mcp.command(name="config")
def mcp_config() -> None:
    """Print Claude Desktop configuration snippet for WikiMind MCP."""
    python_path = sys.executable
    config = {
        "mcpServers": {
            "wikimind": {
                "command": python_path,
                "args": ["-m", "wikimind.mcp.server"],
            },
        },
    }
    click.echo("Add this to your Claude Desktop config (claude_desktop_config.json):\n")
    click.echo(json.dumps(config, indent=2))


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
