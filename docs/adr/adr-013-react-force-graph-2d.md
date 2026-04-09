# ADR-013: react-force-graph-2d for knowledge graph visualization

## Status

Proposed

## Context

ADR-012 commits WikiMind's knowledge graph (Epic 3) to a client-side layout
approach — the browser computes node positions via a force-directed algorithm,
the backend just ships nodes and edges. That decision leaves the specific
JavaScript library unresolved. The design spec
(`docs/superpowers/specs/2026-04-08-knowledge-graph-design.md`) flagged the
library choice as an open decision to lock in before Epic 3 implementation
begins.

The choice affects: bundle size, rendering fidelity at scale, React integration
ergonomics, community health, and the cost of future features (filters,
highlighting, subgraph views, path queries).

The candidates considered were the four mainstream force-directed graph
libraries with maintained React bindings: `react-force-graph-2d`, `cytoscape.js`
(with `react-cytoscapejs`), `sigma.js` (with `react-sigma`), and `vis-network`
(with `react-graph-vis`).

## Decision

Use **`react-force-graph-2d`** as the single graph rendering library for
WikiMind's knowledge graph view.

Rationale:

1. **Bundle size** — `react-force-graph-2d` adds ~60KB gzipped, including the
   d3-force simulation. Cytoscape is ~150KB, vis-network ~180KB, sigma ~90KB
   but with less React-friendly ergonomics.

2. **React ergonomics** — `react-force-graph-2d` is a first-class React
   component that takes `graphData={nodes, links}` as a prop and re-renders
   on update. No imperative setup, no ref gymnastics, no lifecycle
   workarounds. Matches the rest of the `apps/web` codebase which is
   declarative TanStack Query + components.

3. **Sensible defaults** — the library ships with acceptable defaults for
   personal-wiki-scale graphs (50–500 nodes). Zoom, pan, drag, click handlers
   all work out of the box. No multi-hour tuning session required to get a
   viable first render.

4. **Scale is adequate for the product** — react-force-graph-2d canvas-backed
   rendering handles ~500 nodes smoothly and ~2000 nodes with degradation.
   At personal-wiki scale (expected 50–500 articles for most users, low
   thousands in extreme cases), this is a non-issue. The WebGL variant
   (`react-force-graph-3d`) exists as an upgrade path if scale ever becomes a
   problem.

5. **Separation of layout from data** — the library computes positions
   client-side, which aligns with ADR-012. The backend never computes or
   stores coordinates.

6. **Upgrade path** — if 2D proves limiting (unlikely), the same vendor ships
   `react-force-graph-3d` (WebGL 3D) and `react-force-graph-vr` (WebXR). Same
   API. Migration is a drop-in component swap, not a rewrite.

## Alternatives considered

### cytoscape.js with `react-cytoscapejs`

**Pros:** Most feature-complete graph library in JS. Rich layout options
(breadthfirst, circle, grid, concentric, cose, klay). Mature ecosystem with
plugins for clustering, pathfinding, edge bundling.

**Cons:** ~150KB bundle. Imperative API underneath — the React wrapper is a
thin shim and you end up reaching for `cy.*` methods for anything non-trivial.
Overkill for a personal knowledge graph visualization where we want one layout
(force-directed) and basic interactions. Would spend significant time disabling
features we don't want.

### sigma.js with `react-sigma`

**Pros:** WebGL-backed rendering handles tens of thousands of nodes. Smallest
bundle of the four (~90KB). Good for dense graphs.

**Cons:** React integration is newer and less polished. Less documentation.
Learning curve is steeper — lots of graphology + sigma + react-sigma coordination
required to do basic things. Performance ceiling is higher than we need at
personal-wiki scale; paying a complexity tax for scale we won't hit.

### vis-network with `react-graph-vis`

**Pros:** Best looking defaults of the four (rounded nodes, smooth edges, nice
animations). Stable, widely deployed.

**Cons:** ~180KB bundle — largest of the four. Development has slowed;
`react-graph-vis` wrapper is maintenance-mode. Uses an older module pattern
that fights with modern Vite + React 18 builds. Would likely require config
workarounds.

## Consequences

**Enables:**

- Epic 3 implementation can start immediately — no further library evaluation
  needed
- `GraphCanvas.tsx` can be a thin wrapper around `react-force-graph-2d` with
  the right props; most of the interesting UI work happens in the sidebar
  (`GraphFilters.tsx`) and detail panel (`GraphDetailPanel.tsx`), not the
  canvas itself
- Future features like "click to focus on neighborhood" or "highlight shortest
  path" work naturally with the library's `onNodeClick` / `linkColor` /
  `nodeColor` callbacks

**Constrains:**

- Committed to 2D visualization for v1. If users request a 3D view later,
  migration is a component swap but some of the 2D-specific UI (detail panel
  positioning, filter interactions) needs review.
- Locked into a force-directed layout for the main view. Alternative layouts
  (hierarchical, circular, radial) are harder to implement in
  `react-force-graph-2d`. If a future use case requires them, a second
  visualization component (possibly a different library for that specific
  view) may be needed.
- Rendering is canvas-based. Accessibility tooling (screen readers) does not
  work with canvas elements by default. An accessible alternative view
  (probably a filterable list of articles + their top connections) will need
  to exist alongside the graph view. This is a known limitation of every
  force-directed graph library in JS and is not specific to this choice.

**Risks:**

- Library maintenance: `react-force-graph-2d` is maintained primarily by a
  single developer (@vasturiano). If the project becomes abandoned, migration
  effort is moderate (days not weeks, because the component boundary is
  narrow). Monitoring signal: watch commit frequency on the repo.
- Large graph performance: 2D canvas starts to degrade noticeably beyond ~2000
  nodes. At personal-wiki scale this is not a concern, but power users with
  large wikis may hit the ceiling. Mitigation is the `GraphFilters` component
  — filtering by concept / date / connection count reduces the visible graph
  to a comfortable size.

## Related

- ADR-012 — knowledge graph architecture (proposed, parent decision)
- `docs/superpowers/specs/2026-04-08-knowledge-graph-design.md` — Epic 3 design spec
- Issues #3 (Epic 3), #25 (React UI: Graph view)
