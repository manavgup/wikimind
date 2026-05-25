import { useEffect, useRef } from "react";
import type { CitationTarget } from "./CitationContext";
import { useCitation } from "./CitationContext";

interface CitationPopoverProps {
  /** The citation data to display. */
  citation: CitationTarget;
  /** Callback to close the popover. */
  onClose: () => void;
  /** Anchor element for positioning (popover appears below it). */
  anchorRect: DOMRect | null;
}

export function CitationPopover({
  citation,
  onClose,
  anchorRect,
}: CitationPopoverProps) {
  const ref = useRef<HTMLDivElement>(null);
  const { showCitation } = useCitation();

  // Close on click outside
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose();
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [onClose]);

  // Close on Escape
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onClose]);

  if (!anchorRect) return null;

  const style: React.CSSProperties = {
    position: "fixed",
    top: anchorRect.bottom + 8,
    left: Math.max(8, anchorRect.left - 120),
    zIndex: 50,
  };

  return (
    <div
      ref={ref}
      className="w-80 rounded-lg border border-gray-200 bg-white p-4 shadow-lg transition-all duration-200"
      style={style}
    >
      {/* Quoted span text */}
      <blockquote className="mb-3 border-l-2 border-brand-300 pl-3 text-sm italic text-slate-700">
        {citation.spanText.length > 200
          ? citation.spanText.slice(0, 200) + "..."
          : citation.spanText}
      </blockquote>

      {/* Source info */}
      <div className="mb-3 flex items-center gap-2 text-xs text-slate-500">
        <span className="font-medium text-slate-700">
          {citation.sourceName || "Unknown source"}
        </span>
        {citation.locatorInfo && (
          <>
            <span className="text-slate-300">&middot;</span>
            <span>{citation.locatorInfo}</span>
          </>
        )}
      </div>

      {/* View in source link */}
      <button
        onClick={() => {
          showCitation(citation);
          onClose();
        }}
        className="inline-flex items-center gap-1 text-xs font-medium text-brand-600 hover:text-brand-800"
      >
        <svg
          className="h-3.5 w-3.5"
          fill="none"
          viewBox="0 0 24 24"
          strokeWidth={1.5}
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M13.5 6H5.25A2.25 2.25 0 0 0 3 8.25v10.5A2.25 2.25 0 0 0 5.25 21h10.5A2.25 2.25 0 0 0 18 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25"
          />
        </svg>
        View in source
      </button>
    </div>
  );
}
