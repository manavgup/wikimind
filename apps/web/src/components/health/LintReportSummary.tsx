import { Badge } from "../shared/Badge";
import { Card } from "../shared/Card";
import { RunLintButton } from "./RunLintButton";
import type { LintReportDetail } from "../../api/lint";

interface Props {
  detail: LintReportDetail | null;
  isLoading: boolean;
}

function formatDate(iso: string | null): string {
  if (!iso) return "Never";
  return new Date(iso).toLocaleString();
}

export function LintReportSummary({ detail, isLoading }: Props) {
  const report = detail?.report ?? null;
  if (isLoading) {
    return (
      <Card className="p-5">
        <p className="text-sm text-slate-500">Loading report...</p>
      </Card>
    );
  }

  if (!report) {
    return (
      <Card className="p-5">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-800">
              Wiki Health
            </h2>
            <p className="mt-1 text-sm text-slate-500">
              No lint reports yet. Run the linter to generate a health report.
            </p>
          </div>
          <RunLintButton />
        </div>
      </Card>
    );
  }

  const statusTone =
    report.status === "complete"
      ? "success"
      : report.status === "failed"
        ? "danger"
        : "info";

  return (
    <Card className="p-5">
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-semibold text-slate-800">
              Wiki Health
            </h2>
            <Badge tone={statusTone}>
              {report.status === "in_progress" ? "Running" : report.status}
            </Badge>
          </div>
          <p className="mt-1 text-sm text-slate-500">
            Last run: {formatDate(report.generated_at)} | {report.article_count}{" "}
            articles scanned
          </p>
        </div>
        <RunLintButton />
      </div>

      {/* Progress bar when running */}
      {report.status === "in_progress" && report.total_pairs > 0 && (
        <div className="mt-3">
          <div className="flex items-center justify-between text-xs text-slate-500">
            <span>
              Checking pair {report.checked_pairs} of {report.total_pairs}...
            </span>
            <span>
              {Math.round((report.checked_pairs / report.total_pairs) * 100)}%
            </span>
          </div>
          <div className="mt-1 h-2 overflow-hidden rounded-full bg-slate-200">
            <div
              className="h-full rounded-full bg-brand-500 transition-all"
              style={{
                width: `${Math.round((report.checked_pairs / report.total_pairs) * 100)}%`,
              }}
            />
          </div>
        </div>
      )}

      <div className="mt-4 grid grid-cols-3 gap-4">
        {(() => {
          const resolutions = detail?.resolutions ?? {};
          const resolvedCount = Object.keys(resolutions).length;
          const unresolvedContradictions =
            (detail?.contradictions.length ?? 0) - resolvedCount;
          const orphanCount = detail?.orphans.length ?? 0;
          const activeCount = unresolvedContradictions + orphanCount;

          return (
            <>
              <div className="rounded-md border border-slate-200 p-3 text-center">
                <div className="text-2xl font-bold text-slate-800">
                  {activeCount}
                </div>
                <div className="text-xs text-slate-500">
                  Active findings
                  {(report.dismissed_count > 0 || resolvedCount > 0) && (
                    <span className="ml-1 text-slate-400">
                      ({report.dismissed_count} dismissed
                      {resolvedCount > 0 && `, ${resolvedCount} resolved`})
                    </span>
                  )}
                </div>
              </div>
              <div className="rounded-md border border-slate-200 p-3 text-center">
                <div className="text-2xl font-bold text-amber-600">
                  {unresolvedContradictions}
                </div>
                <div className="text-xs text-slate-500">Contradictions</div>
              </div>
              <div className="rounded-md border border-slate-200 p-3 text-center">
                <div className="text-2xl font-bold text-sky-600">
                  {orphanCount}
                </div>
                <div className="text-xs text-slate-500">Orphans</div>
              </div>
            </>
          );
        })()}
      </div>

      {report.error_message ? (
        <div className="mt-3 rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
          {report.error_message}
        </div>
      ) : null}
    </Card>
  );
}
