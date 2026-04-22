# Browser Extension — Chrome + Firefox Web Clipper

## Problem

WikiMind users must manually copy URLs into the web UI or use the API to ingest content. There is no way to clip a page directly from the browser. Issue #30 requests a one-click web clipper extension that sends the current page to WikiMind's ingest endpoint.

## Decision

Build a Manifest V3 browser extension (Chrome + Firefox compatible) that lives at `apps/web-extension/`. The extension is a **popup-only** architecture — no content scripts, no context menu. The user clicks the extension icon, sees the current page URL, clicks "Clip this page", and the extension POSTs the URL to the backend's `/ingest/url` endpoint.

### Key choices

| Decision | Choice | Rationale |
|----------|--------|-----------|
| UI framework | Preact (~3KB) | Same JSX DX as React, 1/10 the bundle. Extension popup needs instant rendering. |
| Build tool | Vite + TypeScript | Matches `apps/web/` conventions. Type safety with `@types/chrome`. |
| Extraction | URL-only to backend | Backend already has trafilatura/docling. No Readability.js needed. |
| Offline support | Simple retry (3 attempts, exponential backoff) | No IndexedDB queue. User sees error if gateway is unreachable after retries. |
| Auth | None in V1 | Default single-user mode has auth disabled. |
| CORS | No backend changes | MV3 extension contexts are not subject to web CORS restrictions. |
| Permissions | `activeTab` + `storage` only | No broad host permissions. `activeTab` grants tab URL access on user click. |

### What this is not

- Not a full browser app — it's a lightweight popup (~10KB bundled)
- Not a content script injection — no page modification, no DOM reading
- Not offline-capable — retries on failure, but does not persist a sync queue

## Architecture

```
┌─────────────────────────────────────────┐
│  Browser Extension (MV3)                │
│                                         │
│  ┌───────────┐    ┌──────────────────┐  │
│  │  Popup    │───▶│  lib/api.ts      │──┼──▶ POST /ingest/url
│  │  (Preact) │    │  (fetch + retry) │  │    GET  /ingest/sources/{id}
│  └───────────┘    └──────────────────┘  │
│       │                                 │
│       │ chrome.runtime.sendMessage      │
│       ▼                                 │
│  ┌──────────────────┐                   │
│  │ Service Worker    │                  │
│  │ (badge updates)   │                  │
│  └──────────────────┘                   │
│                                         │
│  chrome.storage.local                   │
│  ├── gatewayUrl: "http://localhost:7842" │
│  └── recentClips: ClipRecord[]          │
└─────────────────────────────────────────┘
```

### User flow

1. User navigates to an article
2. Clicks the WikiMind extension icon → popup opens
3. Popup reads current tab URL via `chrome.tabs.query({active: true, currentWindow: true})`
4. User clicks "Clip this page"
5. Extension POSTs `{url, auto_compile: true}` to `/ingest/url`
6. On success: badge shows green checkmark (3s), clip saved to recent list
7. On failure: retry up to 3x with exponential backoff (500ms, 1s, 2s), then show error

