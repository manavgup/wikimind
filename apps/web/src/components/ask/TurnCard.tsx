import { useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { QueryRecord } from "../../api/query";

const COLLAPSE_THRESHOLD_CHARS = 800;

interface Props {
  query: QueryRecord;
}

export function TurnCard({ query }: Props) {
  const sources = useMemo(() => parseSources(query.source_article_ids), [query.source_article_ids]);
  const isLong = query.answer.length > COLLAPSE_THRESHOLD_CHARS;
  const [expanded, setExpanded] = useState(!isLong);

  const displayed = expanded ? query.answer : truncateOnParagraphBoundary(query.answer, COLLAPSE_THRESHOLD_CHARS);

  return (
    <article className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <header className="mb-3">
        <div className="text-xs font-medium uppercase tracking-wide text-slate-400">
          Q{query.turn_index + 1}
        </div>
        <h3 className="mt-1 text-base font-semibold text-slate-900">{query.question}</h3>
      </header>

      <div className="prose prose-sm max-w-none text-slate-700">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{displayed}</ReactMarkdown>
      </div>

      {isLong && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="mt-2 text-sm font-medium text-blue-600 hover:underline"
        >
          {expanded ? "Show less" : "Show more"}
        </button>
      )}

      {sources.length > 0 && (
        // Source pills are rendered as non-clickable <span>s until wikilink
        // resolution lands (tracked by manavgup/wikimind#95). When the
        // backend stores resolved article IDs on Query instead of raw
        // titles, these can be upgraded to <Link to={`/wiki/${id}`}>.
        <footer className="mt-4 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-400">
            Sources:
          </span>
          {sources.map((s) => (
            <span
              key={s}
              title="Source article — not yet clickable (tracked by #95)"
              className="rounded-full bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700"
            >
              {s}
            </span>
          ))}
        </footer>
      )}

      {query.confidence && (
        <div className="mt-2 text-xs text-slate-400">
          Confidence: <span className="font-medium text-slate-600">{query.confidence}</span>
        </div>
      )}
    </article>
  );
}

function parseSources(raw: string | null): string[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function truncateOnParagraphBoundary(text: string, max: number): string {
  if (text.length <= max) return text;
  // Find the last \n\n before max
  const slice = text.slice(0, max);
  const lastBreak = slice.lastIndexOf("\n\n");
  if (lastBreak > max * 0.5) {
    return slice.slice(0, lastBreak) + "\n\n…";
  }
  // Fall back to nearest sentence end
  const lastDot = slice.lastIndexOf(". ");
  if (lastDot > max * 0.5) {
    return slice.slice(0, lastDot + 1) + " …";
  }
  return slice + "…";
}
