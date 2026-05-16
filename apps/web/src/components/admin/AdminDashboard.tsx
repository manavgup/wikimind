import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Card } from "../shared/Card";
import { Badge } from "../shared/Badge";
import type { BadgeTone } from "../shared/Badge";
import { Button } from "../shared/Button";
import { Spinner } from "../shared/Spinner";
import {
  getAdminStats,
  retryStuckSource,
  type SystemStats,
  type StuckSource,
} from "../../api/admin";
import { TraceViewer } from "./TraceViewer";

// ---------------------------------------------------------------------------
// Overview cards
// ---------------------------------------------------------------------------

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <Card className="flex flex-col items-center justify-center gap-1 px-4 py-5">
      <span className="text-2xl font-bold text-slate-900">{value}</span>
      <span className="text-xs font-medium text-slate-500">{label}</span>
    </Card>
  );
}

function PercentCard({ label, value }: { label: string; value: number }) {
  const pct = Math.round(value * 100);
  const color = pct >= 80 ? "text-emerald-600" : pct >= 50 ? "text-amber-600" : "text-rose-600";
  return (
    <Card className="flex flex-col items-center justify-center gap-1 px-4 py-5">
      <span className={`text-2xl font-bold ${color}`}>{pct}%</span>
      <span className="text-xs font-medium text-slate-500">{label}</span>
    </Card>
  );
}

