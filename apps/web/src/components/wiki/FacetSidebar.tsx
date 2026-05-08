import { useState } from "react";
import type { FacetGroup } from "../../types/api";

interface FacetSidebarProps {
  facets: FacetGroup[];
  activeFilters: Record<string, string>;
  onFilterChange: (name: string, value: string | null) => void;
}

const FACET_LABELS: Record<string, string> = {
  page_type: "Page Type",
  source_kind: "Source Kind",
  concept: "Concept",
  tag: "Tag",
  date: "Date Range",
  staleness: "Staleness",
};

const DATE_LABELS: Record<string, string> = {
  "7d": "Last 7 days",
  "30d": "Last 30 days",
  "365d": "Last year",
};

const STALENESS_LABELS: Record<string, string> = {
  low: "Fresh (< 0.3)",
  medium: "Aging (0.3 - 0.7)",
  high: "Stale (> 0.7)",
};

function getBucketLabel(facetName: string, value: string): string {
  if (facetName === "date") return DATE_LABELS[value] ?? value;
  if (facetName === "staleness") return STALENESS_LABELS[value] ?? value;
  return value;
}

export function FacetSidebar({
  facets,
  activeFilters,
  onFilterChange,
}: FacetSidebarProps) {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  if (facets.length === 0) return null;

  return (
    <div className="space-y-4 p-4" data-testid="facet-sidebar">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Filters
        </h3>
        {Object.keys(activeFilters).length > 0 && (
          <button
            onClick={() => {
              for (const key of Object.keys(activeFilters)) {
                onFilterChange(key, null);
              }
            }}
            className="text-xs text-brand-600 hover:text-brand-800"
          >
            Clear all
          </button>
        )}
      </div>

      {facets.map((facet) => {
        const isCollapsed = collapsed[facet.name] ?? false;
        const activeValue = activeFilters[facet.name];

        return (
          <div
            key={facet.name}
            className="border-t border-slate-100 pt-3 first:border-0 first:pt-0"
          >
            <button
              onClick={() =>
                setCollapsed((prev) => ({
                  ...prev,
                  [facet.name]: !isCollapsed,
                }))
              }
              className="flex w-full items-center justify-between text-left"
            >
              <span className="text-xs font-semibold text-slate-700">
                {FACET_LABELS[facet.name] ?? facet.name}
              </span>
              <svg
                className={`h-3.5 w-3.5 text-slate-400 transition-transform ${
                  isCollapsed ? "" : "rotate-180"
                }`}
                fill="none"
                viewBox="0 0 24 24"
                strokeWidth={2}
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M19.5 8.25l-7.5 7.5-7.5-7.5"
                />
              </svg>
            </button>

            {!isCollapsed && (
              <ul className="mt-2 space-y-1">
                {facet.buckets.map((bucket) => {
                  const isActive = activeValue === bucket.value;
                  return (
                    <li key={bucket.value}>
                      <button
                        onClick={() =>
                          onFilterChange(
                            facet.name,
                            isActive ? null : bucket.value,
                          )
                        }
                        className={`flex w-full items-center justify-between rounded-md px-2 py-1 text-xs transition ${
                          isActive
                            ? "bg-brand-50 font-medium text-brand-700"
                            : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
                        }`}
                      >
                        <span className="truncate">
                          {getBucketLabel(facet.name, bucket.value)}
                        </span>
                        <span
                          className={`ml-2 tabular-nums ${
                            isActive ? "text-brand-500" : "text-slate-400"
                          }`}
                        >
                          {bucket.count}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        );
      })}
    </div>
  );
}
