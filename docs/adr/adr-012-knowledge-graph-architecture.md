# ADR-012: Knowledge graph architecture

## Status

Accepted

**Revision (2026-04-15):** The backlink enforcer now runs as Phase 3 of
the lint pipeline (ADR-017), auto-repairing missing inverse links for
symmetric relation types. This strengthens the "graph quality is bounded
by Backlink quality" constraint noted below by providing automated
structural integrity enforcement.

## Context

Epic 3 (manavgup/wikimind#3) adds an interactive knowledge-graph view: nodes
are compiled wiki articles, edges are the `Backlink` rows populated by #95's
wikilink resolver. The Karpathy LLM Wiki Pattern gist mentions Obsidian's
graph view as the visual affordance that makes a wiki feel like *a structure
you inhabit* rather than a list, but prescribes nothing about how to build it.

Three architectural decision points drive the rest of the implementation and
are worth locking in before any code is written:

1. **Storage backend** — do we keep the wiki's graph edges in SQLite alongside
   everything else, or introduce a dedicated graph database (neo4j, Kuzu,
   dgraph)?
2. **Layout computation** — does the backend produce positioned nodes, or
   does it hand raw `{nodes, edges}` to the frontend and let the client-side
   force simulation compute positions?
3. **Concept integration** — do concepts appear in the graph as a parallel
   node type (bipartite graph), or as a coloring layer over article nodes?

These three decisions are interrelated and are recorded together here. The
detailed design document is
`docs/superpowers/specs/2026-04-08-knowledge-graph-design.md`; this ADR only
captures the architecture-level commitments.

## Decision

### 1. Graph storage stays in SQLite

The knowledge graph is served from the existing `Backlink` and `Article`
tables in SQLite. No new storage system is introduced. `WikiService.get_graph`
walks the tables, computes node and edge payloads in Python, and returns
them via `GET /wiki/graph`.

`Backlink` may be extended with additional metadata columns (`created_at`,
eventually `relation_type` if needed) via the existing
`database.py:_migrate_added_columns` helper. Composite primary key
`(source_article_id, target_article_id)` stays as-is.

At personal-wiki scale (O(10³) articles, O(10⁴) edges), every graph query
envisioned — full graph, N-hop neighborhood, shortest path, concept subgraph
— runs in well under 100ms as in-memory Python over a few thousand SQLite
rows.

### 2. Layout is computed client-side

The backend returns pure data: `{nodes: [...], edges: [...]}` with metadata
but no positions. The frontend's force simulation (via
`react-force-graph-2d`, itself a wrapper around d3-force) computes positions
on the client at render time.

The backend stays a rendering-agnostic data provider. It does not compute or
cache node coordinates. Layout is ephemeral and viewer-dependent — the same
data may render differently on different screen sizes, with different
filters applied, or after user interaction.

### 3. Concepts are a coloring layer, not parallel graph nodes

Articles are the only node type in the graph. Each article node carries a
`concept_cluster` string (its primary concept's name) which the frontend
maps to a color. Concepts themselves are **not** nodes in the main graph
view. Article→concept relationships are not edges.

Concepts remain a separate taxonomy surfaced via `GET /wiki/concepts` and the
existing Wiki Explorer sidebar. A future "concept graph" view could treat
concepts as nodes in a dedicated visualization, but that is out of scope for
Epic 3.

## Alternatives Considered

### Storage

**Real graph database (neo4j, Kuzu, dgraph).** Rejected. At personal-wiki
scale, a graph database is infrastructure in search of a problem. Every
query Epic 3 needs is a BFS/DFS over a few thousand rows, which Python can
do in-process in well under 100ms. Adopting a graph database would:

1. Violate ADR-001's zero-dependency-startup principle (`make dev` would
   require users to install and run neo4j or equivalent).
2. Introduce a second storage layer with its own consistency story —
   `Backlink` rows in SQLite would have to stay in sync with graph-DB nodes
   and edges.
3. Deliver no benefit until the wiki scales by at least 10². Until then, the
   complexity tax is paid for imagined future needs.

Revisit this decision if and only if (a) measured graph query latency
exceeds a few hundred ms on the production user's wiki, and (b) the
bottleneck is provably graph-query shape rather than something cheaper to
fix (indexing, caching, query shape itself).

**Materialized adjacency cache in a separate table.** Rejected. A denormalized
`adjacency_cache` table keyed by `(article_id, depth)` could precompute
N-hop neighborhoods and accelerate those queries. Rejected because:

1. It's a cache, not a primary store — it has to be invalidated on every
   compile and every backlink write, which is the kind of bookkeeping bug
   that silently breaks the graph.
2. The queries it would accelerate run in <100ms uncached anyway.
3. Plain in-memory caching of `GET /wiki/graph` (see spec §5f) captures 95%
   of the benefit with none of the persistence complexity.

### Layout

**Server-computed layout.** Rejected. The backend would run the force
simulation (via a Python port or a headless renderer), ship positions in
the response, and the frontend would render them directly. Rejected because:

1. Layout is viewer-dependent — the same graph should lay out differently
   at different zoom levels, with different filters, after user interaction.
   Server-computed layout means re-running the simulation on every
   sub-view, which is expensive and chatty.
