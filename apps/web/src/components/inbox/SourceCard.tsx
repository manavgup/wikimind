import { useCallback, useMemo, useState } from "react";
import type { IngestStatus, Source, SourceType } from "../../types/api";
import { getSourceContent } from "../../api/sources";
import { Badge, type BadgeTone } from "../shared/Badge";
import { Button } from "../shared/Button";
import { Card } from "../shared/Card";
import { Spinner } from "../shared/Spinner";
import { useWebSocketStore } from "../../store/websocket";

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
  processing: "Processing",
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

interface SourceContentModalProps {
  filename: string;
  content: string;
  onClose: () => void;
}

function SourceContentModal({
  filename,
  content,
  onClose,
}: SourceContentModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="flex max-h-[80vh] w-full max-w-2xl flex-col rounded-lg border border-slate-200 bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
          <h2 className="truncate text-lg font-semibold text-slate-800">
            {filename}
          </h2>
          <Button variant="ghost" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>
        <div className="overflow-auto p-6">
          <pre className="whitespace-pre-wrap break-words font-mono text-sm text-slate-700">
            {content}
          </pre>
        </div>
      </div>
    </div>
  );
}

export function SourceCard({ source, onRetry, retrying }: SourceCardProps) {
  const statusMessage = useWebSocketStore(
    (s) => s.sourceStatus[source.id] ?? null,
  );

  const [viewState, setViewState] = useState<
    | { status: "idle" }
    | { status: "loading" }
    | { status: "open"; content: string; filename: string }
    | { status: "error"; message: string }
  >({ status: "idle" });

  const titleText = useMemo(() => {
    if (source.title && source.title.trim().length > 0) return source.title;
    if (source.source_url) return source.source_url;
    return "Untitled source";
  }, [source.title, source.source_url]);

  const handleViewSource = useCallback(async () => {
    setViewState({ status: "loading" });
    try {
      const result = await getSourceContent(source.id);
      setViewState({
        status: "open",
        content: result.content,
        filename: result.filename,
      });
    } catch {
      setViewState({ status: "error", message: "Failed to load source content" });
    }
  }, [source.id]);

  return (
    <>
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

        {source.status === "processing" && statusMessage ? (
          <p className="mt-2 text-xs text-slate-500">{statusMessage}</p>
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

        {source.file_path ? (
          <div className="mt-3">
            <Button
              size="sm"
              variant="secondary"
              onClick={handleViewSource}
              disabled={viewState.status === "loading"}
            >
              {viewState.status === "loading" ? <Spinner size={12} /> : null}
              View Source
            </Button>
            {viewState.status === "error" ? (
              <p className="mt-1 text-xs text-rose-700">{viewState.message}</p>
            ) : null}
          </div>
        ) : null}
      </Card>

      {viewState.status === "open" ? (
        <SourceContentModal
          filename={viewState.filename}
          content={viewState.content}
          onClose={() => setViewState({ status: "idle" })}
        />
      ) : null}
    </>
  );
}
