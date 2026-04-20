# WikiMind App UI Kit

A high‑fidelity recreation of the WikiMind web app — the React + Vite frontend at `apps/web/` in the codebase.

**Use this when designing for WikiMind.** The components here match the production Tailwind classes; copy from them rather than inventing new primitives.

## Files

| File | What it is |
|---|---|
| `index.html` | Click‑through prototype. Inbox → Ask → Wiki with working tab switching and mock interactions. |
| `Shell.jsx` | Sidebar + main layout shell (sidebar nav, connection indicator). |
| `Primitives.jsx` | Button, Badge, Card, Spinner, Input, ConfidenceBadge. |
| `InboxView.jsx` | QuickAddBar + SourceCard + SourceList. |
| `AskView.jsx` | ConversationHistory + ConversationThread + TurnCard + QueryInput. |
| `WikiView.jsx` | ConceptTree + ArticleReader + BacklinkPanel. |

## What's interactive

- **Inbox** — type a URL + press Add → a new source appears with a `Processing` badge that flips to `Done` after ~2s. Drop zone is decorative.
- **Ask** — switch conversations in the left rail; type a new question and hit Enter → the turn appears with a spinner, then a canned answer and citation chips fill in.
- **Wiki** — click any concept in the left tree to filter the article grid; click an article card to enter the reader.

## Fidelity caveats

- No real backend. All data is seeded in memory.
- The Graph, Health, and Settings tabs are stubbed (header only) — not in scope for this pass.
- OAuth login is a separate screen (see `preview/brand-logo.html` for the treatment); included as the `/login` button in the shell.
- The full markdown preprocessor for `[[wikilinks]]` and `[sourced]` confidence tags is simplified to a regex swap.

## Rooted in

Files read from the codebase (mounted at `wikimind/`) to get this right:

- `apps/web/tailwind.config.js` — brand scale
- `apps/web/src/index.css` + `index.html` — Inter, bg-slate-50 canvas
- `apps/web/src/components/shared/{Layout,Button,Badge,Card,Spinner}.tsx`
- `apps/web/src/components/inbox/{InboxView,QuickAddBar,SourceCard}.tsx`
- `apps/web/src/components/ask/{AskView,TurnCard}.tsx`
- `apps/web/src/components/wiki/{WikiExplorerView,ArticleReader,ConfidenceBadge}.tsx`
