import { useMemo } from "react";
import type { IngestStatus, Source, SourceType } from "../../types/api";
import { Badge, type BadgeTone } from "../shared/Badge";
import { Button } from "../shared/Button";
import { Card } from "../shared/Card";
import { Spinner } from "../shared/Spinner";
import { useWebSocketStore } from "../../store/websocket";
import { JobProgressBar } from "./JobProgressBar";

interface SourceCardProps {
  source: Source;
  onRetry?: (sourceId: string) => void;
  retrying?: boolean;
}

const STATUS_TONE: Record<IngestStatus, BadgeTone> = {
  pending: "neutral",
  processing: "info",
  compiled: "success",
  failed: "danger",
};

const STATUS_LABEL: Record<IngestStatus, string> = {
  pending: "Pending",
  processing: "Compiling",
  compiled: "Done",
  failed: "Failed",
};

const TYPE_LABEL: Record<SourceType, string> = {
  url: "URL",
  pdf: "PDF",
  youtube: "YouTube",
  audio: "Audio",
  text: "Note",
  rss: "RSS",
  email: "Email",
  obsidian: "Obsidian",
};

function formatTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export function SourceCard({ source, onRetry, retrying }: SourceCardProps) {
  // The compile job for this source is most-recently broadcast under its source_id.
  // Job IDs differ from source IDs, so we display the most-recent in-flight job's
  // progress only when this card is in `processing`.
  const latestJob = useWebSocketStore((s) => {
    const entries = Object.values(s.jobs);
    if (entries.length === 0) return null;
    return entries.sort((a, b) => b.updatedAt - a.updatedAt)[0] ?? null;
  });

  const showProgress = source.status === "processing" && latestJob !== null;

  const titleText = useMemo(() => {
    if (source.title && source.title.trim().length > 0) return source.title;
    if (source.source_url) return source.source_url;
    return "Untitled source";
  }, [source.title, source.source_url]);

  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <Badge tone="brand">{TYPE_LABEL[source.source_type]}</Badge>
            <Badge tone={STATUS_TONE[source.status]}>
              {source.status === "processing" ? (
                <>
                  <Spinner size={10} /> {STATUS_LABEL[source.status]}
                </>
              ) : (
                STATUS_LABEL[source.status]
              )}
            </Badge>
          </div>
          <h3 className="mt-2 truncate text-sm font-semibold text-slate-900">
            {titleText}
          </h3>
          {source.source_url ? (
            <a
              href={source.source_url}
              target="_blank"
              rel="noreferrer"
              className="mt-0.5 block truncate text-xs text-brand-600 hover:underline"
            >
              {source.source_url}
            </a>
          ) : null}
        </div>
        <div className="text-right text-xs text-slate-400">
          {formatTimestamp(source.ingested_at)}
        </div>
      </div>

      {showProgress && latestJob ? (
        <div className="mt-3">
          <JobProgressBar pct={latestJob.pct} message={latestJob.message} />
        </div>
      ) : null}

      {source.status === "failed" ? (
        <div className="mt-3 space-y-2">
          {source.error_message ? (
            <p className="text-xs text-rose-700">{source.error_message}</p>
          ) : null}
          {onRetry ? (
            <Button
              size="sm"
              variant="secondary"
              onClick={() => onRetry(source.id)}
              disabled={retrying}
            >
              {retrying ? <Spinner size={12} /> : null}
              Retry compile
            </Button>
          ) : null}
        </div>
      ) : null}
    </Card>
  );
}