### API surface used

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/ingest/url` | Ingest a URL (body: `{url: string, auto_compile: boolean}`) |
| GET | `/ingest/sources/{id}` | Poll compilation status |
| GET | `/ingest/sources?limit=5` | Populate recent clips from backend |

Response shape (`Source`):
```typescript
interface Source {
  id: string;
  source_type: string;
  source_url: string | null;
  title: string | null;
  status: "pending" | "processing" | "compiled" | "failed";
  ingested_at: string;
  compiled_at: string | null;
  error_message: string | null;
}
```

## File Structure

```
apps/web-extension/
├── package.json              # @wikimind/web-extension, Preact, Vite, Vitest
├── manifest.json             # MV3: activeTab + storage, popup + service worker
├── vite.config.ts            # Popup build (HTML entry)
├── vite.config.sw.ts         # Service worker build (IIFE output)
├── vitest.config.ts          # jsdom + chrome mock setup
├── tsconfig.json             # Strict, jsxImportSource: "preact", types: ["chrome"]
├── src/
│   ├── types.ts              # Source, IngestURLRequest, ClipRecord, ExtensionSettings
│   ├── test-setup.ts         # Mock chrome.* globals for Vitest
│   ├── popup/
│   │   ├── popup.html        # Entry point (360px fixed width)
│   │   ├── popup.tsx         # Preact render mount
│   │   └── components/
│   │       ├── App.tsx       # Root: tab URL, clip state machine, view routing
│   │       ├── ClipButton.tsx    # State-driven button (idle/clipping/success/error)
│   │       ├── StatusBadge.tsx   # Source status pill (pending/compiled/failed)
│   │       ├── RecentClips.tsx   # Last 5 clips from storage
│   │       └── Settings.tsx      # Gateway URL input + save
│   ├── background/
│   │   └── service-worker.ts # Badge management (green ✓ / red !)
│   └── lib/
│       ├── api.ts            # WikiMind API client (clipUrl, getSource, listRecentSources)
│       ├── storage.ts        # Typed chrome.storage.local wrapper
│       ├── retry.ts          # withRetry<T> — exponential backoff, retry on 5xx/network
│       └── __tests__/
│           ├── retry.test.ts
│           ├── api.test.ts
│           └── storage.test.ts
├── public/
│   └── icons/                # 16, 48, 128px PNGs
└── dist/                     # Build output (gitignored)
```

## Implementation Detail

### manifest.json

```json
{
  "manifest_version": 3,
  "name": "WikiMind Clipper",
  "version": "0.1.0",
  "description": "One-click web clipper for WikiMind",
  "permissions": ["activeTab", "storage"],
  "action": {
    "default_popup": "popup.html",
    "default_icon": {
      "16": "icons/icon-16.png",
      "48": "icons/icon-48.png",
      "128": "icons/icon-128.png"
    }
  },
  "background": {
    "service_worker": "service-worker.js"
  },
  "icons": {
    "16": "icons/icon-16.png",
    "48": "icons/icon-48.png",
    "128": "icons/icon-128.png"
  }
}
```

### Build strategy

Two-pass Vite build (MV3 service workers cannot use ES modules):

1. **Popup build** (`vite.config.ts`): Standard HTML entry → `dist/popup.html` + JS/CSS chunks
2. **Service worker build** (`vite.config.sw.ts`): TS entry → `dist/service-worker.js` as IIFE format (`emptyOutDir: false` preserves popup output)
3. **Copy step**: `manifest.json` + `public/icons/` → `dist/`

```json
{
  "scripts": {
    "dev": "npm run build:popup -- --watch & npm run build:sw -- --watch",
    "build": "npm run build:popup && npm run build:sw && npm run copy:manifest",
    "build:popup": "vite build",
    "build:sw": "vite build --config vite.config.sw.ts",
    "copy:manifest": "cp manifest.json dist/manifest.json && cp -r public/icons dist/icons",
    "lint": "eslint src/ --ext .ts,.tsx",
    "typecheck": "tsc --noEmit",
    "test": "vitest run"
  }
}
```

### Core library

**`lib/retry.ts`** — Generic `withRetry<T>(fn, opts)`:
- Max 3 attempts, 500ms base delay, exponential backoff
- Retries on: HTTP 5xx, network errors (fetch TypeError)
- Does NOT retry: 4xx client errors

**`lib/api.ts`** — Thin client:
- Reads `gatewayUrl` from storage, strips trailing slash
- `clipUrl(url)` → POST `/ingest/url` with retry wrapper
- `getSource(id)` → GET `/ingest/sources/{id}`
- `listRecentSources(limit)` → GET `/ingest/sources?limit=N`
- Error parsing matches backend format: `{ error: { code, message, request_id } }`

**`lib/storage.ts`** — Typed `chrome.storage.local` wrapper:
- `getSettings()` → `{ gatewayUrl }` (default: `http://localhost:7842`)
- `setGatewayUrl(url)` → persists user-configured gateway
- `getRecentClips()` / `addRecentClip(clip)` → manages clip history (capped at 20)
- `updateClipStatus(sourceId, status)` → updates status in-place

### Popup components

