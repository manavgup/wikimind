#!/usr/bin/env python3
"""Run a single (provider x document x question) test against the WikiMind API.

Usage:
    python scripts/run_test_matrix.py \
        --doc /path/to/file.pdf \
        --question "What is X?" \
        --provider anthropic \
        --doc-type "slide-deck" \
        --output docs/test-matrix-results.md

The script:
1. Verifies the API is up at localhost:7842 (or --base-url).
2. Verifies the requested provider is configured and enabled.
3. Ingests the document (URL, PDF, or text file).
4. Polls until compilation completes or fails (max --timeout seconds).
5. Records compilation latency and the LLM cost delta from /settings/llm/cost.
6. Asks the question via POST /query and records answer length and citation count.
7. Appends a row to the markdown results table at --output.

The user grades quality (Accuracy / Attribution / Completeness / Calibration)
manually by editing the markdown table after the script writes the row.

This script intentionally has no third-party dependencies beyond ``httpx``
which is already a WikiMind runtime dependency. It is a CLI entry point,
not a library, so it does not ship with pytest tests.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://localhost:7842"
DEFAULT_OUTPUT = Path("docs/test-matrix-results.md")
DEFAULT_TIMEOUT_SECONDS = 300
POLL_INTERVAL_SECONDS = 2.0
HTTP_REQUEST_TIMEOUT_SECONDS = 60.0
VALID_PROVIDERS = ("anthropic", "openai", "google", "ollama")
URL_SCHEMES = ("http://", "https://")
RESULTS_TABLE_HEADER = (
    "| Date | Provider | Doc Type | Doc | Latency | Cost | Citations | "
    "Accuracy | Attribution | Completeness | Calibration | Notes |"
)


class MatrixRunError(RuntimeError):
    """Raised when a matrix run cannot complete successfully."""


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for a single matrix run."""
    parser = argparse.ArgumentParser(
        description="Run a single WikiMind LLM x document type benchmark entry.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--doc",
        required=True,
        help="Path to a PDF or text file, or an http(s) URL to ingest.",
    )
    parser.add_argument(
        "--doc-type",
        required=True,
        help="Short label for the document type (e.g. 'slide-deck', 'academic-paper').",
    )
    parser.add_argument(
        "--question",
        required=True,
        help="The ground-truth question to ask after compilation.",
    )
    parser.add_argument(
        "--provider",
        required=True,
        choices=VALID_PROVIDERS,
        help="LLM provider to use for compile + Q&A. Must be enabled in /settings.",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"WikiMind gateway base URL (default: {DEFAULT_BASE_URL}).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Markdown file to append results to (default: {DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Compilation poll timeout in seconds (default: {DEFAULT_TIMEOUT_SECONDS}).",
    )
    return parser.parse_args()


def verify_api_up(client: httpx.Client) -> None:
    """Confirm the WikiMind gateway responds at /health."""
    try:
        response = client.get("/health")
    except httpx.HTTPError as exc:
        raise MatrixRunError(f"Cannot reach gateway at {client.base_url}: {exc}") from exc
    if response.status_code != httpx.codes.OK:
        raise MatrixRunError(f"Gateway /health returned HTTP {response.status_code}: {response.text}")


def verify_provider_enabled(client: httpx.Client, provider: str) -> None:
    """Confirm the requested provider is configured and enabled in /settings."""
    response = client.get("/settings")
    if response.status_code != httpx.codes.OK:
        raise MatrixRunError(f"GET /settings returned HTTP {response.status_code}: {response.text}")
    payload = response.json()
    providers = payload.get("llm", {}).get("providers", {})
    info = providers.get(provider)
    if info is None:
        raise MatrixRunError(f"Provider '{provider}' not present in /settings response.")
    if not info.get("configured"):
        raise MatrixRunError(
            f"Provider '{provider}' has no API key configured. "
            f"Set it in .env or via POST /settings/llm/api-key and restart the gateway."
        )
    if not info.get("enabled"):
        raise MatrixRunError(f"Provider '{provider}' is not enabled in settings. Enable it before running the matrix.")


def get_cost_total(client: httpx.Client) -> float:
    """Return the current month-to-date LLM cost in USD."""
    response = client.get("/settings/llm/cost")
    if response.status_code != httpx.codes.OK:
        raise MatrixRunError(f"GET /settings/llm/cost returned HTTP {response.status_code}: {response.text}")
    payload = response.json()
    return float(payload.get("cost_this_month_usd", 0.0))


def ingest_document(client: httpx.Client, doc: str) -> dict[str, Any]:
    """Ingest the document and return the created Source row.

    The doc may be an http(s) URL, a path to a .pdf file, or a path to any
    other text file (treated as raw text). Returns the Source dict from the
    API response.
    """
    if doc.startswith(URL_SCHEMES):
        response = client.post("/ingest/url", json={"url": doc, "auto_compile": True})
    else:
        path = Path(doc).expanduser()
        if not path.exists():
            raise MatrixRunError(f"Document not found: {path}")
        if path.suffix.lower() == ".pdf":
            with path.open("rb") as handle:
                files = {"file": (path.name, handle, "application/pdf")}
                response = client.post("/ingest/pdf", files=files)
        else:
            content = path.read_text(encoding="utf-8")
            response = client.post(
                "/ingest/text",
                json={"content": content, "title": path.name, "auto_compile": True},
            )
    if response.status_code != httpx.codes.OK:
        raise MatrixRunError(f"Ingest failed (HTTP {response.status_code}): {response.text}")
    return response.json()


