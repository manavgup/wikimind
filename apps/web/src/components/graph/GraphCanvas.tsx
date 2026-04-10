import { useCallback, useEffect, useMemo, useRef } from "react";
import ForceGraph from "react-force-graph-2d";
import type { ForceGraphMethods } from "react-force-graph-2d";
import type { GraphNode, GraphEdge } from "../../types/api";

/** Simple palette for concept clusters. Cycles if more concepts than colors. */
const CONCEPT_COLORS = [
  "#6366f1", // indigo
  "#f59e0b", // amber
  "#10b981", // emerald
  "#ef4444", // red
  "#3b82f6", // blue
  "#8b5cf6", // violet
  "#ec4899", // pink
  "#14b8a6", // teal
  "#f97316", // orange
  "#84cc16", // lime
];

const DEFAULT_NODE_COLOR = "#94a3b8"; // slate-400

interface GraphCanvasNode {
  id: string;
  label: string;
  concept_cluster: string | null;
  connection_count: number;
  confidence: string | null;
  val: number;
  color: string;
}

interface GraphCanvasLink {
  source: string;
  target: string;
  context: string | null;
}

interface GraphCanvasData {
  nodes: GraphCanvasNode[];
  links: GraphCanvasLink[];
}

interface GraphCanvasProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  width: number;
  height: number;
  onNodeClick?: (node: GraphCanvasNode) => void;
}

function buildColorMap(nodes: GraphNode[]): Map<string, string> {
  const concepts = new Set<string>();
  for (const n of nodes) {
    if (n.concept_cluster) {
      concepts.add(n.concept_cluster);
    }
  }
  const map = new Map<string, string>();
  let i = 0;
  for (const c of concepts) {
    map.set(c, CONCEPT_COLORS[i % CONCEPT_COLORS.length]);
    i++;
  }
  return map;
}

export function GraphCanvas({ nodes, edges, width, height, onNodeClick }: GraphCanvasProps) {
  const fgRef = useRef<ForceGraphMethods<GraphCanvasNode, GraphCanvasLink>>();

  const colorMap = buildColorMap(nodes);

  const graphData: GraphCanvasData = {
    nodes: nodes.map((n) => ({
      id: n.id,
      label: n.label,
      concept_cluster: n.concept_cluster,
      connection_count: n.connection_count,
      confidence: n.confidence,
      val: Math.max(1, n.connection_count),
      color: n.concept_cluster ? (colorMap.get(n.concept_cluster) ?? DEFAULT_NODE_COLOR) : DEFAULT_NODE_COLOR,
    })),
    links: edges.map((e) => ({
      source: e.source,
      target: e.target,
      context: e.context,
    })),
  };

  const handleNodeClick = useCallback(
    (node: GraphCanvasNode) => {
      onNodeClick?.(node);
    },
    [onNodeClick],
  );

  // Stable key for the current node set — triggers zoom on any filter change
  const nodeKey = useMemo(() => nodes.map((n) => n.id).join(","), [nodes]);

  // Zoom to fit whenever the visible node set changes
  useEffect(() => {
    const timer = setTimeout(() => {
      fgRef.current?.zoomToFit(400, 40);
    }, 600);
    return () => clearTimeout(timer);
  }, [nodeKey]);

  return (
    <ForceGraph<GraphCanvasNode, GraphCanvasLink>
      ref={fgRef}
      graphData={graphData}
      width={width}
      height={height}
      nodeLabel="label"
      nodeColor="color"
      nodeVal="val"
      nodeRelSize={4}
      linkColor={() => "#cbd5e1"}
      linkWidth={1}
      linkDirectionalArrowLength={3}
      linkDirectionalArrowRelPos={1}
      onNodeClick={handleNodeClick}
      warmupTicks={50}
      cooldownTicks={100}
      d3AlphaDecay={0.02}
      d3VelocityDecay={0.3}
      enableNodeDrag={true}
      backgroundColor="transparent"
    />
  );
}
