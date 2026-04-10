import { useNavigate } from "react-router-dom";
import { Badge } from "../shared/Badge";
import type { BadgeTone } from "../shared/Badge";
import type { GraphNode, GraphEdge, ConfidenceLevel } from "../../types/api";

interface GraphDetailPanelProps {
  node: GraphNode;
  edges: GraphEdge[];
  allNodes: GraphNode[];
  onClose: () => void;
}

const CONFIDENCE_TONE: Record<ConfidenceLevel, BadgeTone> = {
  sourced: "success",
  mixed: "info",
  inferred: "warning",
  opinion: "danger",
};

export function GraphDetailPanel({ node, edges, allNodes, onClose }: GraphDetailPanelProps) {
  const navigate = useNavigate();

  // Find connected nodes
  const connectedIds = new Set<string>();
  for (const e of edges) {
    if (e.source === node.id) connectedIds.add(e.target);
    if (e.target === node.id) connectedIds.add(e.source);
  }
  const neighbors = allNodes.filter((n) => connectedIds.has(n.id));

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start justify-between">
        <h3 className="text-sm font-semibold text-slate-800">{node.label}</h3>
        <button
          type="button"
          onClick={onClose}
          className="text-xs text-slate-400 hover:text-slate-600"
          aria-label="Close detail panel"
        >
          ✕
        </button>
      </div>

      <div className="flex flex-wrap gap-2">
        {node.concept_cluster && (
          <Badge tone="brand">{node.concept_cluster}</Badge>
        )}
        {node.confidence && (
          <Badge tone={CONFIDENCE_TONE[node.confidence]}>
            {node.confidence}
          </Badge>
        )}
      </div>

      <div className="text-xs text-slate-500">
        {node.connection_count} connection{node.connection_count !== 1 ? "s" : ""}
      </div>

      <button
        type="button"
        onClick={() => navigate(`/wiki/${encodeURIComponent(node.id)}`)}
        className="rounded-md bg-brand-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-700 transition"
      >
        Open article
      </button>

      {neighbors.length > 0 && (
        <div>
          <h4 className="mb-2 text-xs font-medium text-slate-600">Connected articles</h4>
          <ul className="flex flex-col gap-1">
            {neighbors.map((n) => (
              <li key={n.id}>
                <button
                  type="button"
                  onClick={() => navigate(`/wiki/${encodeURIComponent(n.id)}`)}
                  className="w-full truncate rounded px-2 py-1 text-left text-xs text-brand-600 hover:bg-slate-50"
                >
                  {n.label}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
