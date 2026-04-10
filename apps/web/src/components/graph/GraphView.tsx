import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useGraph, useConcepts } from "../../hooks/useArticles";
import { Spinner } from "../shared/Spinner";
import { GraphCanvas } from "./GraphCanvas";
import { GraphFilters, type GraphFilterState } from "./GraphFilters";
import { GraphDetailPanel } from "./GraphDetailPanel";
import type { ConfidenceLevel, GraphNode } from "../../types/api";

function useContainerSize() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    // Measure immediately so the first render has dimensions
    const rect = el.getBoundingClientRect();
    setSize({ width: rect.width, height: rect.height });

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setSize({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        });
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return { containerRef, size };
}

const INITIAL_FILTERS: GraphFilterState = {
  selectedConcepts: new Set<string>(),
  selectedConfidence: new Set<ConfidenceLevel>(),
  showOrphans: true,
};

export function GraphView() {
  const graphQuery = useGraph();
  const conceptsQuery = useConcepts();
  const { containerRef, size } = useContainerSize();

  const [filters, setFilters] = useState<GraphFilterState>(INITIAL_FILTERS);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);

  const handleToggleConcept = useCallback((name: string) => {
    setFilters((prev) => {
      const next = new Set(prev.selectedConcepts);
      if (next.has(name)) {
        next.delete(name);
      } else {
        next.add(name);
      }
      return { ...prev, selectedConcepts: next };
    });
  }, []);

  const handleToggleConfidence = useCallback((level: ConfidenceLevel) => {
    setFilters((prev) => {
      const next = new Set(prev.selectedConfidence);
      if (next.has(level)) {
        next.delete(level);
      } else {
        next.add(level);
      }
      return { ...prev, selectedConfidence: next };
    });
  }, []);

  const handleToggleOrphans = useCallback(() => {
    setFilters((prev) => ({ ...prev, showOrphans: !prev.showOrphans }));
  }, []);

  const handleResetFilters = useCallback(() => {
    setFilters(INITIAL_FILTERS);
  }, []);

  const handleNodeClick = useCallback(
    (node: { id: string; label: string; concept_cluster: string | null; connection_count: number; confidence: string | null }) => {
      const graphNode = graphQuery.data?.nodes.find((n) => n.id === node.id);
      if (graphNode) {
        setSelectedNode(graphNode);
      }
    },
    [graphQuery.data],
  );

  // Filter graph data based on filter state
  const filteredData = useMemo(() => {
    if (!graphQuery.data) return { nodes: [], edges: [] };

    const { nodes, edges } = graphQuery.data;

    // Build a set of connected node IDs
    const connectedIds = new Set<string>();
    for (const e of edges) {
      connectedIds.add(e.source);
      connectedIds.add(e.target);
    }

    const filteredNodes = nodes.filter((n) => {
      // Orphan filter
      if (!filters.showOrphans && !connectedIds.has(n.id)) return false;

      // Concept filter — normalize concept_cluster to match Concept.name
      // (slugified). Some older articles store raw names with spaces.
      if (filters.selectedConcepts.size > 0) {
        const normalized = n.concept_cluster
          ?.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/-+/g, "-").replace(/^-|-$/g, "");
        if (!normalized || !filters.selectedConcepts.has(normalized)) {
          return false;
        }
      }

      // Confidence filter
      if (filters.selectedConfidence.size > 0) {
        if (!n.confidence || !filters.selectedConfidence.has(n.confidence)) {
          return false;
        }
      }

      return true;
    });

    const nodeIds = new Set(filteredNodes.map((n) => n.id));
    const filteredEdges = edges.filter(
      (e) => nodeIds.has(e.source) && nodeIds.has(e.target),
    );

    return { nodes: filteredNodes, edges: filteredEdges };
  }, [graphQuery.data, filters]);

  const totalNodeCount = graphQuery.data?.nodes.length ?? 0;
  const isReady = !graphQuery.isLoading && !graphQuery.isError && size.width > 0 && size.height > 0;

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <header className="border-b border-slate-200 bg-white px-6 py-4">
        <h1 className="text-lg font-semibold text-slate-900">Knowledge Graph</h1>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Canvas area — always mounted so the ref is attached for ResizeObserver */}
        <div ref={containerRef} className="flex-1 bg-slate-50">
          {graphQuery.isLoading ? (
            <div className="flex h-full items-center justify-center gap-2 text-sm text-slate-500">
              <Spinner size={16} /> Loading graph...
            </div>
          ) : graphQuery.isError ? (
            <div className="m-8 rounded-md border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
              Failed to load graph data.
            </div>
          ) : isReady ? (
            <GraphCanvas
              nodes={filteredData.nodes}
              edges={filteredData.edges}
              width={size.width}
              height={size.height}
              onNodeClick={handleNodeClick}
            />
          ) : null}
        </div>

        {/* Right sidebar */}
        <aside className="w-64 shrink-0 overflow-y-auto border-l border-slate-200 bg-white p-4">
          {selectedNode ? (
            <GraphDetailPanel
              node={selectedNode}
              edges={graphQuery.data?.edges ?? []}
              allNodes={graphQuery.data?.nodes ?? []}
              onClose={() => setSelectedNode(null)}
            />
          ) : (
            <GraphFilters
              concepts={conceptsQuery.data ?? []}
              filters={filters}
              totalNodeCount={totalNodeCount}
              visibleNodeCount={filteredData.nodes.length}
              onToggleConcept={handleToggleConcept}
              onToggleConfidence={handleToggleConfidence}
              onToggleOrphans={handleToggleOrphans}
              onResetFilters={handleResetFilters}
            />
          )}
        </aside>
      </div>
    </div>
  );
}
