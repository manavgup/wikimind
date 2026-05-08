import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getSourceContent } from "../../api/sources";
import type { ArticleSourceRef, SourceContentResponse } from "../../types/api";
import { Spinner } from "../shared/Spinner";
import { Badge } from "../shared/Badge";

interface SourcePanelProps {
  sources: ArticleSourceRef[];
  onClose: () => void;
}

const SOURCE_TYPE_LABELS: Record<string, string> = {
  url: "Web Page",
  pdf: "PDF",
  youtube: "YouTube",
  audio: "Audio",
  text: "Text",
  rss: "RSS",
  email: "Email",
  obsidian: "Obsidian",
};

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function SourcePanel({ sources, onClose }: SourcePanelProps) {
  const [selectedId, setSelectedId] = useState<string | null>(
    sources.length > 0 ? sources[0].id : null,
  );

  const contentQuery = useQuery({
    queryKey: ["source-content", selectedId],
    queryFn: () => getSourceContent(selectedId as string),
    enabled: Boolean(selectedId),
  });

  const selectedSource = sources.find((s) => s.id === selectedId);

  return (
    <div className="flex h-full flex-col overflow-hidden border-l border-slate-200 bg-white">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <h2 className="text-sm font-semibold text-slate-900">Sources</h2>
        <button
          onClick={onClose}
          className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          aria-label="Close source panel"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {sources.length === 0 ? (
        <div className="p-4 text-sm text-slate-400">No sources available.</div>
      ) : (
        <>
          <div className="border-b border-slate-200 p-2">
            <ul className="flex flex-col gap-1">
              {sources.map((source) => (
                <li key={source.id}>
                  <button
                    onClick={() => setSelectedId(source.id)}
                    className={`w-full rounded-md px-3 py-2 text-left text-sm transition-colors ${
                      selectedId === source.id
                        ? "bg-brand-50 text-brand-800 font-medium"
                        : "text-slate-700 hover:bg-slate-50"
                    }`}
                  >
                    <span className="block truncate">
                      {source.title || "Untitled source"}
                    </span>
                    <span className="mt-0.5 flex items-center gap-2 text-xs text-slate-500">
                      <Badge tone="neutral">
                        {SOURCE_TYPE_LABELS[source.source_type] || source.source_type}
                      </Badge>
                      {formatDate(source.ingested_at)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>

          <div className="flex-1 overflow-y-auto">
            {selectedSource && (
              <div className="border-b border-slate-100 bg-slate-50 px-4 py-3">
                <h3 className="text-sm font-medium text-slate-800">
                  {selectedSource.title || "Untitled source"}
                </h3>
                <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                  <Badge tone="neutral">
                    {SOURCE_TYPE_LABELS[selectedSource.source_type] || selectedSource.source_type}
                  </Badge>
                  {selectedSource.source_url && (
                    <a
                      href={selectedSource.source_url}
                      target="_blank"
                      rel="noreferrer"
                      className="truncate text-brand-600 hover:underline"
                    >
                      {selectedSource.source_url}
                    </a>
                  )}
                  <span>{formatDate(selectedSource.ingested_at)}</span>
                </div>
              </div>
            )}

            {contentQuery.isLoading ? (
              <div className="flex items-center justify-center gap-2 p-8 text-sm text-slate-500">
                <Spinner size={16} /> Loading source content...
              </div>
            ) : contentQuery.isError ? (
              <div className="m-4 rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
                Failed to load source content.
              </div>
            ) : contentQuery.data ? (
              <SourceText content={contentQuery.data.content} />
            ) : null}
          </div>
        </>
      )}
    </div>
  );
}

function SourceText({ content }: { content: string }) {
  const paragraphs = content.split(/\n{2,}/);

  return (
    <div className="px-4 py-4 text-sm leading-relaxed text-slate-700">
      {paragraphs.map((para, idx) => (
        <p key={idx} className="mb-3 whitespace-pre-wrap">
          {para}
        </p>
      ))}
    </div>
  );
}