def poll_until_compiled(client: httpx.Client, source_id: str, timeout: int) -> dict[str, Any]:
    """Poll GET /ingest/sources/{id} until the source compiles or fails."""
    deadline = time.monotonic() + timeout
    last_status = "unknown"
    while time.monotonic() < deadline:
        response = client.get(f"/ingest/sources/{source_id}")
        if response.status_code != httpx.codes.OK:
            raise MatrixRunError(
                f"GET /ingest/sources/{source_id} returned HTTP {response.status_code}: {response.text}"
            )
        source = response.json()
        last_status = source.get("status", "unknown")
        if last_status == "compiled":
            return source
        if last_status == "failed":
            raise MatrixRunError(
                f"Compilation failed for source {source_id}: {source.get('error_message', '(no message)')}"
            )
        time.sleep(POLL_INTERVAL_SECONDS)
    raise MatrixRunError(f"Compilation did not complete within {timeout}s (last status: {last_status}).")


def ask_question(client: httpx.Client, question: str) -> dict[str, Any]:
    """POST /query with the given question and return the response payload."""
    response = client.post("/query", json={"question": question, "file_back": False})
    if response.status_code != httpx.codes.OK:
        raise MatrixRunError(f"POST /query returned HTTP {response.status_code}: {response.text}")
    return response.json()


def format_doc_label(doc: str) -> str:
    """Return a short, table-friendly label for the document column."""
    if doc.startswith(URL_SCHEMES):
        return doc
    return Path(doc).name


def ensure_results_file(output: Path) -> None:
    """Create the results file with table headers if it does not yet exist.

    The file is normally created up-front by hand from the template, but this
    helper makes the script self-bootstrapping for ad-hoc runs.
    """
    if output.exists():
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "# WikiMind Test Matrix Results\n\n"
        "Auto-bootstrapped by scripts/run_test_matrix.py. "
        "See docs/test-matrix-results.md template for the full methodology.\n\n"
        "## Results\n\n"
        f"{RESULTS_TABLE_HEADER}\n"
        "|------|----------|----------|-----|---------|------|-----------|"
        "----------|-------------|--------------|-------------|-------|\n",
        encoding="utf-8",
    )


def append_result_row(output: Path, row: str) -> None:
    """Append a single markdown table row to the results file."""
    ensure_results_file(output)
    with output.open("a", encoding="utf-8") as handle:
        handle.write(row.rstrip() + "\n")


def build_row(
    *,
    provider: str,
    doc_type: str,
    doc_label: str,
    latency_seconds: float,
    cost_delta_usd: float,
    citation_count: int,
) -> str:
    """Build the markdown row that the script appends to the results table.

    Quality columns (Accuracy / Attribution / Completeness / Calibration) are
    left blank for the user to grade by hand after the run.
    """
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    return (
        f"| {today} | {provider} | {doc_type} | {doc_label} | "
        f"{latency_seconds:.1f}s | ${cost_delta_usd:.4f} | {citation_count} | "
        "| | | | |"
    )


def run_matrix_entry(args: argparse.Namespace) -> int:
    """Execute a single matrix entry end-to-end and append a row to the output."""
    with httpx.Client(base_url=args.base_url, timeout=HTTP_REQUEST_TIMEOUT_SECONDS) as client:
        verify_api_up(client)
        verify_provider_enabled(client, args.provider)

        cost_before = get_cost_total(client)
        start = time.monotonic()
        source = ingest_document(client, args.doc)
        source_id = source["id"]
        print(f"[matrix] ingested source {source_id}, polling for compilation...", file=sys.stderr)

        poll_until_compiled(client, source_id, args.timeout)
        latency_seconds = time.monotonic() - start
        print(f"[matrix] compiled in {latency_seconds:.1f}s, asking question...", file=sys.stderr)

        query_response = ask_question(client, args.question)
        cost_after = get_cost_total(client)

    citations = query_response.get("citations") or []
    citation_count = len(citations)
    cost_delta = max(0.0, cost_after - cost_before)

    row = build_row(
        provider=args.provider,
        doc_type=args.doc_type,
        doc_label=format_doc_label(args.doc),
        latency_seconds=latency_seconds,
        cost_delta_usd=cost_delta,
        citation_count=citation_count,
    )
    append_result_row(args.output, row)

    summary = {
        "provider": args.provider,
        "doc_type": args.doc_type,
        "doc": args.doc,
        "latency_seconds": round(latency_seconds, 2),
        "cost_delta_usd": round(cost_delta, 6),
        "citation_count": citation_count,
        "answer_length_chars": len(query_response.get("answer", "")),
        "confidence": query_response.get("confidence"),
        "appended_to": str(args.output),
    }
    print(json.dumps(summary, indent=2))
    return 0


def main() -> int:
    """Script entry point — parses args, runs one matrix entry, returns exit code."""
    args = parse_args()
    try:
        return run_matrix_entry(args)
    except MatrixRunError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
