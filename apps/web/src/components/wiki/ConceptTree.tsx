import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useArticles, useConcepts } from "../../hooks/useArticles";
import type { Article, Concept } from "../../types/api";
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

interface ConceptTreeProps {
  selectedSlug?: string;
}

export function ConceptTree({ selectedSlug }: ConceptTreeProps) {
  const conceptsQuery = useConcepts();
  const [activeConcept, setActiveConcept] = useState<string | null>(null);
  const articlesQuery = useArticles(
    activeConcept ? { concept: activeConcept } : {},
  );

  const tree = useMemo(
    () => buildTree(conceptsQuery.data ?? []),
    [conceptsQuery.data],
  );

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto p-4">
      <div>
        <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
          Concepts
        </h2>
        {conceptsQuery.isLoading ? (
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <Spinner size={12} /> Loading...
          </div>
        ) : conceptsQuery.isError ? (
          <div className="text-xs text-rose-600">Failed to load concepts</div>
        ) : tree.length === 0 ? (
          <div className="text-xs text-slate-400">No concepts yet</div>
        ) : (
          <ul className="space-y-0.5">
            <li>
              <button
                type="button"
                onClick={() => setActiveConcept(null)}
                className={`w-full rounded px-2 py-1 text-left text-sm transition ${
                  activeConcept === null
                    ? "bg-brand-50 text-brand-700"
                    : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                All articles
              </button>
            </li>
            {tree.map((node) => (
              <ConceptItem
                key={node.id}
                node={node}
                activeConcept={activeConcept}
                onSelect={setActiveConcept}
                depth={0}
              />
            ))}
          </ul>
        )}
      </div>

      <div className="border-t border-slate-200 pt-3">
        <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
          {activeConcept ?? "All articles"}
        </h2>
        <ArticleListing
          articles={articlesQuery.data ?? []}
          isLoading={articlesQuery.isLoading}
          isError={articlesQuery.isError}
          selectedSlug={selectedSlug}
        />
      </div>
    </div>
  );
}

interface ConceptItemProps {
  node: ConceptNode;
  activeConcept: string | null;
  onSelect: (name: string) => void;
  depth: number;
}

function ConceptItem({
  node,
  activeConcept,
  onSelect,
  depth,
}: ConceptItemProps) {
  return (
    <li>
      <button
        type="button"
        onClick={() => onSelect(node.name)}
        style={{ paddingLeft: `${0.5 + depth * 0.75}rem` }}
        className={`flex w-full items-center justify-between rounded px-2 py-1 text-left text-sm transition ${
          activeConcept === node.name
            ? "bg-brand-50 text-brand-700"
            : "text-slate-600 hover:bg-slate-100"
        }`}
      >
        <span className="truncate">{node.name}</span>
        <span className="ml-2 text-xs text-slate-400">{node.article_count}</span>
      </button>
      {node.children.length > 0 ? (
        <ul className="space-y-0.5">
          {node.children.map((child) => (
            <ConceptItem
              key={child.id}
              node={child}
              activeConcept={activeConcept}
              onSelect={onSelect}
              depth={depth + 1}
            />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

interface ArticleListingProps {
  articles: Article[];
  isLoading: boolean;
  isError: boolean;
  selectedSlug?: string;
}

function ArticleListing({
  articles,
  isLoading,
  isError,
  selectedSlug,
}: ArticleListingProps) {
  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-xs text-slate-500">
        <Spinner size={12} /> Loading...
      </div>
    );
  }
  if (isError) {
    return <div className="text-xs text-rose-600">Failed to load articles</div>;
  }
  if (articles.length === 0) {
    return <div className="text-xs text-slate-400">No articles in scope</div>;
  }
  return (
    <ul className="space-y-0.5">
      {articles.map((article) => {
        const active = article.slug === selectedSlug;
        return (
          <li key={article.id}>
            <Link
              to={`/wiki/${encodeURIComponent(article.slug)}`}
              className={`block truncate rounded px-2 py-1 text-sm transition ${
                active
                  ? "bg-brand-100 text-brand-800"
                  : "text-slate-700 hover:bg-slate-100"
              }`}
            >
              {article.title}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
