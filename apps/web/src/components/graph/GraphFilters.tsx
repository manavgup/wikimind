import type { Concept, ConfidenceLevel } from "../../types/api";

const CONFIDENCE_LEVELS: ConfidenceLevel[] = ["sourced", "mixed", "inferred", "opinion"];

export interface GraphFilterState {
  selectedConcepts: Set<string>;
  selectedConfidence: Set<ConfidenceLevel>;
  showOrphans: boolean;
}

interface GraphFiltersProps {
  concepts: Concept[];
  filters: GraphFilterState;
  totalNodeCount: number;
  visibleNodeCount: number;
  onToggleConcept: (conceptName: string) => void;
  onToggleConfidence: (level: ConfidenceLevel) => void;
  onToggleOrphans: () => void;
  onResetFilters: () => void;
}

export function GraphFilters({
  concepts,
  filters,
  totalNodeCount,
  visibleNodeCount,
  onToggleConcept,
  onToggleConfidence,
  onToggleOrphans,
  onResetFilters,
}: GraphFiltersProps) {
  const hasActiveFilters =
    filters.selectedConcepts.size > 0 ||
    filters.selectedConfidence.size > 0 ||
    !filters.showOrphans;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-800">Filters</h3>
        {hasActiveFilters && (
          <button
            type="button"
            onClick={onResetFilters}
            className="text-xs text-brand-600 hover:text-brand-700"
          >
            Reset
          </button>
        )}
      </div>

      <p className="text-xs text-slate-500">
        Showing {visibleNodeCount} of {totalNodeCount} nodes
      </p>

      {/* Concept filters */}
      <div>
        <h4 className="mb-2 text-xs font-medium text-slate-600">Concepts</h4>
        <div className="flex max-h-48 flex-col gap-1 overflow-y-auto">
          {concepts.length === 0 ? (
            <p className="text-xs text-slate-400">No concepts</p>
          ) : (
            concepts.map((c) => (
              <label
                key={c.id}
                className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-xs text-slate-700 hover:bg-slate-50"
              >
                <input
                  type="checkbox"
                  checked={filters.selectedConcepts.has(c.name)}
                  onChange={() => onToggleConcept(c.name)}
                  className="rounded border-slate-300 text-brand-600 focus:ring-brand-500"
                />
                <span className="truncate">{c.name}</span>
                <span className="ml-auto text-slate-400">{c.article_count}</span>
              </label>
            ))
          )}
        </div>
      </div>

      {/* Confidence filters */}
      <div>
        <h4 className="mb-2 text-xs font-medium text-slate-600">Confidence</h4>
        <div className="flex flex-col gap-1">
          {CONFIDENCE_LEVELS.map((level) => (
            <label
              key={level}
              className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-xs text-slate-700 hover:bg-slate-50"
            >
              <input
                type="checkbox"
                checked={filters.selectedConfidence.has(level)}
                onChange={() => onToggleConfidence(level)}
                className="rounded border-slate-300 text-brand-600 focus:ring-brand-500"
              />
              <span className="capitalize">{level}</span>
            </label>
          ))}
        </div>
      </div>

      {/* Orphan toggle */}
      <div>
        <label className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-xs text-slate-700 hover:bg-slate-50">
          <input
            type="checkbox"
            checked={filters.showOrphans}
            onChange={onToggleOrphans}
            className="rounded border-slate-300 text-brand-600 focus:ring-brand-500"
          />
          <span>Show orphan nodes</span>
        </label>
      </div>
    </div>
  );
}
