# View Source Document Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users view the original source document (PDF, HTML) directly in the app without re-fetching, using format-specific viewers.

**Architecture:** A generic streaming endpoint serves original document binaries by detecting file siblings in `~/.wikimind/raw/`. The frontend renders PDFs via PDF.js and HTML in sandboxed iframes. A computed `has_original` field on API responses lets the UI conditionally show the "View Original" button.

**Tech Stack:** FastAPI StreamingResponse, `mimetypes` stdlib, `pdfjs-dist` npm package, sandboxed `<iframe>`.

**Spec:** `docs/superpowers/specs/2026-04-18-view-source-document-design.md`

---

### Task 1: Add `find_original_sibling` helper to storage layer

**Files:**
- Modify: `src/wikimind/storage.py`
- Test: `tests/unit/test_storage.py`

- [ ] **Step 1: Write failing tests for the new helper**

Add to `tests/unit/test_storage.py`:

```python
def test_find_original_sibling_finds_pdf(tmp_path: Path) -> None:
    """When a .pdf sibling exists alongside the .txt, return it."""
    (tmp_path / "abc.txt").write_text("extracted text")
    (tmp_path / "abc.pdf").write_bytes(b"%PDF-fake")
    result = find_original_sibling(tmp_path / "abc.txt")
    assert result is not None
    assert result.suffix == ".pdf"
    assert result.name == "abc.pdf"


def test_find_original_sibling_finds_html(tmp_path: Path) -> None:
    """When an .html sibling exists alongside the .txt, return it."""
    (tmp_path / "xyz.txt").write_text("extracted text")
    (tmp_path / "xyz.html").write_text("<html>hello</html>")
    result = find_original_sibling(tmp_path / "xyz.txt")
    assert result is not None
    assert result.suffix == ".html"


def test_find_original_sibling_returns_none_for_text_only(tmp_path: Path) -> None:
    """When only the .txt exists (text/YouTube sources), return None."""
    (tmp_path / "zzz.txt").write_text("plain text source")
    result = find_original_sibling(tmp_path / "zzz.txt")
    assert result is None


def test_find_original_sibling_returns_none_for_missing_file(tmp_path: Path) -> None:
    """When the txt file itself doesn't exist, return None."""
    result = find_original_sibling(tmp_path / "nonexistent.txt")
    assert result is None
```

Import at the top of the test file:
```python
from wikimind.storage import find_original_sibling
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_storage.py -k "find_original_sibling" -v`
Expected: FAIL — `ImportError: cannot import name 'find_original_sibling'`

- [ ] **Step 3: Implement `find_original_sibling`**

Add to `src/wikimind/storage.py` after the `resolve_raw_path` function (after line 157):

```python
def find_original_sibling(txt_path: Path) -> Path | None:
    """Find the non-.txt sibling of a raw source file.

    During ingest, adapters store both the cleaned text ({id}.txt) and the
    original binary ({id}.pdf, {id}.html).  This function locates the
    original by scanning the same directory for a file with the same stem
    but a different extension.

    Returns None if only the .txt exists (text/YouTube sources) or if
    the txt_path itself does not exist.
    """
    if not txt_path.exists():
        return None
    stem = txt_path.stem
    parent = txt_path.parent
    for sibling in parent.iterdir():
        if sibling.stem == stem and sibling.suffix != ".txt" and sibling.is_file():
            return sibling
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_storage.py -k "find_original_sibling" -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/wikimind/storage.py tests/unit/test_storage.py
git commit -m "feat: add find_original_sibling helper for original document lookup"
```

---

### Task 2: Add `has_original` computed field to Source API responses

**Files:**
- Modify: `src/wikimind/models.py`
- Modify: `apps/web/src/types/api.ts`
- Test: `tests/unit/test_models.py`

- [ ] **Step 1: Write failing test for `has_original` field**

Add to `tests/unit/test_models.py`:

