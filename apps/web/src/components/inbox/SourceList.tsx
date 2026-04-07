import type { Source } from "../../types/api";
import { Spinner } from "../shared/Spinner";
import { SourceCard } from "./SourceCard";

interface SourceListProps {
  sources: Source[];
  isLoading: boolean;
  isError: boolean;
  onRetry: (sourceId: string) => void;
  retryingId: string | null;
}

export function SourceList({
  sources,
  isLoading,
  isError,
  onRetry,
  retryingId,
}: SourceListProps) {
  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-slate-500">
        <Spinner size={14} /> Loading sources...
      </div>
    );
  }

  if (isError) {
    return (
      <div className="rounded-md border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
        Failed to load sources. Is the gateway running on port 7842?
      </div>
    );
  }

  if (sources.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">
        No sources yet. Paste a URL or drop a PDF above to get started.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
      {sources.map((source) => (
        <SourceCard
          key={source.id}
          source={source}
          onRetry={onRetry}
          retrying={retryingId === source.id}
        />
      ))}
    </div>
  );
}
