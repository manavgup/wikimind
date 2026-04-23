# ADR-026: First-Run Onboarding Wizard

## Status

Accepted

## Context

New users who sign up or start WikiMind for the first time face a blank slate with no sources, no articles, and no configured LLM provider. Without guidance, they must figure out the core loop (ingest -> compile -> explore) on their own, which is a high-friction first experience.

Issue #32 calls for a guided onboarding flow that takes users from zero to their first compiled article in under 5 minutes.

## Decision

Add a 5-step onboarding wizard that appears as a modal overlay on first visit:

1. **Welcome** -- explains what WikiMind is and the core loop
2. **Configure LLM** -- API key input with save-and-test validation (skippable)
3. **Add first source** -- URL input with example suggestions, triggers ingest + compile
4. **Watch compilation** -- live progress via existing WebSocket events
5. **Done** -- marks onboarding complete, redirects to Wiki Explorer

### Backend

Onboarding state is stored in the existing `UserPreference` table (ADR-019) using two keys:
- `onboarding.completed` -- `"true"` when finished
- `onboarding.step` -- last completed step number

Two new endpoints on the existing `/settings` router:
- `GET /settings/onboarding-status` -- returns `{completed, step}`
- `POST /settings/onboarding-status` -- marks onboarding complete

### Frontend

A `<OnboardingWizard>` component rendered as a modal overlay inside the authenticated layout. The `App` component queries onboarding status on mount and shows the wizard when `completed` is `false`. The wizard reuses existing API clients (`setApiKey`, `testProvider`, `ingestUrl`) and WebSocket events (`compilation.complete`, `source.progress`) rather than introducing new infrastructure.

## Alternatives Considered

- **Separate onboarding table/model** -- Rejected. The existing `UserPreference` key-value store is sufficient for two boolean/integer values. Adding a new table adds migration complexity for no benefit.
- **Client-side-only state (localStorage)** -- Rejected. Would not survive browser clears or work across devices. Server-side state is consistent.
- **Full-page onboarding route** -- Rejected. A modal overlay lets users see the real UI underneath, creating a smoother transition. It also avoids routing complexity.

## Consequences

- New users get a guided path to their first article, reducing time-to-value.
- The wizard is skippable at the LLM config step for users who prefer to configure later.
- Onboarding state persists across sessions via the DB.
- The feature adds two lightweight API endpoints and one React component tree -- minimal surface area.
- The `UserPreference` table now stores up to 5 keys (3 existing + 2 onboarding) instead of 3.
