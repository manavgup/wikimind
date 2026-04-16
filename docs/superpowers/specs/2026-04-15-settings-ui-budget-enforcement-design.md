# Settings UI + Budget Enforcement — Design Spec

**Epic:** #5 (Sync + Multi-provider) — Phase 5A
**Closes:** #29 (Settings UI — providers, sync, cost) — partially (sync UI deferred)
**Date:** 2026-04-15

## Goal

Build a Settings page that lets users manage LLM provider API keys, monitor cost, and receive budget warnings — without editing config files. Add soft budget enforcement to the LLM router so users know when they're approaching or exceeding their monthly spend limit.

## Scope

**In scope:**
- Settings page with provider cards, cost dashboard, sync status, system info
- API key management via OS keychain (existing POST endpoint)
- Provider connection testing (existing POST endpoint)
- Cost breakdown endpoint (new)
- Budget check in LLM router with WebSocket warnings (new)

**Out of scope (deferred):**
- Google Gemini provider implementation (config exists, no provider class)
- Cloud sync service backend (#28, #74) — sync UI section is read-only, reflecting config
- Runtime config updates / PATCH endpoints (`.env` + keychain is sufficient)
- Settings persistence layer (no new tables)
- Budget hard limits (soft warnings only)

## Architecture

No new persistence. The existing backend already handles:
- **API keys** → OS keychain via `config.set_api_key()` / `POST /settings/llm/api-key`
- **Provider config** → `.env` / env vars via Pydantic `Settings` (auto-enable on key detection)
- **Cost tracking** → `CostLog` table, per-call entries from `LLMRouter.complete()`
- **Settings read** → `GET /settings` returns full config

New work:
1. **Backend**: Budget check in LLM router + cost breakdown endpoint + WS budget events
2. **Frontend**: Settings page with provider cards, cost dashboard, API key modal

---

## Backend Changes

### 1. Budget Check in LLM Router

**File:** `src/wikimind/engine/llm_router.py`

Add two new fields to `LLMConfig` in `config.py`:

```python
class LLMConfig(BaseModel):
    # ... existing fields ...
    budget_warning_pct: float = 0.8           # emit warning at this fraction of budget
    budget_check_cache_seconds: int = 60      # cache spend query to avoid DB pressure
```

Add a budget check method to `LLMRouter` that runs after each successful LLM call (alongside the existing cost logging). The check:

1. Queries `CostLog` for current month's total spend (cached for `budget_check_cache_seconds`)
2. Compares against `settings.llm.monthly_budget_usd`
3. At **warning threshold** (`budget_warning_pct`, default 80%): emits `budget.warning` WebSocket event (once per app lifetime, tracked via `LLMRouter` instance flag — resets on restart)
4. At **100%**: emits `budget.exceeded` WebSocket event (once per app lifetime, same mechanism)
5. **Never blocks** — calls always proceed. This is telemetry, not enforcement.

```python
# In LLMRouter.__init__:
self._budget_warning_sent = False
self._budget_exceeded_sent = False
self._cached_spend: float | None = None
self._cache_expires_at: float = 0.0
```

The check runs in `complete()` after cost logging succeeds, using a fire-and-forget pattern (asyncio.create_task) so it doesn't add latency to the LLM response path.

### 2. Cost Breakdown Endpoint

**File:** `src/wikimind/api/routes/settings.py`

New endpoint:

```
GET /settings/llm/cost/breakdown
```

Response:
```json
{
  "month": "2026-04",
  "total_usd": 12.34,
  "budget_usd": 50.0,
  "budget_pct": 24.7,
  "by_provider": {
    "anthropic": { "cost_usd": 10.50, "call_count": 42 },
    "openai": { "cost_usd": 1.84, "call_count": 15 }
  },
  "by_task_type": {
    "compile": { "cost_usd": 8.20, "call_count": 30 },
    "qa": { "cost_usd": 3.10, "call_count": 20 },
    "lint": { "cost_usd": 1.04, "call_count": 7 }
  }
}
```

Implementation: Two GROUP BY queries on `CostLog` filtered to current month — one by `provider`, one by `task_type`. Uses `get_session_factory()()` (same pattern as existing `get_llm_cost`).

### 3. WebSocket Budget Events

**File:** `src/wikimind/api/routes/ws.py`

Two new emitter functions:

```python
async def emit_budget_warning(spend_usd: float, budget_usd: float, pct: float):
    """Emitted once when monthly spend crosses 80% of budget."""

async def emit_budget_exceeded(spend_usd: float, budget_usd: float):
    """Emitted once when monthly spend crosses 100% of budget."""
```

These are called from the LLM router's budget check, not from API routes.

---

## Frontend Changes

### 1. Settings Page Route

**Files:** `apps/web/src/App.tsx`, `apps/web/src/components/shared/Layout.tsx`

- Add `/settings` route to App.tsx
- Add Settings nav item to Layout.tsx (gear icon or similar, at bottom of nav)

### 2. API Module

**File (new):** `apps/web/src/api/settings.ts`

Functions wrapping the existing and new backend endpoints:

```typescript
// GET /settings → full settings object
export function getSettings(): Promise<SettingsResponse>

// GET /settings/llm/cost → monthly summary
export function getCostSummary(): Promise<CostSummary>

// GET /settings/llm/cost/breakdown → per-provider + per-task breakdown
export function getCostBreakdown(): Promise<CostBreakdown>

// POST /settings/llm/api-key → set key in keychain
export function setApiKey(provider: string, apiKey: string): Promise<void>

// POST /settings/llm/test?provider=X → test provider connection
export function testProvider(provider: string): Promise<TestResult>
```

### 3. Settings View

**File (new):** `apps/web/src/components/settings/SettingsView.tsx`

Main page component with four sections rendered as Card components:

#### Section A: LLM Providers

A grid of provider cards (one per provider from GET /settings response). Each card shows:

- **Provider name** + enabled/disabled Badge
- **Model** name (e.g., "claude-sonnet-4-5")
- **API key status**: "Configured" (green badge) or "Not configured" (neutral badge)
- **"Set Key" button** → opens ApiKeyModal (only for providers that need keys: anthropic, openai, google)
- **"Test" button** → calls POST /settings/llm/test, shows latency on success or error message
- **"Default" badge** if this is the default provider

The default provider card gets a subtle highlight (e.g., `border-brand-200` instead of `border-slate-200`).

Ollama and Mock providers show their status but no key management (no API key needed).

#### Section B: Cost Dashboard

- **Budget gauge**: horizontal progress bar showing spend vs budget
  - Green when < 80%
  - Amber when 80-99%
  - Red when >= 100%
  - Text: "$12.34 / $50.00 (24.7%)"
- **Per-provider breakdown**: simple table or small horizontal bars showing each provider's spend
- **Per-task breakdown**: simple table showing spend by task type (compile, qa, lint, etc.)
- Data from `GET /settings/llm/cost/breakdown`
- Auto-refreshes via React Query with 60-second stale time

#### Section C: Sync Status

Read-only panel reflecting current sync config from `GET /settings` response. Minor backend change: extend the sync section in `get_all_settings()` to also return `bucket` (currently only returns `enabled` and `interval_minutes`).

- **Status badge**: "Disabled" (neutral) or "Enabled" (green) — from `sync.enabled`
- **Interval**: e.g., "Every 15 minutes" — from `sync.interval_minutes`
- **Bucket**: bucket name or "Not set" — from `sync.bucket` (null when unconfigured)
- **Last sync**: "Never" (no SyncLog entries exist yet — backend not implemented)
- Hint text: "Configure sync in your .env file (WIKIMIND_SYNC__ENABLED=true)"

This section is ready for the sync backend (#28, #74) to land later. When the sync service exists, this section will show live status and add a manual sync button.

#### Section D: System Info

Read-only reference panel:
- Data directory path
- Default provider name
- Fallback enabled/disabled
- Monthly budget (from config)
- Hint text: "Configure these values in your .env file"

### 4. API Key Modal

**File (new):** `apps/web/src/components/settings/ApiKeyModal.tsx`

Simple modal with:
- Provider name in header
- Password input field (masked)
- "Save" button → calls `setApiKey()` → invalidates settings query → closes modal
- "Cancel" button

Uses a `<dialog>` element or absolute positioned div (follow existing patterns — no modal library).

### 5. Provider Card

**File (new):** `apps/web/src/components/settings/ProviderCard.tsx`

Extracted component for the per-provider card. Contains the test button state machine (idle → testing → success/error).

### 6. Cost Dashboard

**File (new):** `apps/web/src/components/settings/CostDashboard.tsx`

Contains the budget gauge and breakdown tables. Separated from SettingsView to keep files focused.

### 7. WebSocket Budget Event Handling

**File:** `apps/web/src/hooks/useWebSocket.ts`

Add handlers for `budget.warning` and `budget.exceeded` events:
- Show toast notification via the existing toast system in `useWebSocketStore`
- `budget.warning`: info toast — "Monthly spend at 80% of budget"
- `budget.exceeded`: warning toast — "Monthly budget exceeded"

**File:** `apps/web/src/types/api.ts`

Add to WSEvent union:
```typescript
| { event: "budget.warning"; spend_usd: number; budget_usd: number; pct: number }
| { event: "budget.exceeded"; spend_usd: number; budget_usd: number }
```

---

## File Summary

| Action | File | What |
|--------|------|------|
| Modify | `src/wikimind/config.py` | Add budget_warning_pct, budget_check_cache_seconds to LLMConfig |
| Modify | `src/wikimind/engine/llm_router.py` | Budget check after cost log, cached spend query, WS emit |
| Modify | `src/wikimind/api/routes/settings.py` | Add GET /settings/llm/cost/breakdown |
| Modify | `src/wikimind/api/routes/ws.py` | Add emit_budget_warning, emit_budget_exceeded |
| Create | `apps/web/src/api/settings.ts` | API functions for settings endpoints |
| Create | `apps/web/src/components/settings/SettingsView.tsx` | Main settings page |
| Create | `apps/web/src/components/settings/ProviderCard.tsx` | Per-provider card component |
| Create | `apps/web/src/components/settings/CostDashboard.tsx` | Budget gauge + breakdown |
| Create | `apps/web/src/components/settings/SyncStatus.tsx` | Read-only sync config panel |
| Create | `apps/web/src/components/settings/ApiKeyModal.tsx` | API key input modal |
| Modify | `apps/web/src/App.tsx` | Add /settings route |
| Modify | `apps/web/src/components/shared/Layout.tsx` | Add Settings nav item |
| Modify | `apps/web/src/hooks/useWebSocket.ts` | Handle budget WS events |
| Modify | `apps/web/src/types/api.ts` | Add budget event types, settings response types |

---

## Testing

### Backend
- **Budget check**: Unit test that mocks CostLog query, verifies WS events fire at 80% and 100% thresholds, verifies they only fire once
- **Cost breakdown endpoint**: Test with seeded CostLog entries, verify grouping by provider and task_type
- **Cache behavior**: Verify budget check uses cached value within 60s window

### Frontend
- **Provider card**: Renders correctly for configured/unconfigured providers, test button shows latency
- **API key modal**: Set key flow calls correct endpoint, invalidates queries
- **Cost dashboard**: Budget gauge colors change at thresholds, breakdown tables render
- **WebSocket events**: Toast appears on budget.warning and budget.exceeded

### Manual Verification
1. Open Settings page → see provider cards with current state
2. Click "Set Key" on a provider → enter key → save → card shows "Configured"
3. Click "Test" → see latency result
4. Cost dashboard shows current month spend with gauge
5. Trigger compilations → cost updates on refresh
6. When spend crosses 80% → toast notification appears

---

## PR Strategy

**Single PR** — this is a cohesive feature (settings page + budget warnings). Backend and frontend changes are tightly coupled and small enough to review together.

Estimated: ~12 files changed, moderate scope.
