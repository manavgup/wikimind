"""Wiki commands — list, show, and delete articles."""

from __future__ import annotations

import click
import httpx

from wikimind.cli.client import get_client, get_server_url, handle_response_error


@click.group()
def wiki() -> None:
    """Browse and manage wiki articles."""


@wiki.command(name="list")
@click.option("--limit", "-n", default=50, help="Maximum number of articles to show.")
@click.option("--concept", "-c", default=None, help="Filter by concept.")
def list_articles(limit: int, concept: str | None) -> None:
    """List all wiki articles."""
    params: dict = {"limit": limit}
    if concept:
        params["concept"] = concept

    try:
        with get_client() as client:
            resp = client.get("/wiki/articles", params=params)
            handle_response_error(resp)
            articles = resp.json()

        if not articles:
            click.echo("No articles found.")
            return

        # Table header
        click.echo(f"{'SLUG':<40} {'TITLE':<40} {'TYPE':<10} {'SOURCES'}")
        click.echo("-" * 100)
        for article in articles:
            slug = article.get("slug", "")[:39]
            title = article.get("title", "")[:39]
            page_type = article.get("page_type", "")[:9]
            source_count = article.get("source_count", 0)
            click.echo(f"{slug:<40} {title:<40} {page_type:<10} {source_count}")

        click.echo(f"\n{len(articles)} article(s)")

    except httpx.ConnectError:
        click.echo(f"Error: Cannot connect to WikiMind server at {get_server_url()}", err=True)
        click.echo("Is the server running? Start it with 'make dev'.", err=True)
        raise SystemExit(1) from None


@wiki.command()
@click.argument("slug")
def show(slug: str) -> None:
    """Show the full content of an article by slug."""
    try:
        with get_client() as client:
            resp = client.get(f"/wiki/articles/{slug}")
            handle_response_error(resp)
            data = resp.json()

        title = data.get("title", slug)
        content = data.get("content", "")
        page_type = data.get("page_type", "unknown")
        concepts = ", ".join(data.get("concepts", []))

        click.echo(f"# {title}")
        click.echo(f"Type: {page_type}")
        if concepts:
            click.echo(f"Concepts: {concepts}")
        click.echo()
        click.echo(content)

    except httpx.ConnectError:
        click.echo(f"Error: Cannot connect to WikiMind server at {get_server_url()}", err=True)
        click.echo("Is the server running? Start it with 'make dev'.", err=True)
        raise SystemExit(1) from None


@wiki.command()
@click.argument("slug")
@click.confirmation_option(prompt="Are you sure you want to delete this article?")
def delete(slug: str) -> None:
    """Delete an article by slug.

    Note: This deletes the underlying source, not the article directly.
    The article is removed when its source is deleted.
    """
    try:
        with get_client() as client:
            # First, get the article to find its source IDs
            resp = client.get(f"/wiki/articles/{slug}")
            handle_response_error(resp)
            article = resp.json()

            source_ids = article.get("source_ids", [])
            if not source_ids:
                # Try getting source IDs from the sources list
                sources = article.get("sources", [])
                source_ids = [s.get("id") for s in sources if s.get("id")]

            if not source_ids:
                click.echo("Error: Article has no associated sources to delete.", err=True)
                raise SystemExit(1)

            # Delete each source
            for source_id in source_ids:
                resp = client.delete(f"/ingest/sources/{source_id}")
                handle_response_error(resp)

            click.echo(f"Deleted article '{slug}' and {len(source_ids)} source(s).")

    except httpx.ConnectError:
        click.echo(f"Error: Cannot connect to WikiMind server at {get_server_url()}", err=True)
        click.echo("Is the server running? Start it with 'make dev'.", err=True)
        raise SystemExit(1) from None
