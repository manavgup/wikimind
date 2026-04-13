import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useConcepts } from "../../hooks/useArticles";
import type { Concept } from "../../types/api";
import { Spinner } from "../shared/Spinner";

interface ConceptNode extends Concept {
  children: ConceptNode[];
}

function buildTree(concepts: Concept[]): ConceptNode[] {
  const byId = new Map<string, ConceptNode>();
  concepts.forEach((c) => byId.set(c.id, { ...c, children: [] }));
  const roots: ConceptNode[] = [];
  byId.forEach((node) => {
    if (node.parent_id && byId.has(node.parent_id)) {
      byId.get(node.parent_id)!.children.push(node);
    } else {
      roots.push(node);
    }
  });
  return roots;
}

function matchesSearch(node: ConceptNode, query: string): boolean {
  if (node.name.toLowerCase().includes(query)) return true;
  return node.children.some((child) => matchesSearch(child, query));
}

interface ConceptTreeProps {
  activeConcept: string | null;
  onSelectConcept: (name: string | null) => void;
}

export function ConceptTree({ activeConcept, onSelectConcept }: ConceptTreeProps) {
  const navigate = useNavigate();
  const conceptsQuery = useConcepts();
  const [search, setSearch] = useState("");

  const tree = useMemo(
    () => buildTree(conceptsQuery.data ?? []),
    [conceptsQuery.data],
  );

  const query = search.trim().toLowerCase();
  const filtered = useMemo(
    () => (query ? tree.filter((node) => matchesSearch(node, query)) : tree),
    [tree, query],
  );

  return (
    <div className="flex h-full flex-col overflow-hidden p-4">
      <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
        Concepts
      </h2>

      <div className="mb-3">
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Filter concepts..."
          className="w-full rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-xs shadow-sm placeholder:text-slate-400 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
        />
      </div>

      <div className="flex-1 overflow-y-auto">
        {conceptsQuery.isLoading ? (
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <Spinner size={12} /> Loading...
          </div>
        ) : conceptsQuery.isError ? (
          <div className="text-xs text-rose-600">Failed to load concepts</div>
        ) : filtered.length === 0 && !query ? (
          <div className="text-xs text-slate-400">No concepts yet</div>
        ) : filtered.length === 0 && query ? (
          <div className="text-xs text-slate-400">No matching concepts</div>
        ) : (
          <ul className="space-y-0.5">
            <li>
              <button
                type="button"
                onClick={() => { onSelectConcept(null); navigate("/wiki"); }}
                className={`w-full rounded px-2 py-1 text-left text-sm transition ${
                  activeConcept === null
                    ? "bg-brand-50 font-medium text-brand-700"
                    : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                All articles
              </button>
            </li>
            <li className="my-1 border-t border-slate-200" />
            {filtered.map((node) => (
              <ConceptItem
                key={node.id}
                node={node}
                activeConcept={activeConcept}
                onSelect={onSelectConcept}
                depth={0}
                searchQuery={query}
              />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

interface ConceptItemProps {
  node: ConceptNode;
  activeConcept: string | null;
  onSelect: (name: string) => void;
  depth: number;
  searchQuery: string;
}

function ConceptItem({
  node,
  activeConcept,
  onSelect,
  depth,
  searchQuery,
}: ConceptItemProps) {
  const [expanded, setExpanded] = useState(true);
  const hasChildren = node.children.length > 0;
  const isActive = activeConcept === node.name;

  // When searching, filter children too
  const visibleChildren = searchQuery
    ? node.children.filter((child) => matchesSearch(child, searchQuery))
    : node.children;

  return (
    <li>
      <div className="flex items-center">
        {hasChildren ? (
          <button
            type="button"
            onClick={() => setExpanded(!expanded)}
            className="flex h-5 w-5 shrink-0 items-center justify-center text-slate-400 hover:text-slate-600"
            style={{ marginLeft: `${depth * 0.75}rem` }}
          >
            <svg
              className={`h-3 w-3 transition-transform ${expanded ? "rotate-90" : ""}`}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
            </svg>
          </button>
        ) : (
          <span
            className="inline-block h-5 w-5 shrink-0"
            style={{ marginLeft: `${depth * 0.75}rem` }}
          />
        )}
        <button
          type="button"
          onClick={() => onSelect(node.name)}
          className={`flex min-w-0 flex-1 items-center justify-between rounded px-1.5 py-1 text-left text-sm transition ${
            isActive
              ? "bg-brand-50 font-medium text-brand-700"
              : "text-slate-600 hover:bg-slate-100"
          }`}
        >
          <span className="truncate">{node.name}</span>
          <span className="ml-2 shrink-0 text-xs text-slate-400">
            {node.article_count}
          </span>
        </button>
      </div>
      {hasChildren && expanded && visibleChildren.length > 0 ? (
        <ul className="space-y-0.5">
          {visibleChildren.map((child) => (
            <ConceptItem
              key={child.id}
              node={child}
              activeConcept={activeConcept}
              onSelect={onSelect}
              depth={depth + 1}
              searchQuery={searchQuery}
            />
          ))}
        </ul>
      ) : null}
    </li>
  );
}
