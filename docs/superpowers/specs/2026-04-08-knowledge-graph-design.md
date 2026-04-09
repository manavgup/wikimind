# Knowledge Graph (Epic 3) — Design

**Date:** 2026-04-08
**Status:** Proposed (pre-implementation design, open decisions flagged in §9)
**Author:** Design session against the WikiMind / Karpathy LLM Wiki Pattern
**Related Epic:** [manavgup/wikimind#3 — Epic 3: Knowledge Graph](https://github.com/manavgup/wikimind/issues/3)
**Related issues:** [#23 backlink extraction](https://github.com/manavgup/wikimind/issues/23), [#24 concept taxonomy](https://github.com/manavgup/wikimind/issues/24), [#25 Graph UI](https://github.com/manavgup/wikimind/issues/25), [#95 wikilink resolution](https://github.com/manavgup/wikimind/issues/95)
**Related ADR:** [ADR-012 — Knowledge graph architecture](../../adr/adr-012-knowledge-graph-architecture.md)

## 1. Context

The Karpathy LLM Wiki Pattern gist describes a knowledge OS whose product loop is **Ingest → Query → Lint** and whose long-term payoff is that *explorations compound back into the wiki as new sources*. The gist mentions Obsidian's graph view in passing as the visual affordance that makes a wiki feel like *a structure you inhabit* rather than a list you scroll. It does not prescribe anything beyond that: no storage model, no layout algorithm, no query semantics.

As of main (commit `d57d617`), WikiMind has shipped the full Ask vertical slice (ingest → compile → query → file-back loop, ADR-011). With the loop closed, the question is what to build next that makes the accumulated wiki feel like a single connected artifact rather than a list of compiled articles. Epic 3 is that payoff: an interactive knowledge graph view where the user sees their wiki *as* a graph and can navigate it spatially.

Epic 3 is not just a visualization. It is also a set of graph-native queries that only make sense once the wiki is treated as a graph structure: "what connects these two articles?", "what is the shortest path between A and B?", "which concept clusters are sparsest?" Those queries feed back into the linter's data-gap detection later.

**Dependency on #95 is the blocking constraint.** Today, `src/wikimind/engine/compiler.py` writes `[[Title]]` strings into article markdown bodies based on LLM-guessed `backlink_suggestions`, but **it never creates any `Backlink` table rows**. A grep for `Backlink` against `compiler.py` returns zero hits. The `Backlink` table is effectively empty in any real deployment. Issue #95 is the fix: resolve wikilinks at compile time against the actual article set and persist resolved ones as real `Backlink` rows. Without #95, Epic 3's graph renders as a scatter plot of disconnected dots. **#95 must merge before Epic 3 implementation starts.**

## 2. Current state

### 2a. `Backlink` model

`src/wikimind/models.py:157` defines:

```python
class Backlink(SQLModel, table=True):
    """Directed link between two wiki articles."""

    source_article_id: str = Field(foreign_key="article.id", primary_key=True)
    target_article_id: str = Field(foreign_key="article.id", primary_key=True)
    context: str | None = None  # Sentence where link appears
```

Three fields only: `source_article_id`, `target_article_id`, `context`. No `relation_type`. No `weight`/`confidence`. No `created_at`. The composite primary key means there is exactly one directed edge per (source, target) pair — a second mention from the same article to the same target silently dedupes.

`Article` has ORM-side eager-loading helpers (`backlinks_in`, `backlinks_out`) via `selectin` loading, which is what `get_graph` walks.

**Populated in practice?** No. The compiler writes `[[Title]]` strings into the article markdown but never touches the `Backlink` table. The eager-loaded `backlinks_out` lists are empty for every article compiled today. This is exactly what #95 fixes.

### 2b. `GET /wiki/graph` API

Routed at `src/wikimind/api/routes/wiki.py:36` and implemented at `src/wikimind/services/wiki.py:222` (`WikiService.get_graph`). Response model:

```python
class GraphNode(BaseModel):
    id: str
    label: str
    concept_cluster: str | None   # currently hard-coded to None
    connection_count: int
    confidence: ConfidenceLevel | None

class GraphEdge(BaseModel):
    source: str
    target: str
    context: str | None

class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
```

The service walks every `Article`, collects their eager-loaded `backlinks_out`, and computes `connection_count` by summing inbound + outbound degree per node. It passes `confidence` through from the `Article` row. **`concept_cluster` is hard-coded to `None`** — the field exists but nothing populates it because the concept-article mapping is not wired into this query. Zero positional hints, zero layout metadata, zero clustering data.

No frontend consumer exists for this endpoint today. A grep of `apps/web/src/api/` for `graph` returns nothing.

### 2c. `apps/web/src/components/graph/`

The directory exists but is empty (`ls apps/web/src/components/graph/` returns no entries). It was created as a placeholder for Epic 3 and has sat unused since the directory was first committed.

### 2d. Concept taxonomy

`src/wikimind/models.py:146`:

```python
class Concept(SQLModel, table=True):
    id: str
    name: str = Field(unique=True, index=True)
    parent_id: str | None = Field(default=None, foreign_key="concept.id")
    article_count: int = 0
    description: str | None = None
    created_at: datetime
```

`Article` stores its concepts as a JSON array of concept IDs in `Article.concept_ids`. `GET /wiki/concepts` (`WikiService.get_concepts`) returns the flat concept list. Issue #24 covers the auto-generation of parent/child hierarchy — as of today, the `Concept` table may be populated (from compilation's `CompilationResult.concepts`) but the hierarchy is flat and `parent_id` is typically `NULL`.

### 2e. Issues at a glance

| # | Title | State | Relevance |
|---|---|---|---|
| [#3](https://github.com/manavgup/wikimind/issues/3) | Epic 3: Knowledge Graph | Open | This spec |
| [#23](https://github.com/manavgup/wikimind/issues/23) | Backlink extraction + graph tables | Open | Producer side — superseded by #95 in practice |
| [#24](https://github.com/manavgup/wikimind/issues/24) | Concept taxonomy auto-generation | Open | Feeds graph coloring / clustering |
| [#25](https://github.com/manavgup/wikimind/issues/25) | React UI: Graph view | Open | Consumer side — the frontend work in this spec |
| [#95](https://github.com/manavgup/wikimind/issues/95) | Wikilinks in compiled articles are unresolved | Open | **Hard blocker** — must merge first |

#23 and #95 overlap substantially. #23 is the original "Phase 3" placeholder from the earliest roadmap; #95 is the specific bug-fix filing with detailed evidence. Implementation-wise, closing #95 also closes the meaningful work of #23. This spec treats #95 as the real prerequisite and notes #23 as the historical umbrella.

## 3. Goals for Epic 3

1. **Visualize the wiki as an interactive graph.** Nodes = articles, edges = backlinks. The user opens `/graph`, sees their wiki's connectivity at a glance, pans and zooms, and can navigate from any node into the article view.
2. **Support graph-native queries.** At minimum: N-hop neighborhood of a given article. Stretch goals: shortest path between two articles, most central article in a concept cluster.
3. **Use the concept taxonomy for coloring / clustering.** Nodes in the same concept cluster share a color; optionally, layout bias lets them drift toward each other under force simulation.
4. **Click-to-navigate.** Clicking a node opens a preview panel; double-clicking (or clicking "open in wiki") navigates to the article reader.
5. **Surface "related but not yet connected" candidates.** Articles that share concepts or are otherwise topically related but have no backlink edges between them are suggestions for the user to explicitly link (or for a future linter to propose).

## 4. Non-goals

- **Not real-time.** Graph staleness is fine. The graph can be rebuilt on demand, regenerated on a cadence, or cached for some short window. A user who ingests a source does not need the graph to update within the same tick.
- **Not a graph database.** SQLite + the existing `Backlink` table is sufficient at personal-wiki scale (O(10³) articles, O(10⁴) edges upper bound). Moving to neo4j / dgraph / Kuzu violates ADR-001's local-first, zero-dependency-startup principle and buys us nothing at this scale.
- **Not a social / multi-user graph.** No shared subgraphs, no permissions, no federation. WikiMind is a personal wiki; the graph is personal too.
- **Not 3D.** 2D force-directed is legible, performant, and scales well. A 3D view is novelty over utility at this stage.
- **Not a timeline view.** A time-axis layout captures *when* the wiki grew but not *how it connects*. Out of scope here; could be a future epic.
- **Not editable.** The user cannot drag a node to a new position and expect it to persist. Layout is ephemeral; the underlying data model does not hold coordinates.

## 5. Design

### 5a. Data model decisions

**Is the existing `Backlink` schema sufficient?**

For the MVP of Epic 3 — render nodes and edges, support navigation, color by concept — **yes, it is sufficient as-is**. The three fields (`source_article_id`, `target_article_id`, `context`) give us everything a force-directed layout needs: node identity comes from the `Article` it references, edge direction comes from the primary key ordering, and the `context` sentence is surfaced as a hover tooltip.

However, several extensions are worth considering at spec-review time. Each is justified or rejected below:

| Proposed field | Justification | Recommendation |
|---|---|---|
| `relation_type: str` (cites / contradicts / supersedes / elaborates) | Richer edge semantics; enables colored edges in the graph and future semantic queries | **Defer.** Requires LLM changes in the compiler (new classification call per link) and no clear UX yet. Revisit after MVP if users ask. |
| `weight: float` or `confidence: float` | Allows edge thickness to encode link strength; allows filtering weak links | **Defer.** The compiler has no principled way to assign weights today. Synthetic weights (e.g. "number of mentions") are misleading. Ship with uniform weights, revisit if the graph feels too busy. |
| `created_at: datetime` | Enables "show me links added in the last week" filter; supports the timeline-view follow-on epic | **Add in PR 1.** Small, cheap, useful, doesn't commit to anything. |
| `updated_at: datetime` | Only meaningful if edges can be mutated in place; today each re-compile re-creates all backlinks | **Reject.** Not meaningful under current re-compile semantics. |

**Decision:** PR 1 extends `Backlink` with a single new field: `created_at: datetime`. Everything else stays as-is and can be added incrementally if usage justifies it. The extension is a `_migrate_added_columns` entry, nullable-or-defaulted, and has no back-compat implications.

**Where do concepts sit in the graph?**

Two options:

1. **Concepts are a coloring layer.** Each node (article) gets a `concept_cluster` string — typically the name of its primary concept — and the frontend renders all articles in the same cluster in the same color. Concepts do not appear as graph nodes themselves.
2. **Concepts are parallel nodes.** The graph has two node types: article nodes and concept nodes. Article→concept is an edge. Article↔article is also an edge. The graph is bipartite-ish.

**Decision: concepts are a coloring layer, not a parallel node type.** Rationale:

- Keeps node count equal to article count. Two-type graphs complicate every downstream query ("give me N-hop neighbors" becomes ambiguous — do you traverse through concepts?).
- Keeps the visual simple. The payoff of a knowledge graph is seeing *articles connected to articles*. Concept-as-node visually drowns this in hub nodes.
- Matches Obsidian's graph view, which users already have as a mental model.
- Trivial to upgrade later if it turns out we need it: concepts become nodes in a different view (`/graph/concepts`), not in the main view.

**Orphan articles** (zero backlinks, zero inbound links) sit in the graph as nodes with zero edges. They are still rendered, still clickable, still navigate to the article. They are visually distinct — smaller radius, dimmer color, optional "orphans only" filter. The empty-state copy for a wiki with only orphans is handled in 5e.

### 5b. Graph API

**Current `/wiki/graph` shape** (repeated from §2b for the decision):

```json
{
  "nodes": [
    {"id": "art-123", "label": "Attention Is All You Need",
     "concept_cluster": null, "connection_count": 5,
     "confidence": "sourced"}
  ],
  "edges": [
    {"source": "art-123", "target": "art-456",
     "context": "builds on the self-attention mechanism"}
  ]
}
```

**Extensions for PR 1:**

1. **Populate `concept_cluster`.** Look up each article's primary concept (the first entry in `Article.concept_ids`, parsed as JSON) and set `concept_cluster` to the concept's `name`. Null only if the article has no concepts. This is a join, cached at graph-build time.
2. **Add node metadata the layout engine will want.** Specifically: `slug` (for navigation without a second lookup) and `updated_at` (for "recently updated" visual emphasis). Both are cheap — already on `Article`.
3. **Add edge `created_at`.** Once `Backlink.created_at` lands per 5a, expose it on `GraphEdge` so the frontend can filter by recency.

**New endpoints (PR 4):**

| Route | Returns | Purpose |
|---|---|---|
| `GET /wiki/graph/neighbors/{article_id}?depth=N` | `GraphResponse` — subgraph of N-hop neighborhood | "Show me everything connected to this article within N hops" |
| `GET /wiki/graph/path?from={a}&to={b}` | Ordered list of `{article_id, edge_context}` | Shortest path between two articles (BFS over the adjacency derived from Backlink table) |
| `GET /wiki/graph/cluster/{concept}` | `GraphResponse` — subgraph filtered to one concept | "Show me only the ML concept cluster" |

These are deferred to PR 4 (§10). The MVP (PR 2) only needs the existing `/wiki/graph`.

**Performance consideration.** The current `get_graph` walks every `Article` and every `Backlink`. At personal-wiki scale (<10³ articles) this is a few hundred ms at worst. At larger scale, the endpoint should be cached — see 5f.

### 5c. Layout algorithm

**Decision: force-directed layout, computed client-side.**

Options considered:

1. **Force-directed (d3-force via react-force-graph-2d)** — nodes repel, edges attract, physics simulation settles into an organic layout. Strengths: familiar, good for exploring connectedness, organic clustering falls out naturally. Weaknesses: nondeterministic (same data, different layout each refresh), tricky at scale.
2. **Hierarchical (dagre).** Good for DAGs with clear root-child relationships. Weakness: wiki backlinks are cyclic graphs, not DAGs. Forcing a hierarchy imposes a structure that isn't there.
3. **Circular by concept.** Articles grouped in rings by concept. Weakness: loses the *connectivity* signal, which is the whole point.

**Force-directed wins.** It matches Obsidian's existing affordance (so WikiMind users feel at home) and it visually reveals the graph's actual structure — clusters emerge, bridges are obvious, orphans float at the edge.

**Where does layout run?** **Client-side.** The backend returns `{nodes, edges, metadata}`. The frontend's force simulation computes positions. Rationale:

- The layout is ephemeral and viewer-dependent (zoom state, pan state, which node is selected all affect rendering). Computing server-side would mean sending position data with every response and re-running the simulation whenever the viewer wants a different sub-view.
- `react-force-graph-2d` has a mature, well-tuned simulation. Using it means we get good defaults for free.
- The backend stays pure-data. Graph layout is a rendering concern.

This is an architectural commitment and is captured in ADR-012.

### 5d. Frontend architecture

**Library choice: `react-force-graph-2d`.**

Options evaluated:

| Library | Pros | Cons | Verdict |
|---|---|---|---|
| **react-force-graph-2d** | Thin React wrapper over d3-force + canvas, small API (~20 props), good defaults, optional WebGL variant (`react-force-graph-webgl`) for scale, actively maintained, MIT licensed | Fewer features than cytoscape (no built-in filters, no compound nodes) | **Chosen.** Right scope for MVP. |
| cytoscape.js | Feature-rich, first-class filtering / styling / layout algorithms, battle-tested | Heavier bundle, more opinionated API, steeper learning curve, overkill for MVP | Rejected for MVP; revisit if we outgrow react-force-graph. |
| vis-network | Enterprise-y, has a React wrapper | Maintenance is inconsistent, API feels dated, bundle size is large | Rejected. |
| sigma.js | WebGL-first, scales well | Less idiomatic in React, smaller ecosystem | Rejected. Revisit if scale requires WebGL (see 5f). |

**react-force-graph-2d is the MVP pick.** If/when scale pushes past its 2D-canvas cutoff (~500 nodes without WebGL), migrate to `react-force-graph-webgl` — same API surface, different rendering backend, minimal code change.

This is an open decision flagged in §9 — the user should explicitly lock it in before implementation starts.

**New components under `apps/web/src/components/graph/`:**

| Component | Responsibility |
|---|---|
| `GraphView.tsx` | Page container. Two-pane layout: left sidebar (`GraphFilters`), main area (`GraphCanvas`), overlay right panel (`GraphDetailPanel`) when a node is selected. Loads `/wiki/graph` via react-query on mount. Handles URL state (`/graph?selected=<article_id>`). |
| `GraphCanvas.tsx` | Thin wrapper around `<ForceGraph2D />`. Receives `{nodes, edges, selectedId, onNodeClick, onNodeHover, filters}` as props. Applies visual mapping: node radius ∝ `connection_count`, node color ← `concept_cluster`, node dimness ← orphan state. Handles the physics config (link distance, charge strength) — tuned during implementation. |
| `GraphFilters.tsx` | Sidebar. Controls: concept filter (multi-select), confidence filter (sourced / mixed / inferred / opinion checkboxes), min connection count (slider), show orphans (toggle), search box to pin a node by title. Filter state lives in the parent via lifted `useState` or zustand — decision deferred to implementation. Filters prune `nodes`/`edges` in memory; do **not** re-fetch. |
| `GraphDetailPanel.tsx` | Right-side drawer. Appears when a node is selected. Shows: article title, summary, concept tags, confidence chip, inbound/outbound link counts, an "Open in wiki" button that navigates to `/wiki/:slug`, a list of "related but not yet connected" candidates (articles sharing ≥1 concept but with no edge between them). |

**New route:** `/graph` in `apps/web/src/App.tsx`. Optional `/graph?selected=<article_id>` query param for deep-linking to a node.

**New nav link:** "Graph" in `Layout.tsx`, between "Wiki" and the existing right-side links. Visual order: **Inbox → Ask → Wiki → Graph**. The Graph is the spatial version of the Wiki — naturally adjacent.

**New API client method** in `apps/web/src/api/wiki.ts`:

```typescript
export interface GraphNode { id: string; label: string; slug: string;
  concept_cluster: string | null; connection_count: number;
  confidence: string | null; updated_at: string; }
export interface GraphEdge { source: string; target: string;
  context: string | null; created_at: string; }
export interface GraphResponse { nodes: GraphNode[]; edges: GraphEdge[]; }
export function getGraph(): Promise<GraphResponse>;
```

### 5e. Interaction model

- **Click node** → `GraphDetailPanel` opens, populated with the node's metadata. URL updates to `/graph?selected=<id>`.
- **Double-click node** → navigate to `/wiki/:slug` (the article reader).
- **Hover edge** → tooltip with the source article's `context` snippet (if `Backlink.context` is populated).
- **Hover node** → highlight the node's immediate neighbors; dim everything else.
- **Pan + zoom** → mouse drag + scroll wheel / trackpad pinch. Standard `react-force-graph` defaults.
- **Filter controls** → dynamically prune `nodes` and `edges` in the parent component's state. No re-fetch — the whole graph is already in memory. Filter operations are O(n) per change.
- **Search / pin** → typing in the search box filters the node list to title matches; selecting a match centers the view on that node and opens its `GraphDetailPanel`.
- **Keyboard:**
  - `g` from anywhere → navigate to `/graph`
  - `/` → focus the search input within `/graph`
  - `esc` → close the `GraphDetailPanel`
  - `o` → toggle "show orphans only"

Keyboard shortcuts are a nice-to-have for the MVP. Gate them behind the global command-palette work (not yet shipped) if that feels cleaner.

**Empty state** (zero articles): friendly "Your graph is empty. Ingest a source to start building your wiki." with a link to `/inbox`.

**Sparse state** (articles exist but no edges): the graph renders as a cloud of dots. Show a banner: "Your wiki has {N} articles but no backlinks yet. Backlinks are created when compiled articles cross-reference each other via `[[wikilinks]]`." This is the cold-start reality until #95 is live **and** the user has compiled enough articles for cross-references to emerge.

### 5f. Performance thresholds

Force-directed layout in a 2D canvas starts to feel sluggish past a certain node count. Measured rough thresholds for `react-force-graph-2d`:

| Node count | Behavior | Mitigation |
|---|---|---|
| 0 – 500 | Smooth. No mitigation needed. | — |
| 500 – 2,000 | Noticeable simulation lag on first render; interaction still OK | Pre-compute positions via `cooldownTicks`, render post-settle |
| 2,000 – 5,000 | Canvas rendering becomes the bottleneck | Switch to `react-force-graph-webgl` (WebGL variant, same API) |
| 5,000+ | WebGL also strained | Server-side sub-graph filtering (e.g. only return top 1000 most-connected nodes by default); virtualized rendering |

**For WikiMind's target audience** — personal wikis of 10² to a few × 10³ articles — we are comfortably in the "no mitigation needed" band for the foreseeable future. The 500-node cutoff is the trigger to introduce auto-filtering: when the graph returns >500 nodes, the default view shows only the top-500 most-connected subgraph, with a "show all" escape hatch.

**Backend cache strategy.** `GET /wiki/graph` is the single hot endpoint. Cache the computed response in-memory (LRU with TTL, or invalidate on article write) behind the service method:

- **Invalidation:** on any `Article` insert/update/delete and on any `Backlink` insert/delete. Hook via SQLAlchemy events or explicit service-method bustling.
- **TTL fallback:** 5 minutes. If events are missed for any reason, staleness is bounded.
- **Cache key:** single global key (the graph is global). No per-user consideration — WikiMind is single-user.

Implementation-wise, this is a plain Python `dict` with timestamps. Not Redis, not memcached. Fits in the existing process.

## 6. Alternatives considered

**Real graph database (neo4j, dgraph, Kuzu).** Rejected. At personal-wiki scale (O(10³) articles), SQLite + the existing `Backlink` table handles every query this spec envisions in <100ms with no special infrastructure. Adopting a graph database would:

- violate ADR-001's zero-dependency-startup principle (now the user needs neo4j installed),
- require a second storage layer with its own consistency story,
- contribute nothing that a BFS/DFS over a few thousand rows in Python can't already do.

Revisit only if the wiki scales by 10² and we can measure real pain. Not today.

**3D graph visualization.** Rejected. `react-force-graph-3d` exists and looks cool. But it adds cognitive load (users rotate to see structure), it doesn't reveal more information than 2D at this scale, and it's novelty-driven rather than utility-driven. The payoff of the knowledge graph is "I can see my wiki's structure" — 2D delivers that cleanly.

**Timeline view as the primary layout.** Rejected. Time is one axis the wiki has (via `Article.created_at`) but the graph's purpose is to expose *connections*, not chronology. A timeline layout flattens the connection structure into a line. Could be a separate view in a future epic; should not be the primary graph layout.

**Server-side computed layout.** Rejected. Sending positions from the backend means:

- re-running the simulation every time the viewer wants a different sub-view,
- coupling the storage layer to a rendering concern,
- losing the interactive dynamism of live physics (nodes that spring back when dragged, smooth transitions when filters apply).

Client-side wins on every axis.

**Make concepts first-class graph nodes.** Already discussed in 5a. Rejected because it complicates every downstream query and visually drowns article-to-article structure in concept hubs.

## 7. Consequences

### Enables

- **The payoff of the wiki.** Everything shipped so far (ingest, compile, backlinks, concepts, Ask) has been building toward the moment the user sees their wiki *as a structure*. Epic 3 is that moment.
- **Empirical gap analysis.** Concepts with sparse subgraphs are, by definition, areas where the user has knowledge fragments but few cross-connections. This is ground truth for the linter's "data gaps" feature — the graph surfaces them visually and the linter can report them in copy.
- **Navigation at a new level.** The Wiki Explorer is list-oriented; the Graph is spatial. Some questions ("what's near article X in concept-space?") are natural to answer spatially and awkward to answer in a list.
- **A natural home for future graph queries.** N-hop neighborhood, shortest path, most central article — all of these become new routes on the existing `/wiki/graph/*` namespace without touching the core model.

### Constrains

- **Backlink quality becomes user-visible.** Any regression in #95's wikilink resolution — a missed link, a false positive, a title-matching bug — shows up silently as a wrong edge (or a missing edge) in the graph. This creates a soft obligation to keep backlink quality high and to monitor the compiler's behavior on each release.
- **`/wiki/graph` becomes a hot endpoint.** It's called on every `/graph` page load. Adding fields to the response costs every call. Adding heavy joins costs every call. The endpoint has to stay lean.
- **Layout is ephemeral.** Users cannot "arrange" their graph. If a researcher expects Obsidian-style persistent node positions, they will be disappointed. This is an intentional trade-off (see 5c) but should be documented in the user-facing docs.

### Risks

- **Cold-start UX.** A new user's first compiled article is one node with zero edges. A user with five articles and no cross-references is five disconnected dots. Until the wiki grows, the graph view is *less* impressive than the list view. **Mitigate** with friendly empty-state copy (see 5e) and by gating the "Graph" nav link on `article_count >= 5` in the MVP — users don't see the link until their wiki is interesting enough for the graph to be meaningful. Decision flagged in §9.
- **Graph can reveal sparseness.** Showing a user how sparsely connected their wiki is, is both motivating ("wow, so much room to grow") and discouraging ("wow, I thought I knew more"). Early users are more likely to land on the discouraging side. **Mitigate** with celebration patterns ("Your graph now has 10 connections!") — but **not in v1**. Ship the bare view first, see how it feels, iterate on morale.
- **#95 quality directly bounds graph quality.** If #95 ships with a 60%-recall wikilink resolver, the graph shows 60% of the edges. Users will blame the graph, not the resolver. **Mitigate** by shipping #95 with an explicit recall benchmark and tracking it as a regression guard.
- **Performance cliff at unexpected scale.** If a user imports an Obsidian vault (#92, future) with 10k articles, the force simulation will stutter. **Mitigate** by the auto-filter-to-top-500 rule in 5f, and by adding a "too many nodes to display — showing top 500 by connection count" banner.

## 8. Hard dependencies

| Dependency | Why | Status |
|---|---|---|
| **#95 — wikilink resolution** | Without it, the `Backlink` table stays empty and the graph renders as disconnected dots. The entire Epic is meaningless until #95 ships. | **Must merge before Epic 3 implementation PR 2 starts.** PR 1 (data model + API polish) can land before #95 because it doesn't render anything. |
| **#24 — concept taxonomy populated** | Without this, `concept_cluster` is always `None` and the graph falls back to a single color. Still usable, less interesting. | **Nice-to-have.** Epic 3 does not block on #24; it degrades gracefully when the concept table is empty or flat. |
| **Existing `/wiki/graph` endpoint** | Already exists (§2b). PR 1 extends it. | **Done.** |
| **ADR-012** | Architectural decisions (SQLite storage, client-side layout, concept-as-color) deserve a tracked record. | Drafted as sibling to this spec. |

## 9. Open decisions for the user

These are the decisions this spec deliberately does **not** make. They are flagged for spec review and should be locked in before implementation starts.

1. **Graph library lock-in.** This spec recommends `react-force-graph-2d`. The user should confirm before the frontend PR (PR 2) starts — changing libraries mid-implementation is painful. Alternatives on the table: cytoscape.js (more features, heavier), sigma.js (WebGL-first, smaller ecosystem).

2. **Graph view placement relative to Wiki Explorer.** Does the graph view **replace** the Wiki Explorer as the primary browsing UI, or **live alongside it**? Recommendation: **alongside.** Different audiences (list-oriented vs spatial) want different affordances. The graph is additive.

3. **Search / filter on launch, or v1.1?** The full set of filters (concept, confidence, orphan toggle, min connection count, search) is a non-trivial amount of frontend work. Could the MVP ship with *no filters at all* and add them in a follow-up? Recommendation: **ship MVP with basic filters only** (concept multi-select + orphan toggle + search). Defer the rest. The MVP is tested for "can a user find and navigate to a node from the graph"; that works without a min-connection-count slider.

4. **Definition of done for Epic 3's first shipped PR.** Two readings:
   - **View only:** PR 2 ships the view. Graph queries (neighbors / path) ship in a follow-up PR 4.
   - **View + at least one graph query:** PR 2 ships the view plus `GET /wiki/graph/neighbors/{id}`, because without at least one graph-native query, the feature is *just* a visualization and fails goal 2.

   Recommendation: **view only.** The visualization is the primary payoff. Graph queries are a follow-up that become trivial once the data model is locked in.

5. **Cold-start gating.** Should the "Graph" nav link hide until the user has a minimum number of articles and edges (e.g. 5 articles + 3 edges)? Recommendation: **hide until 5 articles exist.** The edge requirement is too brittle (depends on #95 quality and the user's compilation history).

6. **`Backlink.created_at` addition — in PR 1 or later?** The spec (5a) recommends PR 1, but it's a small lift. Could be its own tiny follow-up PR. Recommendation: **in PR 1**, bundle it with the other data model polish.

7. **Caching strategy for `/wiki/graph`.** Do we need the cache at MVP? At <500 articles the raw query is fast. Recommendation: **defer cache to PR 5 (performance pass).** Ship MVP without it.

## 10. Suggested PR decomposition

This is a sketch, not a plan. A separate planning document will refine it when implementation actually begins.

### PR 1 — backend polish (≈200 LOC)

- Extend `Backlink` with `created_at` (or whichever fields the spec review settles on)
- Populate `concept_cluster` in `GraphResponse` from `Article.concept_ids` + `Concept` table
- Add `slug` and `updated_at` to `GraphNode`
- Add `created_at` to `GraphEdge`
- Unit tests on `WikiService.get_graph` for the new fields
- `docs/openapi.yaml` auto-regenerates
- `.env.example` updated if any settings are added (not currently planned)
- **Depends on:** nothing. Can land before #95.

### PR 2 — frontend graph view MVP (≈500 LOC)

- New `apps/web/src/api/wiki.ts` `getGraph()` method and types
- New `apps/web/src/components/graph/GraphView.tsx`, `GraphCanvas.tsx`, `GraphDetailPanel.tsx`
- New `/graph` route in `App.tsx`
- Nav link in `Layout.tsx` (optionally gated on article count per §9)
- `react-force-graph-2d` added to `apps/web/package.json`
- Basic click-to-preview, double-click-to-navigate
- Loading state and empty state
- **No filters in this PR.** Filters are PR 3.
- **Depends on:** PR 1 merged + #95 merged (otherwise the graph is empty).

### PR 3 — filters + orphan handling + keyboard nav (≈300 LOC)

- `GraphFilters.tsx` with concept / confidence / orphan toggle / search
- Filter state management (zustand or lifted state — decide at implementation time)
- Keyboard shortcuts (`g` → graph, `/` → search, `esc` → close panel, `o` → orphans)
- Orphan visual treatment (dimmer, smaller radius)
- **Depends on:** PR 2 merged.

### PR 4 — graph queries (≈400 LOC backend + ≈200 LOC frontend)

- `GET /wiki/graph/neighbors/{article_id}?depth=N` — BFS subgraph
- `GET /wiki/graph/path?from={a}&to={b}` — shortest path
- `GET /wiki/graph/cluster/{concept}` — subgraph by concept
- Frontend: "focus on neighborhood" action from the detail panel
- Frontend: "show path to…" action
- **Depends on:** PR 3 merged.

### PR 5 — performance pass (≈200 LOC) — conditional

- Only if measurements show real problems at expected scale.
- Backend caching of `/wiki/graph` with event-based invalidation.
- Frontend degradation strategy: auto-filter to top-N-most-connected when the graph is too large.
- Optional: swap to `react-force-graph-webgl` if 2D canvas is the bottleneck.
- **Depends on:** PR 4 merged + evidence that performance is actually a problem.

## 11. Related work

- [#3 — Epic 3: Knowledge Graph](https://github.com/manavgup/wikimind/issues/3) — the umbrella epic this spec fulfills.
- [#23 — Backlink extraction + graph tables](https://github.com/manavgup/wikimind/issues/23) — the original Phase 3 placeholder; effectively subsumed by #95's more specific fix.
- [#24 — Concept taxonomy auto-generation](https://github.com/manavgup/wikimind/issues/24) — feeds graph coloring. Not a hard blocker (graceful degradation), but materially improves the payoff.
- [#25 — React UI: Graph view](https://github.com/manavgup/wikimind/issues/25) — the UI-side placeholder; PR 2 closes it.
- [#95 — Wikilinks in compiled articles are unresolved](https://github.com/manavgup/wikimind/issues/95) — the hard blocker. Epic 3 PR 2 cannot ship meaningfully until #95 ships.
- [ADR-001 — FastAPI + async SQLite](../../adr/adr-001-fastapi-async-sqlite.md) — the local-first principle that rejects adopting a real graph database.
- [ADR-004 — Markdown files + SQLite metadata](../../adr/adr-004-markdown-files-sqlite-metadata.md) — the existing storage model the graph reads from.
- [ADR-012 — Knowledge graph architecture](../../adr/adr-012-knowledge-graph-architecture.md) — the architectural decisions this spec is grounded in.