**`App.tsx`** — Root component with two views (main / settings) and a clip state machine:
- States: `idle` → `clipping` → `success` | `error`
- On mount: reads current tab URL + loads recent clips from storage
- On clip: calls `clipUrl()`, stores result, messages service worker for badge update
- Disables clip button for `chrome://`, `edge://`, `about:` URLs

**`ClipButton.tsx`** — Full-width button, state-driven:
- idle: "Clip this page" (indigo `#6366f1`)
- clipping: "Clipping..." (disabled)
- success: "Clipped!" (green `#22c55e`)
- error: "Retry" (red `#ef4444`)

**`RecentClips.tsx`** — Shows last 5 clips: truncated URL, status badge, relative time

**`Settings.tsx`** — Gateway URL input with save button

### Service worker

Minimal — listens for `clip:success` / `clip:error` messages from popup, sets badge text. Green ✓ for 3s on success, red ! for 5s on error. No persistent state, no alarms, no long-lived operations.

### MV3 lifecycle considerations

- Service workers terminate after ~30s of inactivity — all state goes through `chrome.storage.local`
- `setTimeout` in message handlers is fine (handler keeps SW alive for the callback duration)
- Future status polling would need `chrome.alarms` (minimum 1-min granularity)

## Repo Integration

### Makefile changes

Insert after the Desktop section (line 217):

```makefile
##@ 🌐 BROWSER EXTENSION

.PHONY: extension-install
extension-install: ## Install browser extension dependencies
	cd apps/web-extension && npm install

.PHONY: extension-dev
extension-dev: ## Build extension with watch mode for development
	cd apps/web-extension && npm run dev

.PHONY: extension-build
extension-build: ## Build browser extension for production
	cd apps/web-extension && npm run build

.PHONY: extension-verify
extension-verify: ## Run extension quality checks (typecheck + build)
	@cd apps/web-extension && [ -d node_modules ] || npm install
	cd apps/web-extension && npm run typecheck && npm run build
```

Update `verify` target (line 178) to include `extension-verify`.

### .gitignore

Add `node_modules/` (currently missing — needed for all `apps/*/` directories).

### README.md

- Add `apps/web-extension/` to the Architecture tree (line 153)
- Add browser extension section under Make targets
- Add browser extension row to Tech stack table

## Testing Strategy

### Unit tests (Vitest)

- `retry.test.ts`: success, retry on 5xx, no retry on 4xx, network errors, maxAttempts, backoff timing
- `api.test.ts`: URL construction, error parsing, mock fetch + storage
- `storage.test.ts`: defaults, addRecentClip caps at 20, updateClipStatus

### Manual smoke test

1. `make extension-build` — builds without errors
2. Load `apps/web-extension/dist/` as unpacked extension in Chrome
3. Navigate to an article → click icon → click "Clip this page"
4. With gateway running: green badge, source appears in recent list
5. With gateway stopped: retry then error message
6. Settings: change gateway URL, verify persistence across popup reopens
7. Firefox: load as temporary add-on, repeat steps 3-6

## Dependencies

| Package | Purpose | Size |
|---------|---------|------|
| `preact` | UI framework | ~3KB gzip |
| `@preact/preset-vite` | Vite JSX plugin | dev only |
| `@types/chrome` | Extension API types | dev only |
| `vite` | Build tool | dev only |
| `vitest` | Test runner | dev only |
| `typescript` | Type checking | dev only |
| `eslint` | Linting | dev only |

Estimated popup bundle: ~8-12KB gzipped.

## Edge Cases

- **Internal browser pages** (`chrome://`, `about:`, etc.): clip button disabled
- **Duplicate URLs**: backend dedup (SHA-256 content hash) returns existing Source — extension shows "Clipped!" normally
- **Gateway unreachable**: 3 retries with backoff, then "Cannot reach WikiMind gateway" error
- **Very long URLs**: truncated in display, sent in full to backend
- **Tab without URL** (e.g., new tab): "No URL detected", clip button disabled

## Future Enhancements (out of scope)

- Context menu integration ("Send to WikiMind" on right-click)
- Client-side Readability.js extraction for paywalled content
- Persistent offline queue with IndexedDB
- Auth token handling for multi-user mode
- Status polling via `chrome.alarms` for compilation progress
