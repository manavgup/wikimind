# WikiMind Web

React frontend for the WikiMind local LLM Knowledge OS.

## Stack

- **Vite** + **React 18** + **TypeScript** (strict mode)
- **TanStack Query** v5 for data fetching
- **Zustand** for WebSocket connection state
- **Tailwind CSS** for styling
- **React Router** v6 for routing
- **react-markdown** + **remark-gfm** + **rehype-raw** for markdown rendering

## Quick start

```bash
npm install
npm run dev      # http://localhost:5173
```

The dev server expects the WikiMind gateway to be running on `http://localhost:7842`.

To point the UI at a different gateway, set `VITE_API_URL` in a `.env` file:

```
VITE_API_URL=http://localhost:7842
```

## Scripts

| script | description |
| --- | --- |
| `npm run dev` | Vite dev server (HMR) on :5173 |
| `npm run build` | Type-check and produce production bundle in `dist/` |
| `npm run lint` | Run ESLint over `src/` |
| `npm run typecheck` | Run `tsc --noEmit` |
| `npm run preview` | Preview the production build |

## Layout

```
src/
├── main.tsx         # entry point
├── App.tsx          # routes
├── api/             # fetch wrappers per resource
├── types/api.ts     # TS mirror of Pydantic models
├── store/           # Zustand stores
├── hooks/           # TanStack Query + WS hooks
└── components/
    ├── shared/      # Layout, Card, Badge, Button, Spinner
    ├── inbox/       # Inbox view (#17)
    └── wiki/        # Wiki Explorer view (#18)
```
