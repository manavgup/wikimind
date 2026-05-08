"""Query commands — ask questions against the wiki."""

from __future__ import annotations

import click
import httpx

from wikimind.cli.client import get_client, get_server_url, handle_response_error


@click.command()
@click.argument("question")
@click.option(
    "--conversation",
    "-c",
    default=None,
    help="Conversation ID to continue (omit for new conversation).",
)
def ask(question: str, conversation: str | None) -> None:
    """Ask a question against the wiki."""
    payload: dict = {"question": question}
    if conversation:
        payload["conversation_id"] = conversation

    try:
        with get_client() as client:
            resp = client.post("/query", json=payload, timeout=120.0)
            handle_response_error(resp)
            data = resp.json()

        query_data = data.get("query", {})
        answer = query_data.get("answer", "No answer received.")
        confidence = query_data.get("confidence")
        conv_data = data.get("conversation", {})
        conv_id = conv_data.get("id")

        click.echo(answer)
        click.echo()
        if confidence:
            click.echo(f"Confidence: {confidence}")
        if conv_id:
            click.echo(f"Conversation: {conv_id}")

    except httpx.ConnectError:
        click.echo(f"Error: Cannot connect to WikiMind server at {get_server_url()}", err=True)
        click.echo("Is the server running? Start it with 'make dev'.", err=True)
        raise SystemExit(1) from None
