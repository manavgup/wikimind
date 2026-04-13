import { Link } from "react-router-dom";
import type { ArticleResponse, BacklinkEntry } from "../../types/api";

interface BacklinkPanelProps {
  article: ArticleResponse | null;
  hasFigures?: boolean;
  figureCount?: number;
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
      <Section title="Linked from" links={inLinks} emptyText="Nothing links here yet" />
      <Section title="Links to" links={outLinks} emptyText="No outgoing links" />

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

interface SectionProps {
  title: string;
  links: BacklinkEntry[];
  emptyText: string;
}

function Section({ title, links, emptyText }: SectionProps) {
  return (
    <div>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
        {title}
      </h3>
      {links.length === 0 ? (
        <p className="text-xs text-slate-400">{emptyText}</p>
      ) : (
        <ul className="space-y-1">
          {links.map((link) => (
            <li key={link.id}>
              <Link
                to={`/wiki/${encodeURIComponent(link.slug)}`}
                className="block truncate rounded px-2 py-1 text-sm text-brand-700 hover:bg-brand-50"
              >
                {link.title}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
