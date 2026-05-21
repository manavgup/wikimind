import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getArticleClaims, type ClaimConfidenceItem } from "../../api/wiki";
import { Badge, type BadgeTone } from "../shared/Badge";
import { Spinner } from "../shared/Spinner";

interface ClaimsPanelProps {
  articleId: string;
}

function confidenceColor(score: number): string {
  if (score >= 0.8) return "bg-emerald-500";
  if (score >= 0.5) return "bg-amber-400";
  return "bg-rose-500";
}

function confidenceTrackColor(score: number): string {
  if (score >= 0.8) return "bg-emerald-100";
  if (score >= 0.5) return "bg-amber-100";
  return "bg-rose-100";
}

function levelTone(level: string): BadgeTone {
  switch (level) {
    case "sourced":
      return "success";
    case "mixed":
      return "info";
    case "inferred":
      return "warning";
    case "opinion":
      return "neutral";
    default:
      return "neutral";
  }
}

function levelLabel(level: string): string {
  return level.charAt(0).toUpperCase() + level.slice(1);
}

function ClaimCard({ claim }: { claim: ClaimConfidenceItem }) {
  const pct = Math.round(claim.confidence_score * 100);

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <p className="text-sm text-slate-800">{claim.text}</p>
      <div className="mt-3 flex items-center gap-3">
        {/* Confidence bar */}
        <div className="flex flex-1 items-center gap-2">
          <div
            className={`h-2 flex-1 overflow-hidden rounded-full ${confidenceTrackColor(claim.confidence_score)}`}
          >
            <div
              className={`h-full rounded-full transition-all ${confidenceColor(claim.confidence_score)}`}
              style={{ width: `${pct}%` }}
            />
          </div>
          <span className="text-xs font-medium text-slate-600">{pct}%</span>
        </div>
        {/* Level badge */}
        <Badge tone={levelTone(claim.confidence_level)}>
          {levelLabel(claim.confidence_level)}
        </Badge>
        {/* Source count */}
        {claim.source_ids.length > 0 && (
          <span className="text-xs text-slate-500">
            {claim.source_ids.length} source{claim.source_ids.length !== 1 ? "s" : ""}
          </span>
        )}
      </div>
    </div>
  );
}

export function ClaimsPanel({ articleId }: ClaimsPanelProps) {
  const [open, setOpen] = useState(false);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["article-claims", articleId],
    queryFn: () => getArticleClaims(articleId),
    enabled: open,
    staleTime: 60_000,
  });

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="flex items-center gap-2 rounded-md bg-slate-50 px-3 py-1.5 text-sm text-slate-700 transition-colors hover:bg-slate-100"
      >
        <svg
          className="h-4 w-4"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"
          />
        </svg>
        View claim confidence
      </button>
    );
  }

  const aggregatePct = data
    ? Math.round(data.article_confidence_score * 100)
    : 0;

  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <h3 className="text-sm font-semibold text-slate-700">
          Claim Confidence
        </h3>
        <button
          onClick={() => setOpen(false)}
          className="text-slate-400 hover:text-slate-600"
          title="Close claims panel"
        >
          <svg
            className="h-4 w-4"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M6 18L18 6M6 6l12 12"
            />
          </svg>
        </button>
      </div>

      {/* Content */}
      <div className="px-4 py-4">
        {isLoading && (
          <div className="flex items-center justify-center py-6">
            <Spinner size={20} />
            <span className="ml-2 text-sm text-slate-500">
              Loading claims...
            </span>
          </div>
        )}

        {isError && (
          <p className="text-sm text-rose-600">Failed to load claims.</p>
        )}

        {data && (
          <>
            {/* Aggregate score */}
            <div className="mb-4 rounded-md border border-slate-100 bg-slate-50 p-3">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-slate-700">
                  Article confidence
                </span>
                <span
                  className={`text-sm font-semibold ${
                    data.article_confidence_score >= 0.8
                      ? "text-emerald-700"
                      : data.article_confidence_score >= 0.5
                        ? "text-amber-700"
                        : "text-rose-700"
                  }`}
                >
                  {aggregatePct}%
                </span>
              </div>
              <div
                className={`mt-2 h-2 overflow-hidden rounded-full ${confidenceTrackColor(data.article_confidence_score)}`}
              >
                <div
                  className={`h-full rounded-full transition-all ${confidenceColor(data.article_confidence_score)}`}
                  style={{ width: `${aggregatePct}%` }}
                />
              </div>
              <p className="mt-1 text-xs text-slate-500">
                {data.claims.length} claim{data.claims.length !== 1 ? "s" : ""}{" "}
                analyzed
              </p>
            </div>

            {/* Claim list */}
            {data.claims.length > 0 ? (
              <div className="space-y-3">
                {data.claims.map((claim) => (
                  <ClaimCard key={claim.id} claim={claim} />
                ))}
              </div>
            ) : (
              <p className="text-sm italic text-slate-500">
                No claims have been extracted for this article yet.
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
