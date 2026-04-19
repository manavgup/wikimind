# View Source Document — Design Spec

**Date:** 2026-04-18
**Issue:** #177
**Replaces:** PR #179 (will be closed)

## Problem

When a user ingests a PDF, URL, or other document into WikiMind, they can see the compiled wiki article but cannot view the original source document without leaving the app or re-fetching from the internet. The original files are already stored on disk (`~/.wikimind/raw/{id}.pdf`, `{id}.html`) but there's no API to serve them or UI to display them.

## Design

### Backend

**New endpoint:** `GET /ingest/sources/{id}/original`

Serves the original document binary with the correct Content-Type. Generic — works for any file format stored during ingest.

**Behavior by source type:**

| Source type | File on disk | Content-Type | Response |
|---|---|---|---|
| PDF | `{id}.pdf` | `application/pdf` | StreamingResponse of PDF bytes |
| URL | `{id}.html` | `text/html` | StreamingResponse of HTML bytes |
| Text | none | n/a | 404: no original document |
| YouTube | none | n/a | 404: no original document |
| Future (DOCX, PPTX, etc.) | `{id}.{ext}` | auto-detected via `mimetypes` | StreamingResponse |

**Implementation details:**
- Resolves the original file by checking for non-`.txt` siblings of `Source.file_path` in the raw directory
- Uses `mimetypes.guess_type()` for Content-Type, so future formats work without code changes
- Uses `StreamingResponse` to avoid loading large files into memory
- File I/O via `asyncio.to_thread()` for async safety
- Returns `Content-Disposition: inline` (display in browser, not download)

**New field on Source response:** `has_original: bool` — computed from whether a non-`.txt` sibling file exists. Added to the Source Pydantic response model so the frontend knows which button to show without an extra round-trip.

**Files to modify:**
- `src/wikimind/api/routes/ingest.py` — new route handler
- `src/wikimind/models.py` — add `has_original` to the response schema
- `src/wikimind/storage.py` — helper to find original file sibling

### Frontend

**"View Original" button** on each source card in the Inbox, visible only when `has_original` is true.

**Format-specific viewers (all full-screen modals, ~90vh x 90vw):**

1. **PDF viewer** — embed [PDF.js](https://mozilla.github.io/pdf.js/) via `pdfjs-dist` npm package. Render in an `<iframe>` or `<canvas>` inside the modal. Provides search, zoom, and page navigation out of the box.

2. **HTML viewer** — render the stored `.html` in a sandboxed `<iframe>`:
   ```html
   <iframe
     sandbox="allow-same-origin"
     srcdoc={htmlContent}
     style="width: 100%; height: 100%"
   />
   ```
   No `allow-scripts` — prevents XSS from third-party HTML. Styling may degrade without external CSS/images, which is acceptable.

3. **Fallback (future formats)** — for formats the browser can't render (DOCX, PPTX), show a download button instead of an inline viewer.

**For sources without originals** (text, YouTube): no "View Original" button is shown. These source types don't have a separate original document.

**Component structure:**
```
SourceCard
├── ViewOriginalButton (conditional on has_original)
└── DocumentViewerModal
    ├── PdfViewer (source_type === "pdf")
    ├── HtmlViewer (source_type === "url")
    └── DownloadFallback (unknown types)
```

**New npm dependency:** `pdfjs-dist` (~500KB, Mozilla's official PDF.js distribution for npm).

### What this does NOT include

- **Extracted text viewer** — PR #179's text modal is dropped. The extracted text is already visible in the compiled wiki article. If needed later, it can be added as a separate "View Extracted Text" option.
- **Re-fetching from the internet** — this only serves locally stored files, never re-downloads.
- **Editing or annotating** — view-only.
- **Per-page image extraction viewer** — that's the existing FiguresPanel (issue #142), separate from this feature.

### Security

- HTML rendered in `sandbox="allow-same-origin"` iframe — no script execution
- PDF rendered via PDF.js — no native browser plugin vulnerabilities
- StreamingResponse prevents memory exhaustion on large files
- No user-uploaded filenames in responses (uses source_id, not original filename)

### Error handling

- Source not found → 404
- No original file on disk → 404 with `"No original document available"`
- File read error → 500

## Verification

- Ingest a PDF → "View Original" button appears → opens PDF.js viewer in modal
- Ingest a URL → "View Original" button appears → opens HTML in sandboxed iframe
- Ingest plain text → no "View Original" button shown
- Ingest a YouTube URL → no "View Original" button shown
- Large PDF (50+ pages) → streams without memory issues
- HTML with `<script>` tags → scripts do not execute in sandbox
