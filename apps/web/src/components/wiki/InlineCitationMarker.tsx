import { useCallback, useRef, useState } from "react";
import { getSourceSpans } from "../../api/sources";
import type { ArticleSourceRef, SourceSpanResponse } from "../../types/api";
import { CitationPopover } from "./CitationPopover";
import type { CitationTarget } from "./CitationContext";

interface InlineCitationMarkerProps {
  /** The article's sources to look up spans from. */
  sources: ArticleSourceRef[];
}

export function InlineCitationMarker({ sources }: InlineCitationMarkerProps) {
  const [popoverCitation, setPopoverCitation] = useState<CitationTarget | null>(
    null,
  );
  const [popoverRect, setPopoverRect] = useState<DOMRect | null>(null);
  const [loading, setLoading] = useState(false);
  const markerRef = useRef<HTMLButtonElement>(null);

  const handleClick = useCallback(async () => {
    if (popoverCitation) {
      setPopoverCitation(null);
      return;
    }
    if (sources.length === 0) return;

    setLoading(true);
    try {
      // Try each source until we find one with spans
      for (const source of sources) {
        const spans: SourceSpanResponse[] = await getSourceSpans(source.id);
        if (spans.length > 0) {
          const span = spans[0];
          const citation: CitationTarget = {
            sourceId: source.id,
            spanText: span.text,
            sourceName: source.title,
            locatorInfo: formatLocator(span),
          };
          setPopoverCitation(citation);
          if (markerRef.current) {
            setPopoverRect(markerRef.current.getBoundingClientRect());
          }
          return;
        }
      }
    } finally {
      setLoading(false);
    }
  }, [popoverCitation, sources]);

  if (sources.length === 0) return null;

  return (
    <>
      <button
        ref={markerRef}
        onClick={handleClick}
        className="ml-0.5 cursor-pointer align-super text-[10px] font-semibold text-brand-600 hover:text-brand-800"
        title="View source citation"
        type="button"
      >
        {loading ? "..." : "[src]"}
      </button>
      {popoverCitation && (
        <CitationPopover
          citation={popoverCitation}
          onClose={() => setPopoverCitation(null)}
          anchorRect={popoverRect}
        />
      )}
    </>
  );
}

function formatLocator(span: SourceSpanResponse): string {
  switch (span.locator_kind) {
    case "pdf-page-rect": {
      const page = span.locator.page ?? span.locator.page_number;
      return page != null ? `page ${page}` : "";
    }
    case "html-xpath-offset": {
      const para = span.locator.paragraph ?? span.locator.index;
      return para != null ? `paragraph #${para}` : "";
    }
    case "text-byte-range":
      return "text";
    case "youtube-timestamp": {
      const ts = span.locator.timestamp ?? span.locator.start;
      return ts != null ? `${ts}s` : "";
    }
    default:
      return "";
  }
}