```python
def test_source_has_original_true_when_pdf_sibling_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """has_original is True when a non-.txt sibling exists in raw/."""
    monkeypatch.setattr("wikimind.models.resolve_raw_path", lambda p: tmp_path / p)
    (tmp_path / "src-1.txt").write_text("text")
    (tmp_path / "src-1.pdf").write_bytes(b"%PDF")
    source = Source(id="src-1", source_type=SourceType.PDF, file_path="src-1.txt")
    assert source.has_original is True


def test_source_has_original_false_for_text_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """has_original is False when only the .txt exists."""
    monkeypatch.setattr("wikimind.models.resolve_raw_path", lambda p: tmp_path / p)
    (tmp_path / "src-2.txt").write_text("text")
    source = Source(id="src-2", source_type=SourceType.TEXT, file_path="src-2.txt")
    assert source.has_original is False


def test_source_has_original_false_when_no_file_path() -> None:
    """has_original is False when file_path is None."""
    source = Source(id="src-3", source_type=SourceType.TEXT)
    assert source.has_original is False
```

Import at top:
```python
from wikimind.models import Source, SourceType
from pathlib import Path
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_models.py -k "has_original" -v`
Expected: FAIL — `AttributeError: 'Source' object has no attribute 'has_original'`

- [ ] **Step 3: Add `has_original` computed property to Source model**

In `src/wikimind/models.py`, add import at top:

```python
from wikimind.storage import find_original_sibling, resolve_raw_path
```

Add the computed property to the `Source` class (after `content_hash` field):

```python
    @property
    def has_original(self) -> bool:
        """Whether the original document (PDF, HTML) exists alongside the .txt."""
        if not self.file_path:
            return False
        txt_path = resolve_raw_path(self.file_path)
        return find_original_sibling(txt_path) is not None
```

SQLModel uses Pydantic under the hood. To ensure the property is included in JSON serialization, add `model_config` to the Source class:

```python
    model_config = ConfigDict(
        # Include computed properties in serialization
        json_schema_extra=None,  # already present if exists
    )
```

**Note:** Check if Source already has `model_config`. If so, add to existing. If SQLModel doesn't serialize `@property`, use a `@computed_field` decorator from Pydantic v2 instead:

```python
from pydantic import computed_field

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_original(self) -> bool:
        """Whether the original document (PDF, HTML) exists alongside the .txt."""
        if not self.file_path:
            return False
        txt_path = resolve_raw_path(self.file_path)
        return find_original_sibling(txt_path) is not None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_models.py -k "has_original" -v`
Expected: 3 passed

- [ ] **Step 5: Add `has_original` to frontend TypeScript interface**

In `apps/web/src/types/api.ts`, add to the `Source` interface (after `file_path`):

```typescript
export interface Source {
  id: string;
  source_type: SourceType;
  source_url: string | null;
  title: string | null;
  author: string | null;
  published_date: string | null;
  status: IngestStatus;
  ingested_at: string;
  compiled_at: string | null;
  token_count: number | null;
  error_message: string | null;
  file_path: string | null;
  has_original: boolean;
}
```

- [ ] **Step 6: Commit**

```bash
git add src/wikimind/models.py apps/web/src/types/api.ts tests/unit/test_models.py
git commit -m "feat: add has_original computed field to Source model and TS interface"
```

---

### Task 3: Add `GET /ingest/sources/{id}/original` streaming endpoint

**Files:**
- Modify: `src/wikimind/api/routes/ingest.py`
- Test: `tests/unit/test_ingest_service.py` (or a new `tests/unit/test_ingest_routes.py`)

- [ ] **Step 1: Write failing test for the endpoint**

Add a new test file `tests/unit/test_view_original.py`:

