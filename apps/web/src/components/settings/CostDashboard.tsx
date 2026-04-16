import { useQuery } from "@tanstack/react-query";
import { Card } from "../shared/Card";
import { Spinner } from "../shared/Spinner";
import { getCostBreakdown } from "../../api/settings";

interface CostDashboardProps {
  warningThresholdPct?: number;
}

export function CostDashboard({ warningThresholdPct = 80 }: CostDashboardProps) {
  const { data, isLoading } = useQuery({
    queryKey: ["cost-breakdown"],
    queryFn: getCostBreakdown,
    staleTime: 60_000,
  });

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
      ? "bg-red-500"
      : data.budget_pct >= warningThresholdPct
        ? "bg-amber-500"
        : "bg-emerald-500";

  function formatCost(usd: number): string {
    return `$${usd.toFixed(2)}`;
  }

  function formatTaskType(key: string): string {
    return key
      .replace(/_/g, " ")
      .replace(/\b\w/g, (c) => c.toUpperCase());
  }

  return (
    <Card className="p-4">
      <div className="mb-4">
        <div className="h-4 w-full rounded-full bg-slate-200">
          <div
            className={`h-4 rounded-full transition-all ${gaugeColor}`}
            style={{ width: `${pct}%` }}
          />
        </div>
        <p className="mt-1 text-sm text-slate-600">
          {formatCost(data.total_usd)} / {formatCost(data.budget_usd)} ({data.budget_pct.toFixed(1)}%)
        </p>
      </div>

      {Object.keys(data.by_provider).length > 0 && (
        <div className="mb-4">
          <h3 className="mb-2 text-sm font-semibold text-slate-700">By Provider</h3>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                <th className="pb-1 font-medium">Provider</th>
                <th className="pb-1 font-medium">Cost</th>
                <th className="pb-1 font-medium">Calls</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(data.by_provider).map(([provider, entry]) => (
                <tr key={provider} className="border-b border-slate-100">
                  <td className="py-1 capitalize text-slate-700">{provider}</td>
                  <td className="py-1 text-slate-700">{formatCost(entry.cost_usd)}</td>
                  <td className="py-1 text-slate-700">{entry.call_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {Object.keys(data.by_task_type).length > 0 && (
        <div>
          <h3 className="mb-2 text-sm font-semibold text-slate-700">By Task Type</h3>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                <th className="pb-1 font-medium">Task Type</th>
                <th className="pb-1 font-medium">Cost</th>
                <th className="pb-1 font-medium">Calls</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(data.by_task_type).map(([taskType, entry]) => (
                <tr key={taskType} className="border-b border-slate-100">
                  <td className="py-1 text-slate-700">{formatTaskType(taskType)}</td>
                  <td className="py-1 text-slate-700">{formatCost(entry.cost_usd)}</td>
                  <td className="py-1 text-slate-700">{entry.call_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
