import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card } from "../shared/Card";
import { Spinner } from "../shared/Spinner";
import { getCostBreakdown } from "../../api/settings";

interface CostDashboardProps {
  warningThresholdPct?: number;
}

function formatCost(usd: number): string {
  return `$${usd.toFixed(2)}`;
}

function formatTaskType(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function CostDashboard({ warningThresholdPct = 80 }: CostDashboardProps) {
  const { data, isLoading } = useQuery({
    queryKey: ["cost-breakdown"],
    queryFn: getCostBreakdown,
    staleTime: 60_000,
  });

  const totalCalls = useMemo(() => {
    if (!data) return 0;
    return Object.values(data.by_provider).reduce((sum, e) => sum + e.call_count, 0);
  }, [data]);

  if (isLoading) {
    return (
      <Card className="flex items-center justify-center p-6">
        <Spinner />
      </Card>
    );
  }

  if (!data || data.total_usd === 0) {
    return (
      <Card className="p-4">
        <p className="text-sm text-slate-500">No cost data yet.</p>
      </Card>
    );
  }

  const pct = Math.min(data.budget_pct, 100);
  const gaugeColor =
    data.budget_pct >= 100
      ? "bg-rose-500"
      : data.budget_pct >= warningThresholdPct
        ? "bg-amber-500"
        : "bg-emerald-500";
  const gaugeTextColor =
    data.budget_pct >= 100
      ? "text-red-700"
      : data.budget_pct >= warningThresholdPct
        ? "text-amber-700"
        : "text-emerald-700";

  return (
    <div className="space-y-4">
      {/* Summary metric cards */}
      <div className="grid gap-4 sm:grid-cols-3">
        <Card className="p-4">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Spend</p>
          <p className="mt-1 text-2xl font-bold text-slate-800">
            {formatCost(data.total_usd)}
          </p>
          <p className="mt-0.5 text-xs text-slate-400">
            of {formatCost(data.budget_usd)} budget
          </p>
        </Card>
        <Card className="p-4">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Budget Used</p>
          <p className={`mt-1 text-2xl font-bold ${gaugeTextColor}`}>
            {data.budget_pct.toFixed(1)}%
          </p>
          <div className="mt-2 h-2 w-full rounded-full bg-slate-200">
            <div
              className={`h-2 rounded-full transition-all ${gaugeColor}`}
              style={{ width: `${pct}%` }}
            />
          </div>
        </Card>
        <Card className="p-4">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">API Calls</p>
          <p className="mt-1 text-2xl font-bold text-slate-800">
            {totalCalls.toLocaleString()}
          </p>
          <p className="mt-0.5 text-xs text-slate-400">
            {data.month}
          </p>
        </Card>
      </div>

      {/* Breakdown tables */}
      <div className="grid gap-4 sm:grid-cols-2">
        {Object.keys(data.by_provider).length > 0 && (
          <Card className="p-4">
            <h3 className="mb-3 text-sm font-semibold text-slate-700">By Provider</h3>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                  <th className="pb-1 font-medium">Provider</th>
                  <th className="pb-1 text-right font-medium">Cost</th>
                  <th className="pb-1 text-right font-medium">Calls</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(data.by_provider).map(([provider, entry]) => (
                  <tr key={provider} className="border-b border-slate-100">
                    <td className="py-1.5 capitalize text-slate-700">{provider}</td>
                    <td className="py-1.5 text-right font-mono text-slate-700">
                      {formatCost(entry.cost_usd)}
                    </td>
                    <td className="py-1.5 text-right text-slate-700">
                      {entry.call_count}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}

        {Object.keys(data.by_task_type).length > 0 && (
          <Card className="p-4">
            <h3 className="mb-3 text-sm font-semibold text-slate-700">By Task Type</h3>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                  <th className="pb-1 font-medium">Task Type</th>
                  <th className="pb-1 text-right font-medium">Cost</th>
                  <th className="pb-1 text-right font-medium">Calls</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(data.by_task_type).map(([taskType, entry]) => (
                  <tr key={taskType} className="border-b border-slate-100">
                    <td className="py-1.5 text-slate-700">{formatTaskType(taskType)}</td>
                    <td className="py-1.5 text-right font-mono text-slate-700">
                      {formatCost(entry.cost_usd)}
                    </td>
                    <td className="py-1.5 text-right text-slate-700">
                      {entry.call_count}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </div>
    </div>
  );
}
