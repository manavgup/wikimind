# ADR-026: Article Export Layer (PDF, LinkedIn, Slides)

**Status:** Accepted
**Date:** 2026-04-21

## Context

Users need to share or repurpose wiki article content outside WikiMind. Three initial export formats were identified:

1. **PDF** — clean, printable documents for offline reading or sharing.
2. **LinkedIn** — professional social posts derived from article insights.
3. **Slides** — presentation decks for meetings or talks.

The key design tension is between output quality and dependency weight. Full PDF rendering (e.g., weasyprint, Playwright) pulls in heavy native dependencies (Cairo, Pango, or Chromium), increasing image size and CI time — the same problem solved by ADR-025 for Docling.

## Decision

Implement a lightweight export layer with the following approach:

- **PDF**: Convert article markdown to styled HTML using a built-in markdown-to-HTML converter and a print-friendly CSS template. The HTML can be opened in any browser and printed to PDF. No heavy dependencies required. An optional `[export]` extras group in pyproject.toml is reserved for future heavier renderers (e.g., weasyprint).

- **LinkedIn / Slides**: Use the existing LLM router to rewrite article content into the target format. LinkedIn posts follow a hook-insight-CTA structure capped at 300 words. Slides produce Marp-compatible markdown that can be rendered by any Marp-compatible tool.

Architecture:
- `ExportService` in `src/wikimind/services/export.py` owns all transformation logic.
- `POST /wiki/articles/{id_or_slug}/export?format=<pdf|linkedin|slides>` is the single endpoint.
- PDF returns `text/html`; LinkedIn and slides return JSON with the generated text.
- LLM calls are tracked under `TaskType.EXPORT` for cost visibility.

## Consequences

### Positive

- Zero new runtime dependencies for the base install.
- PDF export works immediately without native library installation.
- LinkedIn and slides leverage existing LLM infrastructure with cost tracking.
- The `[export]` extras group provides a clean upgrade path for server-side PDF rendering.

### Negative

- PDF output is HTML, not a true PDF binary — users must use browser print-to-PDF for the final .pdf file.
- The built-in markdown-to-HTML converter handles common patterns but is not a full CommonMark parser; edge cases in complex article formatting may render imperfectly.

### Neutral

- LinkedIn and slides quality depends on the configured LLM provider's capabilities.
- Marp slides require a Marp-compatible renderer (VS Code extension, marp-cli, or marp.app) to preview.
