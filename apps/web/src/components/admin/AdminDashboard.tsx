import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Card } from "../shared/Card";
import { Badge } from "../shared/Badge";
import type { BadgeTone } from "../shared/Badge";
import { Button } from "../shared/Button";
import { Spinner } from "../shared/Spinner";
import {
  getAdminStats,
  getAdminUsers,
  getAdminUserDetail,
  getAdminPlans,
  updatePlanModel,
  retryStuckSource,
  type SystemStats,
  type StuckSource,
  type AdminPlan,
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
// Users section
// ---------------------------------------------------------------------------

type SortField = "email" | "article_count" | "source_count" | "total_cost_usd";

function UserDetailPanel({ userId }: { userId: string }) {
  const { data: detail, isLoading } = useQuery({
    queryKey: ["admin-user-detail", userId],
    queryFn: () => getAdminUserDetail(userId),
  });

  if (isLoading) return <Spinner size={20} />;
  if (!detail) return null;

  return (
    <div className="mt-3 grid gap-4 sm:grid-cols-3">
      <Card className="p-3">
        <h4 className="mb-2 text-xs font-semibold text-slate-500">Articles by Type</h4>
        {Object.keys(detail.articles_by_type).length === 0 ? (
          <p className="text-xs text-slate-400">No articles</p>
        ) : (
          <ul className="space-y-1 text-xs text-slate-600">
            {Object.entries(detail.articles_by_type).map(([k, v]) => (
              <li key={k} className="flex justify-between">
                <span>{k}</span>
                <span className="font-medium tabular-nums">{v}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card className="p-3">
        <h4 className="mb-2 text-xs font-semibold text-slate-500">Sources by Status</h4>
        {Object.keys(detail.sources_by_status).length === 0 ? (
          <p className="text-xs text-slate-400">No sources</p>
        ) : (
          <ul className="space-y-1 text-xs text-slate-600">
            {Object.entries(detail.sources_by_status).map(([k, v]) => (
              <li key={k} className="flex justify-between">
                <span>{k}</span>
                <span className="font-medium tabular-nums">{v}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card className="p-3">
        <h4 className="mb-2 text-xs font-semibold text-slate-500">Cost by Provider</h4>
        {Object.keys(detail.cost_by_provider).length === 0 ? (
          <p className="text-xs text-slate-400">No cost data</p>
        ) : (
          <ul className="space-y-1 text-xs text-slate-600">
            {Object.entries(detail.cost_by_provider).map(([k, v]) => (
              <li key={k} className="flex justify-between">
                <span>{k}</span>
                <span className="font-medium tabular-nums">${v.toFixed(4)}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
      {detail.recent_sources.length > 0 && (
        <div className="sm:col-span-3">
          <Card className="p-3">
            <h4 className="mb-2 text-xs font-semibold text-slate-500">
              Recent Sources (last 10)
            </h4>
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="text-slate-400">
                  <th className="pb-1 pr-3 font-medium">Title</th>
                  <th className="pb-1 pr-3 font-medium">Type</th>
                  <th className="pb-1 pr-3 font-medium">Status</th>
                  <th className="pb-1 font-medium">Ingested</th>
                </tr>
              </thead>
              <tbody>
                {detail.recent_sources.map((s) => (
                  <tr key={s.id} className="border-t border-slate-100">
                    <td className="py-1.5 pr-3 text-slate-700">
                      {s.title || s.id.slice(0, 8)}
                    </td>
                    <td className="py-1.5 pr-3">
                      <Badge tone="neutral">{s.source_type}</Badge>
                    </td>
                    <td className="py-1.5 pr-3">
                      <Badge tone={STATUS_BADGE_TONE[s.status] ?? "neutral"}>
                        {s.status}
                      </Badge>
                    </td>
                    <td className="py-1.5 text-slate-500">
                      {new Date(s.ingested_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
      )}
    </div>
  );
}

function UsersSection() {
  const { data: users, isLoading } = useQuery({
    queryKey: ["admin-users"],
    queryFn: getAdminUsers,
    refetchInterval: 30_000,
  });

  const [expandedUserId, setExpandedUserId] = useState<string | null>(null);
  const [sortField, setSortField] = useState<SortField>("email");
  const [sortAsc, setSortAsc] = useState(true);

  if (isLoading) return <Spinner size={24} />;
  if (!users || users.length === 0) {
    return (
      <p className="text-xs text-slate-400">No users found.</p>
    );
  }

  const sorted = [...users].sort((a, b) => {
    const av = a[sortField];
    const bv = b[sortField];
    if (typeof av === "string" && typeof bv === "string") {
      return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
    }
    return sortAsc
      ? (av as number) - (bv as number)
      : (bv as number) - (av as number);
  });

  function handleSort(field: SortField) {
    if (sortField === field) {
      setSortAsc(!sortAsc);
    } else {
      setSortField(field);
      setSortAsc(true);
    }
  }

  const arrow = (field: SortField) =>
    sortField === field ? (sortAsc ? " \u2191" : " \u2193") : "";

  return (
    <section>
      <h2 className="mb-3 text-lg font-semibold text-slate-700">Users</h2>
      <Card className="overflow-x-auto p-4">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="text-xs text-slate-400">
              <th
                className="cursor-pointer pb-2 pr-3 font-medium"
                onClick={() => handleSort("email")}
              >
                Email{arrow("email")}
              </th>
              <th className="pb-2 pr-3 font-medium">Name</th>
              <th
                className="cursor-pointer pb-2 pr-3 font-medium text-right"
                onClick={() => handleSort("article_count")}
              >
                Articles{arrow("article_count")}
              </th>
              <th
                className="cursor-pointer pb-2 pr-3 font-medium text-right"
                onClick={() => handleSort("source_count")}
              >
                Sources{arrow("source_count")}
              </th>
              <th
                className="cursor-pointer pb-2 pr-3 font-medium text-right"
                onClick={() => handleSort("total_cost_usd")}
              >
                Cost (USD){arrow("total_cost_usd")}
              </th>
              <th className="pb-2 font-medium">Last Active</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((user) => (
              <tr key={user.id}>
                <td colSpan={6} className="p-0">
                  <div
                    className="flex cursor-pointer items-center border-t border-slate-100 hover:bg-slate-50"
                    onClick={() =>
                      setExpandedUserId(
                        expandedUserId === user.id ? null : user.id,
                      )
                    }
                  >
                    <span className="flex-1 py-2 pr-3 text-sm text-slate-700">
                      {user.email}
                    </span>
                    <span className="w-32 py-2 pr-3 text-sm text-slate-600 truncate">
                      {user.name || "\u2014"}
                    </span>
                    <span className="w-20 py-2 pr-3 text-right text-sm tabular-nums text-slate-700">
                      {user.article_count}
                    </span>
                    <span className="w-20 py-2 pr-3 text-right text-sm tabular-nums text-slate-700">
                      {user.source_count}
                    </span>
                    <span className="w-24 py-2 pr-3 text-right text-sm tabular-nums text-slate-700">
                      ${user.total_cost_usd.toFixed(4)}
                    </span>
                    <span className="w-40 py-2 text-sm text-slate-500">
                      {user.last_active_at
                        ? new Date(user.last_active_at).toLocaleString()
                        : "Never"}
                    </span>
                  </div>
                  {expandedUserId === user.id && (
                    <div className="px-3 pb-3">
                      <UserDetailPanel userId={user.id} />
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Plans section
// ---------------------------------------------------------------------------

function PlanRow({ plan }: { plan: AdminPlan }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [model, setModel] = useState(plan.llm_model);
  const [provider, setProvider] = useState(plan.llm_provider);

  const save = useMutation({
    mutationFn: () =>
      updatePlanModel(plan.id, { llm_model: model, llm_provider: provider }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-plans"] });
      setEditing(false);
    },
  });

  const handleCancel = () => {
    setModel(plan.llm_model);
    setProvider(plan.llm_provider);
    setEditing(false);
  };

  return (
    <tr className="border-t border-slate-100">
      <td className="py-2 pr-3 text-sm font-medium text-slate-700">
        {plan.display_name}
      </td>
      <td className="py-2 pr-3 text-sm text-slate-500">{plan.name}</td>
      <td className="py-2 pr-3">
        {editing ? (
          <input
            type="text"
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
          />
        ) : (
          <span className="text-sm text-slate-700">{plan.llm_provider}</span>
        )}
      </td>
      <td className="py-2 pr-3">
        {editing ? (
          <input
            type="text"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
          />
        ) : (
          <span className="text-sm text-slate-700">{plan.llm_model}</span>
        )}
      </td>
      <td className="py-2 pr-3">
        <Badge tone={plan.is_active ? "success" : "neutral"}>
          {plan.is_active ? "Active" : "Inactive"}
        </Badge>
      </td>
      <td className="py-2">
        {editing ? (
          <div className="flex gap-2">
            <Button
              variant="primary"
              size="sm"
              onClick={() => save.mutate()}
              disabled={
                save.isPending ||
                (model === plan.llm_model && provider === plan.llm_provider)
              }
            >
              {save.isPending ? "Saving..." : "Save"}
            </Button>
            <Button variant="secondary" size="sm" onClick={handleCancel}>
              Cancel
            </Button>
          </div>
        ) : (
          <Button variant="secondary" size="sm" onClick={() => setEditing(true)}>
            Edit
          </Button>
        )}
      </td>
    </tr>
  );
}

function PlansSection() {
  const { data: plans, isLoading } = useQuery({
    queryKey: ["admin-plans"],
    queryFn: getAdminPlans,
    refetchInterval: 30_000,
  });

  if (isLoading) return <Spinner size={24} />;
  if (!plans || plans.length === 0) {
    return <p className="text-xs text-slate-400">No plans configured.</p>;
  }

  return (
    <section>
      <h2 className="mb-3 text-lg font-semibold text-slate-700">Plans</h2>
      <Card className="overflow-x-auto p-4">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="text-xs text-slate-400">
              <th className="pb-2 pr-3 font-medium">Display Name</th>
              <th className="pb-2 pr-3 font-medium">Slug</th>
              <th className="pb-2 pr-3 font-medium">LLM Provider</th>
              <th className="pb-2 pr-3 font-medium">LLM Model</th>
              <th className="pb-2 pr-3 font-medium">Status</th>
              <th className="pb-2 font-medium">Action</th>
            </tr>
          </thead>
          <tbody>
            {plans.map((plan) => (
              <PlanRow key={plan.id} plan={plan} />
            ))}
          </tbody>
        </table>
      </Card>
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
        <PlansSection />
        <UsersSection />
        <section>
          <h2 className="mb-3 text-lg font-semibold text-slate-700">LLM Traces</h2>
          <TraceViewer />
        </section>
      </div>
    </div>
  );
}
