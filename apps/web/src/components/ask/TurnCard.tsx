import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { CitationResponse, QueryRecord } from "../../api/query";

const COLLAPSE_THRESHOLD_CHARS = 800;

interface Props {
  query: QueryRecord;
}

/**
 * Renders one Q+A turn in a conversation thread.
 *
 * IMPORTANT: Callers must key this component by `query.id` (e.g.
 * `<TurnCard key={q.id} query={q} />`) so React remounts on a
 * different turn. The `expanded` state is only initialized at
 * mount — swapping the `query` prop on a live instance would
 * leak stale expand/collapse state.
 */
export function TurnCard({ query }: Props) {
  const sources = useMemo(() => parseSources(query.source_article_ids), [query.source_article_ids]);
  const slugByTitle = useMemo(() => buildSlugMap(query.citations), [query.citations]);
  const relatedArticles = useMemo(
    () => parseSources(query.related_article_ids),
    [query.related_article_ids],
  );
  const isLong = query.answer.length > COLLAPSE_THRESHOLD_CHARS;
  const [expanded, setExpanded] = useState(!isLong);

  const displayed = expanded
    ? query.answer
    : truncateOnParagraphBoundary(query.answer, COLLAPSE_THRESHOLD_CHARS);

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
        <footer className="mt-4 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-400">
            Sources:
          </span>
          {sources.map((title, i) => {
            const slug = slugByTitle.get(title);
            return slug ? (
              <Link
                key={`${title}-${i}`}
                to={`/wiki/${slug}`}
                className="rounded-full bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700 hover:bg-blue-100 hover:underline"
              >
                {title}
              </Link>
            ) : (
              <span
                key={`${title}-${i}`}
                className="rounded-full bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700"
              >
                {title}
              </span>
            );
          })}
        </footer>
      )}

      {relatedArticles.length > 0 && (
        <footer className="mt-3 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-400">
            Related:
          </span>
          {relatedArticles.map((title, i) => {
            const slug = slugByTitle.get(title);
            return slug ? (
              <Link
                key={`related-${title}-${i}`}
                to={`/wiki/${slug}`}
                className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700 hover:bg-emerald-100 hover:underline"
              >
                {title}
              </Link>
            ) : (
              <span
                key={`related-${title}-${i}`}
                className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700"
              >
                {title}
              </span>
            );
          })}
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

/** Build a title -> slug lookup from the citations array. */
function buildSlugMap(citations?: CitationResponse[]): Map<string, string> {
  const map = new Map<string, string>();
  if (!citations) return map;
  for (const c of citations) {
    map.set(c.article.title, c.article.slug);
  }
  return map;
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
  // TODO: This is markdown-unsafe in the fallback paths — slicing
  // raw markdown can land inside a fenced code block, an open link
  // `[text](url)`, or mid-heading, producing malformed output. For
  // long single-paragraph answers with no `\n\n` in the first half
  // this can render oddly. The "Show more" button always reveals
  // the full, well-formed answer, so this is a visual quirk not a
  // correctness bug. A proper fix (e.g. ast-aware truncation or
  // fence-balancing) can land in a follow-up.
  if (text.length <= max) return text;
  // Find the last \n\n before max
  const slice = text.slice(0, max);
  const lastBreak = slice.lastIndexOf("\n\n");
  if (lastBreak > max * 0.5) {
    return slice.slice(0, lastBreak) + "\n\n…";
  }
  // Fall back to nearest sentence end (. ? !)
  const sentenceEnd = Math.max(
    slice.lastIndexOf(". "),
    slice.lastIndexOf("? "),
    slice.lastIndexOf("! "),
  );
  if (sentenceEnd > max * 0.5) {
    return slice.slice(0, sentenceEnd + 1) + " …";
  }
  return slice + "…";
}