```python
"""Tests for the GET /ingest/sources/{id}/original endpoint."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from wikimind.main import app
from wikimind.models import Source, SourceType


@pytest.fixture
def mock_session():
    return AsyncMock()


@pytest.fixture
def source_with_pdf():
    return Source(
        id="src-pdf",
        source_type=SourceType.PDF,
        file_path="src-pdf.txt",
        title="Test PDF",
    )


@pytest.fixture
def source_text_only():
    return Source(
        id="src-text",
        source_type=SourceType.TEXT,
        file_path="src-text.txt",
        title="Test Text",
    )


async def test_original_endpoint_streams_pdf(tmp_path: Path, source_with_pdf: Source) -> None:
    """Endpoint returns PDF bytes with correct Content-Type."""
    pdf_bytes = b"%PDF-1.4 fake pdf content"
    (tmp_path / "src-pdf.txt").write_text("extracted text")
    (tmp_path / "src-pdf.pdf").write_bytes(pdf_bytes)

    with (
        patch("wikimind.api.routes.ingest.get_session", return_value=AsyncMock()),
        patch("wikimind.api.routes.ingest.get_ingest_service") as mock_svc_dep,
        patch("wikimind.api.routes.ingest.resolve_raw_path", return_value=tmp_path / "src-pdf.txt"),
    ):
        mock_svc = AsyncMock()
        mock_svc.get_source = AsyncMock(return_value=source_with_pdf)
        mock_svc_dep.return_value = mock_svc

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/ingest/sources/src-pdf/original")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content == pdf_bytes


async def test_original_endpoint_404_for_text_source(tmp_path: Path, source_text_only: Source) -> None:
    """Endpoint returns 404 when no original sibling exists."""
    (tmp_path / "src-text.txt").write_text("just text")

    with (
        patch("wikimind.api.routes.ingest.get_session", return_value=AsyncMock()),
        patch("wikimind.api.routes.ingest.get_ingest_service") as mock_svc_dep,
        patch("wikimind.api.routes.ingest.resolve_raw_path", return_value=tmp_path / "src-text.txt"),
    ):
        mock_svc = AsyncMock()
        mock_svc.get_source = AsyncMock(return_value=source_text_only)
        mock_svc_dep.return_value = mock_svc

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/ingest/sources/src-text/original")

    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_view_original.py -v`
Expected: FAIL — 404 because route doesn't exist yet

- [ ] **Step 3: Implement the streaming endpoint**

In `src/wikimind/api/routes/ingest.py`, add imports:

```python
import mimetypes
from pathlib import Path

from fastapi.responses import StreamingResponse

from wikimind.storage import find_original_sibling, resolve_raw_path
```

Add the new route handler after the `delete_source` handler (after line 80):

```python
@router.get("/sources/{source_id}/original")
async def get_source_original(
    source_id: str,
    session: AsyncSession = Depends(get_session),
    service: IngestService = Depends(get_ingest_service),
):
    """Stream the original source document (PDF, HTML, etc.).

    Returns the raw binary stored during ingest — not the extracted text.
    Sources that have no original (text, YouTube) return 404.
    """
    source = await service.get_source(source_id, session)
    if not source.file_path:
        raise HTTPException(status_code=404, detail="No original document available")

    txt_path = resolve_raw_path(source.file_path)
    original = find_original_sibling(txt_path)
    if original is None:
        raise HTTPException(status_code=404, detail="No original document available")

    content_type, _ = mimetypes.guess_type(original.name)
    if content_type is None:
        content_type = "application/octet-stream"

    def iter_file():
        with open(original, "rb") as f:
            while chunk := f.read(64 * 1024):
                yield chunk

    return StreamingResponse(
        iter_file(),
        media_type=content_type,
        headers={"Content-Disposition": "inline"},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_view_original.py -v`
Expected: 2 passed

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `make verify`
Expected: All existing tests pass, lint clean

- [ ] **Step 6: Commit**

```bash
git add src/wikimind/api/routes/ingest.py tests/unit/test_view_original.py
git commit -m "feat: add GET /ingest/sources/{id}/original streaming endpoint"
```

---

### Task 4: Regenerate OpenAPI spec

**Files:**
- Regenerate: `docs/openapi.yaml`

- [ ] **Step 1: Export the updated OpenAPI spec**

Run: `make export-openapi`

- [ ] **Step 2: Verify docs are in sync**

Run: `make check-docs`
Expected: All checks pass

- [ ] **Step 3: Commit**

```bash
git add docs/openapi.yaml
git commit -m "docs: regenerate openapi.yaml with /original endpoint"
```

---

### Task 5: Install `pdfjs-dist` and add PDF viewer component

**Files:**
- Modify: `apps/web/package.json`
- Create: `apps/web/src/components/viewers/PdfViewer.tsx`

- [ ] **Step 1: Install pdfjs-dist**

```bash
cd apps/web && npm install pdfjs-dist && cd ../..
```

- [ ] **Step 2: Create the PdfViewer component**

Create `apps/web/src/components/viewers/PdfViewer.tsx`:

