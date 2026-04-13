import { useCallback, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { CitationResponse, QueryRecord } from "../../api/query";

const COLLAPSE_THRESHOLD_CHARS = 800;

interface Props {
  query: QueryRecord;
  onEdit?: (turnIndex: number, newQuestion: string) => void;
  forkCount?: number;
  selectionMode?: boolean;
  isSelected?: boolean;
  onToggleSelect?: () => void;
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
export function TurnCard({ query, onEdit, forkCount, selectionMode, isSelected, onToggleSelect }: Props) {
  const sources = useMemo(() => parseSources(query.source_article_ids), [query.source_article_ids]);
  const slugByTitle = useMemo(() => buildSlugMap(query.citations), [query.citations]);
  const relatedArticles = useMemo(
    () => parseSources(query.related_article_ids),
    [query.related_article_ids],
  );
  const isLong = query.answer.length > COLLAPSE_THRESHOLD_CHARS;
  const [expanded, setExpanded] = useState(!isLong);
  const [isEditing, setIsEditing] = useState(false);
  const [editText, setEditText] = useState(query.question);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleEditSubmit = useCallback(() => {
    const trimmed = editText.trim();
    if (trimmed && trimmed !== query.question && onEdit) {
      onEdit(query.turn_index, trimmed);
    }
    setIsEditing(false);
  }, [editText, query.question, query.turn_index, onEdit]);

  const handleEditKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleEditSubmit();
      } else if (e.key === "Escape") {
        setIsEditing(false);
        setEditText(query.question);
      }
    },
    [handleEditSubmit, query.question],
  );

  const displayed = expanded
    ? query.answer
    : truncateOnParagraphBoundary(query.answer, COLLAPSE_THRESHOLD_CHARS);

  return (
    <article
      className={`group rounded-lg border p-5 shadow-sm ${
        selectionMode && isSelected
          ? "border-blue-400 bg-blue-50"
          : "border-slate-200 bg-white"
      }`}
    >
      <header className="mb-3 flex items-start gap-3">
        {selectionMode && (
          <input
            type="checkbox"
            checked={isSelected ?? false}
            onChange={onToggleSelect}
            className="mt-1 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
            aria-label={`Select turn Q${query.turn_index + 1}`}
          />
        )}
        <div className="flex-1">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium uppercase tracking-wide text-slate-400">
                Q{query.turn_index + 1}
              </span>
              {forkCount !== undefined && forkCount > 0 && (
                <span
                  className="inline-flex items-center gap-0.5 rounded bg-purple-50 px-1.5 py-0.5 text-xs font-medium text-purple-600"
                  title={`${forkCount} branch${forkCount === 1 ? "" : "es"}`}
                >
                  <svg className="h-3 w-3" viewBox="0 0 16 16" fill="currentColor">
                    <path d="M5 3.25a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0ZM5 12.75a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0ZM12.5 3.25a.75.75 0 1 1-1.5 0 .75.75 0 0 1 1.5 0ZM4.25 4.5a.75.75 0 0 1 .75.75v3.5a.75.75 0 0 1-1.5 0v-3.5a.75.75 0 0 1 .75-.75ZM11 4.5a.75.75 0 0 1 .75.75v1a2.25 2.25 0 0 1-2.25 2.25H6.56l1.22-1.22a.75.75 0 0 0-1.06-1.06l-2.5 2.5a.75.75 0 0 0 0 1.06l2.5 2.5a.75.75 0 1 0 1.06-1.06L6.56 10h2.94A3.75 3.75 0 0 0 13.25 6.25v-1A.75.75 0 0 0 12.5 4.5Z"/>
                  </svg>
                  {forkCount}
                </span>
              )}
            </div>
            {onEdit && !isEditing && !selectionMode && (
              <button
                type="button"
                onClick={() => {
                  setIsEditing(true);
                  setEditText(query.question);
                  setTimeout(() => textareaRef.current?.focus(), 0);
                }}
                className="rounded p-1 text-slate-300 opacity-0 transition-opacity hover:bg-slate-100 hover:text-slate-600 group-hover:opacity-100"
                title="Edit question (creates a branch)"
                aria-label="Edit question"
              >
                <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                  <path d="M2.695 14.763l-1.262 3.154a.5.5 0 00.65.65l3.155-1.262a4 4 0 001.343-.885L17.5 5.5a2.121 2.121 0 00-3-3L3.58 13.42a4 4 0 00-.885 1.343z"/>
                </svg>
              </button>
            )}
          </div>
          {isEditing ? (
            <div className="mt-1">
              <textarea
                ref={textareaRef}
                value={editText}
                onChange={(e) => setEditText(e.target.value)}
                onKeyDown={handleEditKeyDown}
                rows={2}
                className="w-full resize-none rounded border border-blue-300 bg-blue-50 p-2 text-sm text-slate-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
              <div className="mt-1 flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleEditSubmit}
                  disabled={!editText.trim() || editText.trim() === query.question}
                  className="rounded bg-blue-600 px-3 py-1 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
                >
                  Fork
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setIsEditing(false);
                    setEditText(query.question);
                  }}
                  className="rounded px-3 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100"
                >
                  Cancel
                </button>
                <span className="text-xs text-slate-400">
                  This creates a new branch
                </span>
              </div>
            </div>
          ) : (
            <h3 className="mt-1 text-base font-semibold text-slate-900">{query.question}</h3>
          )}
        </div>
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
            const slug = slugByTitle.get(title) || slugifyTitle(title);
            return (
              <Link
                key={`${title}-${i}`}
                to={`/wiki/${encodeURIComponent(slug)}`}
                className="rounded-full bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700 hover:bg-blue-100 hover:underline"
              >
                {title}
              </Link>
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
            const slug = slugByTitle.get(title) || slugifyTitle(title);
            return (
              <Link
                key={`related-${title}-${i}`}
                to={`/wiki/${encodeURIComponent(slug)}`}
                className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700 hover:bg-emerald-100 hover:underline"
              >
                {title}
              </Link>
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

/**
 * Derive a slug from an article title — matches the backend's slugify logic.
 * Used as a fallback when citations don't resolve (e.g. title mismatch).
 */
function slugifyTitle(title: string): string {
  return title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
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
