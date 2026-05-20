import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Card } from "../shared/Card";
import { Button } from "../shared/Button";
import { Spinner } from "../shared/Spinner";
import { getPlans, getUsage, createCheckout, getPortalUrl } from "../../api/billing";
import type { UsageInfo } from "../../api/billing";

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  const value = bytes / Math.pow(1024, i);
  return `${value.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

interface UsageBarProps {
  label: string;
  used: number;
  limit: number | null;
  formatValue?: (v: number) => string;
}

function UsageBar({ label, used, limit, formatValue }: UsageBarProps) {
  if (limit === null) {
    const displayUsed = formatValue ? formatValue(used) : used.toString();
    return (
      <div className="mb-4">
        <div className="mb-1 flex items-center justify-between text-sm">
          <span className="text-slate-700">{label}</span>
          <span className="text-slate-500">{displayUsed} (unlimited)</span>
        </div>
        <div className="h-2 w-full rounded-full bg-slate-100">
          <div className="h-2 rounded-full bg-emerald-500" style={{ width: "2%" }} />
        </div>
      </div>
    );
  }

  const pct = limit > 0 ? Math.min((used / limit) * 100, 100) : 0;
  const displayUsed = formatValue ? formatValue(used) : used.toString();
  const displayLimit = formatValue ? formatValue(limit) : limit.toString();
  const barColor = pct >= 90 ? "bg-rose-500" : pct >= 80 ? "bg-amber-500" : "bg-brand-600";

  return (
    <div className="mb-4">
      <div className="mb-1 flex items-center justify-between text-sm">
        <span className="text-slate-700">{label}</span>
        <span className="text-slate-500">
          {displayUsed} / {displayLimit} ({Math.round(pct)}%)
        </span>
      </div>
      <div className="h-2 w-full rounded-full bg-slate-100">
        <div
          className={`h-2 rounded-full transition-all ${barColor}`}
          style={{ width: `${Math.max(pct, 1)}%` }}
        />
      </div>
    </div>
  );
}

function UsageBars({ usage }: { usage: UsageInfo }) {
  return (
    <div>
      <UsageBar label="Sources" used={usage.sources} limit={usage.sources_limit} />
      <UsageBar label="Articles" used={usage.articles} limit={usage.articles_limit} />
      <UsageBar
        label="Queries today"
        used={usage.queries_today}
        limit={usage.queries_limit}
      />
      <UsageBar
        label="Storage"
        used={usage.storage_bytes}
        limit={usage.storage_limit}
        formatValue={formatBytes}
      />
      <UsageBar
        label="Active shares"
        used={usage.active_shares}
        limit={usage.shares_limit}
      />
    </div>
  );
}

export function BillingPage() {
  const [actionLoading, setActionLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const {
    data: usage,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["billing-usage"],
    queryFn: getUsage,
  });

  async function handleUpgrade() {
    setActionLoading(true);
    setActionError(null);
    try {
      const plans = await getPlans();
      const proPlan = plans.find((p) => p.name === "pro");
      if (!proPlan) throw new Error("Pro plan not found");
      const { checkout_url } = await createCheckout(proPlan.id);
      window.location.href = checkout_url;
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Failed to start checkout");
      setActionLoading(false);
    }
  }

  async function handleManageSubscription() {
    setActionLoading(true);
    setActionError(null);
    try {
      const { portal_url } = await getPortalUrl();
      window.location.href = portal_url;
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Failed to open billing portal");
      setActionLoading(false);
    }
  }

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner size={32} />
      </div>
    );
  }

  if (error || !usage) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-slate-500">Failed to load billing information.</p>
      </div>
    );
  }

  const isFree = usage.plan_name === "free";

  return (
    <div className="h-full overflow-y-auto">
      <div className="p-6">
        <h1 className="mb-6 text-2xl font-bold text-slate-900">Plan & Billing</h1>

        <section className="mb-8">
          <h2 className="mb-4 text-lg font-semibold text-slate-700">Current plan</h2>
          <Card className="p-5">
            <div className="flex items-center justify-between">
              <span className="text-xl font-bold text-slate-900">
                {usage.plan_display_name} plan
              </span>
              {isFree ? (
                <Button onClick={handleUpgrade} disabled={actionLoading}>
                  {actionLoading ? "Redirecting..." : "Upgrade to Pro"}
                </Button>
              ) : (
                <Button
                  variant="secondary"
                  onClick={handleManageSubscription}
                  disabled={actionLoading}
                >
                  {actionLoading ? "Redirecting..." : "Manage subscription"}
                </Button>
              )}
            </div>
            {actionError && (
              <p className="mt-3 text-sm text-rose-600">{actionError}</p>
            )}
            <div className="mt-3 text-center">
              <Link
                to="/pricing"
                className="text-sm text-brand-600 hover:text-brand-700 hover:underline"
              >
                Compare plans
              </Link>
            </div>
          </Card>
        </section>

        <section className="mb-8">
          <h2 className="mb-4 text-lg font-semibold text-slate-700">Usage</h2>
          <Card className="p-5">
            <UsageBars usage={usage} />
          </Card>
        </section>
      </div>
    </div>
  );
}