function OverviewSection({ stats }: { stats: SystemStats }) {
  return (
    <section>
      <h2 className="mb-3 text-lg font-semibold text-slate-700">Overview</h2>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-8">
        <StatCard label="Users" value={stats.total_users} />
        <StatCard label="Articles" value={stats.article_count} />
        <StatCard label="Sources" value={stats.source_count} />
        <StatCard label="Concepts" value={stats.concept_count} />
        <StatCard label="Claims" value={stats.total_compiled_claims} />
        <StatCard label="Backlinks" value={stats.backlink_count} />
        <StatCard label="Orphans" value={stats.orphan_count} />
        <PercentCard label="Compile Rate" value={stats.compilation_success_rate} />
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Content breakdown
// ---------------------------------------------------------------------------

function BreakdownBar({
  data,
  colorFn,
}: {
  data: Record<string, number>;
  colorFn?: (key: string) => string;
}) {
  const total = Object.values(data).reduce((s, v) => s + v, 0);
  if (total === 0) {
    return (
      <div className="text-xs text-slate-400">No data yet</div>
    );
  }
  return (
    <div className="space-y-1.5">
      {Object.entries(data).map(([key, count]) => (
        <div key={key} className="flex items-center gap-2 text-xs">
          <span className="w-20 truncate font-medium text-slate-600">{key}</span>
          <div className="flex-1 overflow-hidden rounded bg-slate-100 h-3">
            <div
              className={`h-full rounded ${colorFn ? colorFn(key) : "bg-brand-500"}`}
              style={{ width: `${Math.max((count / total) * 100, 2)}%` }}
            />
          </div>
          <span className="w-8 text-right tabular-nums text-slate-500">{count}</span>
        </div>
      ))}
    </div>
  );
}

const STATUS_COLORS: Record<string, string> = {
  compiled: "bg-emerald-500",
  done: "bg-emerald-500",
  pending: "bg-sky-500",
  processing: "bg-amber-500",
  review_pending: "bg-violet-500",
  failed: "bg-rose-500",
};

function statusColor(key: string): string {
  return STATUS_COLORS[key] ?? "bg-slate-400";
}

const CONFIDENCE_COLORS: Record<string, string> = {
  sourced: "bg-emerald-500",
  inferred: "bg-sky-500",
  mixed: "bg-amber-500",
  unknown: "bg-slate-400",
};

function ContentBreakdownSection({ stats }: { stats: SystemStats }) {
  return (
    <section>
      <h2 className="mb-3 text-lg font-semibold text-slate-700">Content Breakdown</h2>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card className="p-4">
          <h3 className="mb-2 text-sm font-semibold text-slate-600">
            Articles by Page Type
          </h3>
          <BreakdownBar data={stats.articles_by_page_type} />
        </Card>
        <Card className="p-4">
          <h3 className="mb-2 text-sm font-semibold text-slate-600">
            Sources by Type
          </h3>
          <BreakdownBar data={stats.sources_by_type} />
        </Card>
        <Card className="p-4">
          <h3 className="mb-2 text-sm font-semibold text-slate-600">
            Sources by Status
          </h3>
          <BreakdownBar data={stats.sources_by_status} colorFn={statusColor} />
        </Card>
        <Card className="p-4">
          <h3 className="mb-2 text-sm font-semibold text-slate-600">
            Articles by Confidence
          </h3>
          <BreakdownBar
            data={stats.articles_by_confidence}
            colorFn={(k) => CONFIDENCE_COLORS[k] ?? "bg-slate-400"}
          />
        </Card>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Operational health
// ---------------------------------------------------------------------------

const STATUS_BADGE_TONE: Record<string, BadgeTone> = {
  compiled: "success",
  done: "success",
  pending: "info",
  processing: "warning",
  review_pending: "brand",
  failed: "danger",
};

function StuckSourceRow({ source }: { source: StuckSource }) {
  const queryClient = useQueryClient();
  const retry = useMutation({
    mutationFn: () => retryStuckSource(source.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-stats"] });
    },
  });

  return (
    <tr className="border-t border-slate-100">
      <td className="py-2 pr-3 text-sm text-slate-700">
        {source.title || source.id.slice(0, 8)}
      </td>
      <td className="py-2 pr-3">
        <Badge tone={STATUS_BADGE_TONE[source.source_type] ?? "neutral"}>
          {source.source_type}
        </Badge>
      </td>
      <td className="py-2 pr-3 text-sm tabular-nums text-slate-500">
        {source.minutes_stuck}m
      </td>
      <td className="py-2">
        <Button
          variant="secondary"
          size="sm"
          onClick={() => retry.mutate()}
          disabled={retry.isPending}
        >
          {retry.isPending ? "Retrying..." : "Retry"}
        </Button>
      </td>
    </tr>
  );
}

function OperationalHealthSection({ stats }: { stats: SystemStats }) {
  const stuck = stats.sources_stuck_processing;
  return (
    <section>
      <h2 className="mb-3 text-lg font-semibold text-slate-700">Operational Health</h2>
      <div className="grid gap-4 sm:grid-cols-2">
        <Card className="p-4">
          <h3 className="mb-3 text-sm font-semibold text-slate-600">
            Compilation Pipeline
          </h3>
          <div className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
            <span className="text-slate-500">Queue depth</span>
            <span className="font-medium text-slate-700">
              {stats.compilation_queue_depth}
            </span>
            <span className="text-slate-500">Last compilation</span>
            <span className="font-medium text-slate-700">
              {stats.last_compilation_at
                ? new Date(stats.last_compilation_at).toLocaleString()
                : "Never"}
            </span>
          </div>
        </Card>

        <Card className="p-4">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-600">
              Stuck Sources
            </h3>
            {stuck.length > 0 && (
              <Badge tone="danger">{stuck.length}</Badge>
            )}
          </div>
          {stuck.length === 0 ? (
            <p className="text-xs text-slate-400">
              No sources stuck in processing.
            </p>
          ) : (
            <table className="w-full text-left">
              <thead>
                <tr className="text-xs text-slate-400">
                  <th className="pb-1 pr-3 font-medium">Title</th>
                  <th className="pb-1 pr-3 font-medium">Type</th>
                  <th className="pb-1 pr-3 font-medium">Stuck</th>
                  <th className="pb-1 font-medium">Action</th>
                </tr>
              </thead>
              <tbody>
                {stuck.map((s) => (
                  <StuckSourceRow key={s.id} source={s} />
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Main dashboard
// ---------------------------------------------------------------------------

export function AdminDashboard() {
  const { data: stats, isLoading, isError } = useQuery({
    queryKey: ["admin-stats"],
    queryFn: getAdminStats,
    refetchInterval: 30_000,
  });

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner size={32} />
      </div>
    );
  }

  if (isError || !stats) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-slate-500">Failed to load admin statistics.</p>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="space-y-8 p-6">
        <h1 className="text-2xl font-bold text-slate-900">Admin Dashboard</h1>
        <OverviewSection stats={stats} />
        <ContentBreakdownSection stats={stats} />
        <OperationalHealthSection stats={stats} />
        <section>
          <h2 className="mb-3 text-lg font-semibold text-slate-700">LLM Traces</h2>
          <TraceViewer />
        </section>
      </div>
    </div>
  );
}