```tsx
import { useEffect, useRef, useState } from "react";
import * as pdfjsLib from "pdfjs-dist";
import { Spinner } from "../shared/Spinner";

// Use the bundled worker from pdfjs-dist
pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

interface PdfViewerProps {
  url: string;
}

export function PdfViewer({ url }: PdfViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pageCount, setPageCount] = useState(0);

  useEffect(() => {
    let cancelled = false;

    async function render() {
      try {
        const pdf = await pdfjsLib.getDocument(url).promise;
        if (cancelled) return;
        setPageCount(pdf.numPages);
        const container = containerRef.current;
        if (!container) return;
        container.innerHTML = "";

        for (let i = 1; i <= pdf.numPages; i++) {
          const page = await pdf.getPage(i);
          const viewport = page.getViewport({ scale: 1.5 });
          const canvas = document.createElement("canvas");
          canvas.width = viewport.width;
          canvas.height = viewport.height;
          canvas.style.display = "block";
          canvas.style.margin = "0 auto 16px auto";
          container.appendChild(canvas);
          const ctx = canvas.getContext("2d")!;
          await page.render({ canvasContext: ctx, viewport }).promise;
        }
        setLoading(false);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load PDF");
          setLoading(false);
        }
      }
    }

    render();
    return () => {
      cancelled = true;
    };
  }, [url]);

  if (error) {
    return (
      <div className="flex items-center justify-center p-8 text-rose-600">
        {error}
      </div>
    );
  }

  return (
    <div className="relative h-full overflow-auto bg-slate-100">
      {loading && (
        <div className="flex items-center justify-center p-8">
          <Spinner size={24} />
          <span className="ml-2 text-sm text-slate-500">Loading PDF...</span>
        </div>
      )}
      <div ref={containerRef} className="p-4" />
      {!loading && pageCount > 0 && (
        <div className="sticky bottom-0 bg-white/80 px-4 py-2 text-center text-xs text-slate-500 backdrop-blur">
          {pageCount} page{pageCount !== 1 ? "s" : ""}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Verify it compiles**

Run: `cd apps/web && npx tsc --noEmit && cd ../..`
Expected: No type errors

- [ ] **Step 4: Commit**

```bash
git add apps/web/package.json apps/web/package-lock.json apps/web/src/components/viewers/PdfViewer.tsx
git commit -m "feat(web): add PdfViewer component using pdfjs-dist"
```

---

### Task 6: Add HtmlViewer and DownloadFallback components

**Files:**
- Create: `apps/web/src/components/viewers/HtmlViewer.tsx`
- Create: `apps/web/src/components/viewers/DownloadFallback.tsx`

- [ ] **Step 1: Create the HtmlViewer component**

Create `apps/web/src/components/viewers/HtmlViewer.tsx`:

```tsx
interface HtmlViewerProps {
  url: string;
}

export function HtmlViewer({ url }: HtmlViewerProps) {
  return (
    <iframe
      src={url}
      sandbox="allow-same-origin"
      title="Source document"
      className="h-full w-full border-0"
    />
  );
}
```

Note: We use `src={url}` (pointing at the streaming endpoint) instead of `srcdoc` so the browser fetches the HTML directly — no need to load it into JS memory first.

- [ ] **Step 2: Create the DownloadFallback component**

Create `apps/web/src/components/viewers/DownloadFallback.tsx`:

```tsx
import { Button } from "../shared/Button";

interface DownloadFallbackProps {
  url: string;
  filename: string;
}

export function DownloadFallback({ url, filename }: DownloadFallbackProps) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 p-8">
      <p className="text-sm text-slate-500">
        This file type cannot be previewed in the browser.
      </p>
      <Button
        as="a"
        href={url}
        download={filename}
        variant="primary"
        size="sm"
      >
        Download original
      </Button>
    </div>
  );
}
```

- [ ] **Step 3: Verify both compile**

Run: `cd apps/web && npx tsc --noEmit && cd ../..`
Expected: No type errors (if `Button` doesn't support `as="a"`, adjust to a plain `<a>` tag styled as a button)

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/components/viewers/HtmlViewer.tsx apps/web/src/components/viewers/DownloadFallback.tsx
git commit -m "feat(web): add HtmlViewer and DownloadFallback viewer components"
```

---

### Task 7: Add DocumentViewerModal and wire into SourceCard

**Files:**
- Create: `apps/web/src/components/viewers/DocumentViewerModal.tsx`
- Modify: `apps/web/src/components/inbox/SourceCard.tsx`
- Modify: `apps/web/src/api/client.ts` (add helper to build original URL)

- [ ] **Step 1: Add `getOriginalUrl` helper to API client**

In `apps/web/src/api/sources.ts`, add:

