import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { getSourceContent } from "../../api/sources";
import type { CitationTarget } from "./CitationContext";
import { useCitation } from "./CitationContext";
import { Spinner } from "../shared/Spinner";

interface SourceHighlightPanelProps {
  citation: CitationTarget;
}

export function SourceHighlightPanel({ citation }: SourceHighlightPanelProps) {
  const { clearCitation } = useCitation();
  const highlightRef = useRef<HTMLSpanElement>(null);

  const contentQuery = useQuery({
    queryKey: ["source-content", citation.sourceId],
    queryFn: () => getSourceContent(citation.sourceId),
  });

  // Auto-scroll to highlighted span once content loads
  useEffect(() => {
    if (highlightRef.current) {
      highlightRef.current.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
    }
  }, [contentQuery.data]);

  return (
    <div className="flex h-full flex-col overflow-hidden border-l border-slate-200 bg-white transition-all duration-200">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <h2 className="text-sm font-semibold text-slate-900">
          Source Preview
        </h2>
        <button
          onClick={clearCitation}
          className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-brand-600 hover:bg-brand-50 hover:text-brand-800"
          aria-label="Back to article outline"
        >
          <svg
            className="h-3.5 w-3.5"
            fill="none"
            viewBox="0 0 24 24"
            strokeWidth={2}
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M10.5 19.5 3 12m0 0 7.5-7.5M3 12h18"
            />
          </svg>
          Back to article
        </button>
      </div>

      {/* Source info */}
      <div className="border-b border-slate-100 bg-slate-50 px-4 py-3">
        <h3 className="text-sm font-medium text-slate-800">
          {citation.sourceName || "Unknown source"}
        </h3>
        {citation.locatorInfo && (
          <p className="mt-0.5 text-xs text-slate-500">
            {citation.locatorInfo}
          </p>
        )}
      </div>

      {/* Content with highlighted span */}
      <div className="flex-1 overflow-y-auto">
        {contentQuery.isLoading ? (
          <div className="flex items-center justify-center gap-2 p-8 text-sm text-slate-500">
            <Spinner size={16} /> Loading source content...
          </div>
        ) : contentQuery.isError ? (
          <div className="m-4 rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
            Failed to load source content.
          </div>
        ) : contentQuery.data ? (
          <HighlightedSourceText
            content={contentQuery.data.content}
            spanText={citation.spanText}
            highlightRef={highlightRef}
          />
        ) : null}
      </div>
    </div>
  );
}

interface HighlightedSourceTextProps {
  content: string;
  spanText: string;
  highlightRef: React.RefObject<HTMLSpanElement>;
}

function HighlightedSourceText({
  content,
  spanText,
  highlightRef,
}: HighlightedSourceTextProps) {
  // Find the span text in the source content
  const normalizedContent = content;
  const matchIndex = normalizedContent.indexOf(spanText);

  if (matchIndex === -1) {
    // Fallback: show the whole content with the quoted span at the top
    return (
      <div className="px-4 py-4 text-sm leading-relaxed text-slate-700">
        <div className="mb-4 rounded-md border border-amber-200 bg-amber-50 p-3">
          <p className="mb-1 text-xs font-medium text-amber-800">
            Cited passage
          </p>
          <blockquote className="border-l-2 border-amber-300 pl-3 italic text-slate-700">
            {spanText}
          </blockquote>
        </div>
        <div className="border-t border-slate-100 pt-4">
          {content.split(/\n{2,}/).map((para, idx) => (
            <p key={idx} className="mb-3 whitespace-pre-wrap">
              {para}
            </p>
          ))}
        </div>
      </div>
    );
  }

  // Split content into before, match, and after
  const before = content.slice(0, matchIndex);
  const match = content.slice(matchIndex, matchIndex + spanText.length);
  const after = content.slice(matchIndex + spanText.length);

  return (
    <div className="px-4 py-4 text-sm leading-relaxed text-slate-700">
      {before && (
        <span className="whitespace-pre-wrap">{before}</span>
      )}
      <span
        ref={highlightRef}
        className="rounded bg-amber-100 px-0.5 ring-2 ring-amber-300"
      >
        {match}
      </span>
      {after && (
        <span className="whitespace-pre-wrap">{after}</span>
      )}
    </div>
  );
}
