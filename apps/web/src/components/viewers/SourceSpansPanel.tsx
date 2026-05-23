import { useMemo } from "react";
import { useSourceSpans } from "../../hooks/useSources";
import { Badge } from "../shared/Badge";
import { Card } from "../shared/Card";
import { Spinner } from "../shared/Spinner";
import type { LocatorKind, SourceSpanResponse } from "../../types/api";

const LOCATOR_LABEL: Record<LocatorKind, string> = {
  "pdf-page-rect": "PDF Page",
  "html-xpath-offset": "HTML",
  "text-byte-range": "Bytes",
  "youtube-timestamp": "YouTube",
};

function formatLocator(kind: LocatorKind, locator: Record<string, unknown>): string {
  switch (kind) {
    case "pdf-page-rect": {
      const page = locator.page ?? locator.page_number;
      return page != null ? `page ${page}` : "page ?";
    }
    case "html-xpath-offset": {
      const para = locator.paragraph ?? locator.index;
      return para != null ? `paragraph #${para}` : "xpath";
    }
    case "text-byte-range": {
      const start = locator.start ?? locator.byte_start;
      const end = locator.end ?? locator.byte_end;
      if (start != null && end != null) return `bytes ${start}-${end}`;
      if (start != null) return `byte ${start}`;
      return "byte range";
    }
    case "youtube-timestamp": {
      const ts = locator.timestamp ?? locator.start;
      return ts != null ? `${ts}s` : "timestamp";
    }
    default:
      return JSON.stringify(locator);
  }
}

function SpanCard({ span }: { span: SourceSpanResponse }) {
  const truncatedFingerprint = span.fingerprint.slice(0, 12);

  return (
    <div className="rounded-md border border-slate-200 bg-white p-3">
      <blockquote className="border-l-2 border-brand-300 pl-3 text-sm italic text-slate-700">
        {span.text}
      </blockquote>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Badge tone="info">
          {LOCATOR_LABEL[span.locator_kind]} &middot; {formatLocator(span.locator_kind, span.locator)}
        </Badge>
        <span className="font-mono text-xs text-slate-400" title={span.fingerprint}>
          {truncatedFingerprint}
        </span>
      </div>
    </div>
  );
}

interface SourceSpansPanelProps {
  sourceId: string;
}

export function SourceSpansPanel({ sourceId }: SourceSpansPanelProps) {
  const { data: spans, isLoading, isError } = useSourceSpans(sourceId);

  const grouped = useMemo(() => {
    if (!spans || spans.length === 0) return null;

    const groups = new Map<LocatorKind, SourceSpanResponse[]>();
    for (const span of spans) {
      const existing = groups.get(span.locator_kind);
      if (existing) {
        existing.push(span);
      } else {
        groups.set(span.locator_kind, [span]);
      }
    }

    return groups;
  }, [spans]);

  if (isLoading) {
    return (
      <Card className="p-5">
        <div className="flex items-center gap-2">
          <Spinner size={16} />
          <span className="text-sm text-slate-500">Loading source spans...</span>
        </div>
      </Card>
    );
  }

  if (isError) {
    return (
      <Card className="p-5">
        <p className="text-sm text-slate-500">Failed to load source spans.</p>
      </Card>
    );
  }

  if (!spans || spans.length === 0) {
    return null;
  }

  const hasMultipleKinds = grouped != null && grouped.size > 1;

  return (
    <Card className="p-5">
      <h2 className="mb-4 text-base font-semibold text-slate-900">
        Extracted Passages ({spans.length})
      </h2>

      {hasMultipleKinds ? (
        <div className="space-y-5">
          {Array.from(grouped!.entries()).map(([kind, kindSpans]) => (
            <div key={kind}>
              <h3 className="mb-2 text-sm font-medium text-slate-600">
                {LOCATOR_LABEL[kind]} ({kindSpans.length})
              </h3>
              <div className="space-y-2">
                {kindSpans.map((span) => (
                  <SpanCard key={span.id} span={span} />
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="space-y-2">
          {spans.map((span) => (
            <SpanCard key={span.id} span={span} />
          ))}
        </div>
      )}
    </Card>
  );
}
