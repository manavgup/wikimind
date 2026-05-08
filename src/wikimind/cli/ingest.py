"""Ingest commands — add URLs, files, and text to the knowledge base."""

from __future__ import annotations

from pathlib import Path

import click
import httpx

from wikimind.cli.client import get_client, get_server_url, handle_response_error


@click.group()
def ingest() -> None:
    """Ingest sources into the knowledge base."""


@ingest.command()
@click.argument("url")
def url(url: str) -> None:
    """Ingest a web URL or YouTube video."""
    try:
        with get_client() as client:
            resp = client.post("/ingest/url", json={"url": url})
            handle_response_error(resp)
            data = resp.json()

        click.echo(f"Source ingested: {data.get('title', url)}")
        click.echo(f"  ID:     {data.get('id', 'unknown')}")
        click.echo(f"  Type:   {data.get('source_type', 'unknown')}")
        click.echo(f"  Status: {data.get('status', 'unknown')}")

    except httpx.ConnectError:
        click.echo(f"Error: Cannot connect to WikiMind server at {get_server_url()}", err=True)
        click.echo("Is the server running? Start it with 'make dev'.", err=True)
        raise SystemExit(1) from None


@ingest.command()
@click.argument("path", type=click.Path(exists=True))
def file(path: str) -> None:
    """Ingest a local PDF document into the wiki."""
    file_path = Path(path)
    if file_path.suffix.lower() != ".pdf":
        click.echo("Error: Only PDF files are currently supported.", err=True)
        raise SystemExit(1)

    try:
        with get_client() as client:
            with open(file_path, "rb") as f:
                resp = client.post(
                    "/ingest/pdf",
                    files={"file": (file_path.name, f, "application/pdf")},
                )
            handle_response_error(resp)
            data = resp.json()

        click.echo(f"Source ingested: {data.get('title', file_path.name)}")
        click.echo(f"  ID:     {data.get('id', 'unknown')}")
        click.echo(f"  Status: {data.get('status', 'unknown')}")

    except httpx.ConnectError:
        click.echo(f"Error: Cannot connect to WikiMind server at {get_server_url()}", err=True)
        click.echo("Is the server running? Start it with 'make dev'.", err=True)
        raise SystemExit(1) from None


@ingest.command()
@click.argument("content")
@click.option("--title", "-t", default=None, help="Optional title for the text.")
def text(content: str, title: str | None) -> None:
    """Ingest raw text or a note."""
    payload: dict = {"content": content}
    if title:
        payload["title"] = title

    try:
        with get_client() as client:
            resp = client.post("/ingest/text", json=payload)
            handle_response_error(resp)
            data = resp.json()

        click.echo(f"Source ingested: {data.get('title', '(untitled)')}")
        click.echo(f"  ID:     {data.get('id', 'unknown')}")
        click.echo(f"  Status: {data.get('status', 'unknown')}")

    except httpx.ConnectError:
        click.echo(f"Error: Cannot connect to WikiMind server at {get_server_url()}", err=True)
        click.echo("Is the server running? Start it with 'make dev'.", err=True)
        raise SystemExit(1) from None
