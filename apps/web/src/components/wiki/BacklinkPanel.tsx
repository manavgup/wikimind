import { Link } from "react-router-dom";
import type { ArticleResponse } from "../../types/api";

interface BacklinkPanelProps {
  article: ArticleResponse | null;
}

export function BacklinkPanel({ article }: BacklinkPanelProps) {
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
  links: string[];
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
            <li key={link}>
              <Link
                to={`/wiki/${encodeURIComponent(link)}`}
                className="block truncate rounded px-2 py-1 text-sm text-brand-700 hover:bg-brand-50"
              >
                {link}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
