import { useState } from "react";
import {
  useIngestPdf,
  useIngestUrl,
  useRetryCompile,
  useSources,
} from "../../hooks/useSources";
import { ApiError } from "../../api/client";
import { useWebSocketStore } from "../../store/websocket";
import { QuickAddBar } from "./QuickAddBar";
import { SourceList } from "./SourceList";

export function InboxView() {
  const sourcesQuery = useSources();
  const ingestUrlMutation = useIngestUrl();
  const ingestPdfMutation = useIngestPdf();
  const retryMutation = useRetryCompile();
  const [error, setError] = useState<string | null>(null);

  const handleSubmitUrl = async (url: string) => {
    setError(null);
    try {
      await ingestUrlMutation.mutateAsync(url);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to ingest URL");
    }
  };

  const handleSubmitPdf = async (file: File) => {
    setError(null);
    try {
      await ingestPdfMutation.mutateAsync(file);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to ingest PDF");
    }
  };

  const handleRetry = async (sourceId: string) => {
    setError(null);
    try {
      await retryMutation.mutateAsync(sourceId);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Failed to retry compilation",
      );
    }
  };

  const wsState = useWebSocketStore((s) => s.state);
  const sources = sourcesQuery.data ?? [];

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <header className="border-b border-slate-200 bg-white px-6 py-5">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-slate-900">Inbox</h1>
            <p className="mt-1 text-sm text-slate-500">
              All ingested sources. Live progress streams over WebSocket
              {wsState === "open" ? " (connected)" : ` (${wsState})`}.
            </p>
          </div>
          <div className="text-xs text-slate-500">
            {sources.length} source{sources.length === 1 ? "" : "s"}
          </div>
        </div>
      </header>

      <div className="flex flex-1 flex-col gap-5 overflow-y-auto p-6">
        <QuickAddBar
          onSubmitUrl={handleSubmitUrl}
          onSubmitPdf={handleSubmitPdf}
          isSubmittingUrl={ingestUrlMutation.isPending}
          isSubmittingPdf={ingestPdfMutation.isPending}
        />

        {error ? (
          <div className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
            {error}
          </div>
        ) : null}

        <SourceList
          sources={sources}
          isLoading={sourcesQuery.isLoading}
          isError={sourcesQuery.isError}
          onRetry={handleRetry}
          retryingId={
            retryMutation.isPending && retryMutation.variables
              ? retryMutation.variables
              : null
          }
        />
      </div>
    </div>
  );
}
