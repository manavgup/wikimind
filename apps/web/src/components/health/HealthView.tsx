import { LintReportSummary } from "./LintReportSummary";
import { FindingsByKindTabs } from "./FindingsByKindTabs";
import { useLatestReport } from "../../hooks/useLint";

export function HealthView() {
  const { data, isLoading, isError } = useLatestReport();

  return (
    <div className="flex h-full flex-col overflow-auto p-6">
      <LintReportSummary
        detail={data ?? null}
        isLoading={isLoading}
      />

      {data && !isError ? (
        <div className="mt-6">
          <FindingsByKindTabs detail={data} />
        </div>
      ) : isError && !isLoading ? (
        <div className="mt-6 rounded-md border border-slate-200 bg-white p-8 text-center text-sm text-slate-500">
          No lint reports yet. Click "Run lint now" to generate one.
        </div>
      ) : null}
    </div>
  );
}
