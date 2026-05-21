import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useSourceDetail } from "../../hooks/useSources";
import { getBaseUrl } from "../../api/client";
import { Badge, type BadgeTone } from "../shared/Badge";
import { Card } from "../shared/Card";
import { Spinner } from "../shared/Spinner";
import { SourceSpansPanel } from "../viewers/SourceSpansPanel";
import type { IngestStatus, PipelineStep, SourceType } from "../../types/api";

const STATUS_TONE: Record<IngestStatus, BadgeTone> = {
  pending: "neutral",
  processing: "info",
  review_pending: "warning",
  compiled: "success",
  failed: "danger",
};

const STATUS_LABEL: Record<IngestStatus, string> = {
  pending: "Pending",
  processing: "Processing",
  review_pending: "Review",
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

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function StepIcon({ status }: { status: PipelineStep["status"] }) {
  if (status === "complete") {
    return (
      <div className="flex h-7 w-7 items-center justify-center rounded-full bg-emerald-100">
        <svg className="h-4 w-4 text-emerald-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
        </svg>
      </div>
    );
  }
  if (status === "active") {
    return (
      <div className="flex h-7 w-7 items-center justify-center rounded-full bg-brand-100">
        <Spinner size={14} />
      </div>
    );
  }
  if (status === "failed") {
    return (
      <div className="flex h-7 w-7 items-center justify-center rounded-full bg-rose-100">
        <svg className="h-4 w-4 text-rose-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
        </svg>
      </div>
    );
  }
  return (
    <div className="flex h-7 w-7 items-center justify-center rounded-full bg-slate-100">
      <div className="h-2.5 w-2.5 rounded-full bg-slate-300" />
    </div>
  );
}

export function SourceDetailView() {
  const { id } = useParams<{ id: string }>();
  const { data: source, isLoading, isError } = useSourceDetail(id);
  const [selectedImg, setSelectedImg] = useState<string | null>(null);

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner size={24} />
      </div>
    );
  }

  if (isError || !source) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3">
        <p className="text-sm text-slate-600">Source not found.</p>
        <Link to="/inbox" className="text-sm text-brand-600 hover:underline">
          Back to Inbox
        </Link>
      </div>
    );
  }

  const baseUrl = getBaseUrl();

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <header className="border-b border-slate-200 bg-white px-6 py-5">
        <div className="flex items-center gap-3">
          <Link to="/inbox" className="text-sm text-slate-500 hover:text-slate-700">
            Inbox
          </Link>
          <span className="text-slate-300">/</span>
          <span className="text-sm font-medium text-slate-900 truncate">
            {source.title || "Untitled source"}
          </span>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto p-6">
        <div className="mx-auto max-w-3xl space-y-6">
          {/* Metadata card */}
          <Card className="p-5">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0 flex-1">
                <h1 className="text-xl font-semibold text-slate-900 truncate">
                  {source.title || "Untitled source"}
                </h1>
                {source.source_url ? (
                  <a
                    href={source.source_url}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-1 block truncate text-sm text-brand-600 hover:underline"
                  >
                    {source.source_url}
                  </a>
                ) : null}
              </div>
              <div className="flex items-center gap-2">
                <Badge tone="brand">{TYPE_LABEL[source.source_type]}</Badge>
                <Badge tone={STATUS_TONE[source.status]}>
                  {STATUS_LABEL[source.status]}
                </Badge>
              </div>
            </div>

            <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-3">
              {source.author ? (
                <div>
                  <dt className="text-xs font-medium text-slate-500">Author</dt>
                  <dd className="text-slate-900">{source.author}</dd>
                </div>
              ) : null}
              {source.published_date ? (
                <div>
                  <dt className="text-xs font-medium text-slate-500">Published</dt>
                  <dd className="text-slate-900">{source.published_date}</dd>
                </div>
              ) : null}
              <div>
                <dt className="text-xs font-medium text-slate-500">Ingested</dt>
                <dd className="text-slate-900">{formatDate(source.ingested_at)}</dd>
              </div>
              {source.compiled_at ? (
                <div>
                  <dt className="text-xs font-medium text-slate-500">Compiled</dt>
                  <dd className="text-slate-900">{formatDate(source.compiled_at)}</dd>
                </div>
              ) : null}
              {source.token_count ? (
                <div>
                  <dt className="text-xs font-medium text-slate-500">Tokens</dt>
                  <dd className="text-slate-900">{source.token_count.toLocaleString()}</dd>
                </div>
              ) : null}
            </dl>

            {source.error_message ? (
              <div className="mt-4 rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
                {source.error_message}
              </div>
            ) : null}
          </Card>

          {/* Pipeline steps */}
          <Card className="p-5">
            <h2 className="mb-4 text-base font-semibold text-slate-900">
              Processing Pipeline
            </h2>
            <div className="relative">
              {source.pipeline_steps.map((step, idx) => (
                <div key={step.name} className="flex gap-3 pb-4 last:pb-0">
                  <div className="flex flex-col items-center">
                    <StepIcon status={step.status} />
                    {idx < source.pipeline_steps.length - 1 ? (
                      <div className="mt-1 h-full w-px bg-slate-200" />
                    ) : null}
                  </div>
                  <div className="pt-0.5">
                    <p className="text-sm font-medium text-slate-900">{step.name}</p>
                    <p className="text-xs text-slate-500">{step.description}</p>
                  </div>
                </div>
              ))}
            </div>
          </Card>

          {/* Extracted images */}
          {source.images.length > 0 ? (
            <Card className="p-5">
              <h2 className="mb-4 text-base font-semibold text-slate-900">
                Extracted Images ({source.images.length})
              </h2>
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
                {source.images.map((img) => {
                  const imgUrl = `${baseUrl}/api/ingest/sources/${source.id}/images/${img.filename}`;
                  return (
                    <button
                      key={img.filename}
                      type="button"
                      onClick={() => setSelectedImg(imgUrl)}
                      className="group overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm transition hover:border-brand-300 hover:shadow"
                    >
                      <div className="flex items-center justify-center bg-slate-50 p-3">
                        <img
                          src={imgUrl}
                          alt={img.label}
                          className="max-h-32 w-auto object-contain"
                          loading="lazy"
                        />
                      </div>
                      <div className="flex items-center gap-2 border-t border-slate-100 px-3 py-2">
                        <span
                          className={`inline-block h-2 w-2 rounded-full ${
                            img.kind === "table" ? "bg-amber-400" : "bg-brand-400"
                          }`}
                        />
                        <span className="text-xs font-medium text-slate-700">
                          {img.label}
                        </span>
                      </div>
                    </button>
                  );
                })}
              </div>
            </Card>
          ) : null}

          {/* Source spans (extracted passages) */}
          <SourceSpansPanel sourceId={source.id} />

          {/* Linked articles */}
          {source.linked_articles.length > 0 ? (
            <Card className="p-5">
              <h2 className="mb-4 text-base font-semibold text-slate-900">
                Compiled Articles ({source.linked_articles.length})
              </h2>
              <ul className="divide-y divide-slate-100">
                {source.linked_articles.map((article) => (
                  <li key={article.id}>
                    <Link
                      to={`/wiki/${encodeURIComponent(article.slug)}`}
                      className="flex items-center gap-3 py-3 hover:bg-slate-50 -mx-2 px-2 rounded-md transition"
                    >
                      <Badge tone="brand">{article.page_type}</Badge>
                      <span className="text-sm font-medium text-slate-900 truncate">
                        {article.title}
                      </span>
                      <svg
                        className="ml-auto h-4 w-4 text-slate-400"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2}
                          d="M9 5l7 7-7 7"
                        />
                      </svg>
                    </Link>
                  </li>
                ))}
              </ul>
            </Card>
          ) : null}
        </div>
      </div>

      {/* Lightbox */}
      {selectedImg ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-8"
          onClick={() => setSelectedImg(null)}
        >
          <div
            className="relative max-h-[90vh] max-w-[90vw]"
            onClick={(e) => e.stopPropagation()}
          >
            <img
              src={selectedImg}
              alt="Full size"
              className="max-h-[85vh] max-w-full rounded-lg bg-white object-contain shadow-2xl"
            />
            <button
              type="button"
              onClick={() => setSelectedImg(null)}
              className="absolute -right-3 -top-3 flex h-8 w-8 items-center justify-center rounded-full bg-white text-slate-600 shadow-lg hover:bg-slate-100"
              aria-label="Close"
            >
              X
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
