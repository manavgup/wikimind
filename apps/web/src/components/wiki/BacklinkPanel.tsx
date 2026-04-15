import { useMemo } from "react";
import { Link } from "react-router-dom";
import type { ArticleResponse, BacklinkEntry, RelationType } from "../../types/api";

interface BacklinkPanelProps {
  article: ArticleResponse | null;
  hasFigures?: boolean;
  figureCount?: number;
}

const RELATION_STYLE: Record<RelationType, { label: string; className: string }> = {
  references: { label: "References", className: "text-brand-700 hover:bg-brand-50" },
  contradicts: { label: "Contradicts", className: "text-rose-700 hover:bg-rose-50" },
  extends: { label: "Extends", className: "text-sky-700 hover:bg-sky-50" },
  supersedes: { label: "Supersedes", className: "text-amber-700 hover:bg-amber-50" },
  synthesizes: { label: "Synthesizes", className: "text-violet-700 hover:bg-violet-50" },
  related_to: { label: "Related to", className: "text-slate-600 hover:bg-slate-100" },
};

function groupByRelationType(links: BacklinkEntry[]): Map<string, BacklinkEntry[]> {
  const groups = new Map<string, BacklinkEntry[]>();
  for (const link of links) {
    const key = link.relation_type ?? "references";
    const existing = groups.get(key) ?? [];
    existing.push(link);
    groups.set(key, existing);
  }
  return groups;
}

export function BacklinkPanel({ article, hasFigures, figureCount }: BacklinkPanelProps) {
  if (!article) {
    return (
      <div className="p-4 text-xs text-slate-400">
        Select an article to see its backlinks.
      </div>
    );
  }

  const inLinks = article.backlinks_in ?? [];
  const outLinks = article.backlinks_out ?? [];

  return (
    <div className="flex h-full flex-col gap-5 overflow-y-auto p-4">
      <TypedSection title="Linked from" links={inLinks} emptyText="Nothing links here yet" />
      <TypedSection title="Links to" links={outLinks} emptyText="No outgoing links" />

      {hasFigures && (
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Figures & Tables
          </h3>
          <a
            href="#figures-tables"
            onClick={(e) => {
              e.preventDefault();
              document.getElementById("figures-tables")?.scrollIntoView({ behavior: "smooth" });
            }}
            className="flex items-center gap-2 rounded px-2 py-1 text-sm text-blue-600 hover:bg-blue-50"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="m2.25 15.75 5.159-5.159a2.25 2.25 0 0 1 3.182 0l5.159 5.159m-1.5-1.5 1.409-1.409a2.25 2.25 0 0 1 3.182 0l2.909 2.909M3.75 21h16.5A2.25 2.25 0 0 0 22.5 18.75V5.25A2.25 2.25 0 0 0 20.25 3H3.75A2.25 2.25 0 0 0 1.5 5.25v13.5A2.25 2.25 0 0 0 3.75 21Z" />
            </svg>
            {figureCount} extracted
          </a>
        </div>
      )}

      {article.concepts.length > 0 ? (
        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Concepts
          </h3>
          <div className="flex flex-wrap gap-1">
            {article.concepts.map((concept) => (
              <span
                key={concept}
                className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-700"
              >
                {concept}
              </span>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

interface TypedSectionProps {
  title: string;
  links: BacklinkEntry[];
  emptyText: string;
}

function TypedSection({ title, links, emptyText }: TypedSectionProps) {
  const grouped = useMemo(() => groupByRelationType(links), [links]);

  return (
    <div>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
        {title}
      </h3>
      {links.length === 0 ? (
        <p className="text-xs text-slate-400">{emptyText}</p>
      ) : grouped.size === 1 && grouped.has("references") ? (
        // Simple list when all links are plain references
        <ul className="space-y-1">
          {links.map((link) => (
            <BacklinkItem key={link.id} link={link} />
          ))}
        </ul>
      ) : (
        // Grouped by relation type
        <div className="space-y-3">
          {Array.from(grouped.entries()).map(([relType, groupLinks]) => {
            const style = RELATION_STYLE[relType as RelationType] ?? RELATION_STYLE.references;
            return (
              <div key={relType}>
                <p className="mb-1 text-xs font-medium text-slate-500">
                  {style.label}
                </p>
                <ul className="space-y-1">
                  {groupLinks.map((link) => (
                    <BacklinkItem key={link.id} link={link} />
                  ))}
                </ul>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function BacklinkItem({ link }: { link: BacklinkEntry }) {
  const relType = (link.relation_type ?? "references") as RelationType;
  const style = RELATION_STYLE[relType] ?? RELATION_STYLE.references;

  return (
    <li>
      <Link
        to={`/wiki/${encodeURIComponent(link.slug)}`}
        className={`block truncate rounded px-2 py-1 text-sm ${style.className}`}
      >
        {link.title}
        {link.relation_type === "contradicts" && link.resolution ? (
          <span className="ml-1 text-xs text-slate-400">
            ({link.resolution})
          </span>
        ) : null}
      </Link>
    </li>
  );
}