2. It couples a storage/query concern to a rendering concern. The backend
   becomes responsible for a choice (d3-force vs dagre vs circular) that
   rightfully belongs to the view layer.
3. It loses the interactive dynamism — nodes can't spring back when
   dragged, transitions can't be smooth, because every frame would need a
   server roundtrip.

**Precomputed, persisted positions.** Rejected for all the reasons above
plus: storing coordinates in the database commits us to a single layout
algorithm forever and invents a new schema concern (coordinates need to be
invalidated any time the graph structure changes, which is every time an
article is compiled).

### Concept integration

**Concepts as parallel graph nodes (bipartite-ish graph).** Rejected. A
graph with two node types (article and concept) and two edge types
(article↔article, article↔concept) is richer in information but worse at
the visualization's primary job — showing how articles connect *to each
other*. Concept nodes become high-degree hubs that visually dominate the
article-to-article structure.

Concretely rejected because:

1. Every downstream graph query becomes ambiguous. "Give me the N-hop
   neighbors of this article" — does that traverse through concept nodes
   or not?
2. It doubles the UI's decision surface (colors, sizes, interactions)
   for both node types.
3. Obsidian's graph view, which is the closest mental-model reference for
   WikiMind users, uses concepts as coloring, not as nodes. Matching that
   model minimizes user onboarding friction.
4. Trivial to change later if real usage demands it — add a separate
   `/graph/concepts` view without touching the main graph.

**Concepts in a second parallel graph (two views side by side).** Rejected
for MVP on scope grounds. Potentially worth revisiting in a future epic if
users show concrete interest in browsing by concept structure.

## Consequences

### Enables

- **Zero new infrastructure.** Epic 3 ships as pure code changes against
  the existing SQLite + FastAPI + React stack. No new services to run, no
  new skill to learn, no new failure modes.
- **Full graph available as one API call.** `GET /wiki/graph` is a single
  round trip that returns everything the viewer needs. Pan, zoom, filter,
  and hover all happen client-side against in-memory data.
- **Layout algorithm is swappable.** Because the backend doesn't own
  layout, the frontend can migrate from `react-force-graph-2d` to
  `react-force-graph-webgl` (WebGL variant, same API) or to cytoscape.js
  without any backend change.
- **Concept coloring degrades gracefully.** If `Concept` rows are sparse or
  the concept taxonomy (#24) isn't yet populated, `concept_cluster` is
  `null` and the graph renders in a single color. Still usable, still
  navigable.
- **Future graph queries** (N-hop neighborhood, shortest path, cluster
  subgraph) are BFS/DFS over the existing `Backlink` table, in Python, with
  no new storage. Each becomes a new route on `/wiki/graph/*` without
  touching the data model.

### Constrains

- **Backend cannot serve a "pre-arranged" graph.** If users ever ask for
  persistent node positions ("I want article X to always sit in the top-
  left"), this ADR needs to be revisited. For now, layout is ephemeral and
  that is a deliberate choice.
- **Graph quality is bounded by `Backlink` quality.** Since the edges are
  exactly the rows in the `Backlink` table, any gap, regression, or false
  positive in the wikilink resolver (#95) is directly visible in the graph.
  There is no second source of truth.
- **`GET /wiki/graph` is a hot endpoint.** It is called on every `/graph`
  page load and returns potentially the entire article corpus. Keeping it
  lean is a continuous obligation — new fields on `GraphNode` or
  `GraphEdge` cost every call.
- **Scale cliff, if it ever arrives, hits the frontend first.** At ~500
  article nodes without WebGL, the force simulation becomes sluggish. The
  backend keeps working fine. Degradation strategy (auto-filter to top-N
  most-connected, migrate to WebGL renderer) is a frontend concern.

### Risks

- **SQLite-backed storage may become inadequate at unforeseen scale.** If a
  user imports a large Obsidian vault (thousands of articles, tens of
  thousands of backlinks) the queries may become slow enough to matter.
  Mitigation: cache `GET /wiki/graph` in memory (planned in spec §5f);
  revisit a graph database only if measurements show it's necessary, not
  preemptively.
- **The client-side layout commitment makes certain future features
  harder.** If WikiMind ever needs to render the graph in a non-JS context
  (CLI, PDF export, server-side screenshot for a social preview), the
  layout algorithm will have to be re-implemented somewhere that has
  positions. Mitigation: cross that bridge when we come to it. No current
  user story wants it.
- **Concept-as-coloring is a weaker signal than concept-as-node.** A user
  wanting to browse their wiki by concept hierarchy is better served by
  the Wiki Explorer's concept sidebar than by the graph. The graph is the
  *connectivity* view, not the *taxonomy* view. Mitigation: document this
  clearly in the user-facing copy; consider a second "concept graph" view
  as a follow-on epic if users ask for it.
- **Epic 3 is meaningless until #95 ships.** The Backlink table is
  effectively empty today. If #95 slips, Epic 3's implementation can start
  (PR 1 data-model polish is independent) but PR 2 (the actual graph view)
  must wait. Mitigation: track #95 as an explicit hard dependency in the
  spec and in PR 2's description.