```typescript
import { getBaseUrl } from "./client";

export function getOriginalUrl(sourceId: string): string {
  return `${getBaseUrl()}/ingest/sources/${encodeURIComponent(sourceId)}/original`;
}
```

- [ ] **Step 2: Create the DocumentViewerModal**

Create `apps/web/src/components/viewers/DocumentViewerModal.tsx`:

```tsx
import type { SourceType } from "../../types/api";
import { Button } from "../shared/Button";
import { DownloadFallback } from "./DownloadFallback";
import { HtmlViewer } from "./HtmlViewer";
import { PdfViewer } from "./PdfViewer";

interface DocumentViewerModalProps {
  sourceId: string;
  sourceType: SourceType;
  title: string;
  url: string;
  onClose: () => void;
}

const INLINE_VIEWERS: Record<string, React.FC<{ url: string }>> = {
  pdf: PdfViewer,
  url: HtmlViewer,
};

export function DocumentViewerModal({
  sourceType,
  title,
  url,
  onClose,
}: DocumentViewerModalProps) {
  const Viewer = INLINE_VIEWERS[sourceType];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="flex h-[90vh] w-[90vw] flex-col rounded-lg border border-slate-200 bg-white shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-200 px-6 py-3">
          <h2 className="truncate text-lg font-semibold text-slate-800">
            {title}
          </h2>
          <Button variant="ghost" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>

        {/* Viewer area */}
        <div className="flex-1 overflow-hidden">
          {Viewer ? (
            <Viewer url={url} />
          ) : (
            <DownloadFallback url={url} filename={title} />
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Wire "View Original" button into SourceCard**

Modify `apps/web/src/components/inbox/SourceCard.tsx`:

Add imports at top:

```typescript
import { useState } from "react";
import { getOriginalUrl } from "../../api/sources";
import { DocumentViewerModal } from "../viewers/DocumentViewerModal";
```

Change the `useMemo` import line to also import `useState`:
```typescript
import { useMemo, useState } from "react";
```

Inside the `SourceCard` component, add state and handler before the return:

```typescript
const [viewerOpen, setViewerOpen] = useState(false);
```

Add the "View Original" button and modal inside the `<Card>`, after the status/retry section (before `</Card>`):

```tsx
{source.has_original ? (
  <>
    <div className="mt-3">
      <Button
        size="sm"
        variant="secondary"
        onClick={() => setViewerOpen(true)}
      >
        View Original
      </Button>
    </div>
    {viewerOpen ? (
      <DocumentViewerModal
        sourceId={source.id}
        sourceType={source.source_type}
        title={source.title ?? "Source document"}
        url={getOriginalUrl(source.id)}
        onClose={() => setViewerOpen(false)}
      />
    ) : null}
  </>
) : null}
```

- [ ] **Step 4: Verify frontend compiles and type-checks**

Run: `cd apps/web && npx tsc --noEmit && cd ../..`
Expected: No type errors

- [ ] **Step 5: Verify frontend builds**

Run: `cd apps/web && npm run build && cd ../..`
Expected: Build succeeds

- [ ] **Step 6: Commit**

```bash
git add apps/web/src/api/sources.ts apps/web/src/components/viewers/DocumentViewerModal.tsx apps/web/src/components/inbox/SourceCard.tsx
git commit -m "feat(web): add DocumentViewerModal and View Original button on SourceCard"
```

---

### Task 8: Final verification

**Files:** None (verification only)

- [ ] **Step 1: Run backend quality checks**

Run: `make verify`
Expected: All lint, format, typecheck, and tests pass

- [ ] **Step 2: Run frontend quality checks**

Run: `make frontend-verify`
Expected: All frontend checks pass

- [ ] **Step 3: Regenerate docs if needed**

Run: `make check-docs`
If any failures: `make regenerate-docs` then commit

- [ ] **Step 4: Manual smoke test**

1. Start the dev server: `make dev`
2. In another terminal: `cd apps/web && npm run dev`
3. Ingest a PDF via the UI → verify "View Original" button appears → click it → PDF.js viewer opens in full-screen modal
4. Ingest a URL → verify "View Original" button appears → click it → HTML renders in sandboxed iframe
5. Ingest plain text → verify no "View Original" button shown
6. Close the viewer modal → verify app returns to normal state

- [ ] **Step 5: Create final commit if any remaining changes**

```bash
git add -A
git commit -m "chore: final cleanup for view source document feature"
```
