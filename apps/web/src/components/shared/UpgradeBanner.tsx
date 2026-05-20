import { useState } from "react";
import { Link } from "react-router-dom";
import type { UsageInfo } from "../../api/billing";

interface UpgradeBannerProps {
  usage: UsageInfo;
  deploymentMode: string;
}

function isApproachingLimit(used: number, limit: number | null): boolean {
  if (limit === null || limit === 0) return false;
  return used / limit >= 0.8;
}

export function UpgradeBanner({ usage, deploymentMode }: UpgradeBannerProps) {
  const [dismissed, setDismissed] = useState(false);

  if (dismissed) return null;
  if (deploymentMode !== "hosted") return null;
  if (usage.plan_name !== "free") return null;

  const approaching =
    isApproachingLimit(usage.sources, usage.sources_limit) ||
    isApproachingLimit(usage.articles, usage.articles_limit) ||
    isApproachingLimit(usage.queries_today, usage.queries_limit) ||
    isApproachingLimit(usage.storage_bytes, usage.storage_limit) ||
    isApproachingLimit(usage.active_shares, usage.shares_limit);

  if (!approaching) return null;

  return (
    <div className="flex items-center justify-between gap-4 border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-900">
      <p>
        You&apos;re approaching your plan limits.{" "}
        <Link
          to="/settings/billing"
          className="font-medium text-brand-700 underline underline-offset-2 hover:text-brand-800"
        >
          Upgrade to Pro
        </Link>{" "}
        for more.
      </p>
      <button
        type="button"
        onClick={() => setDismissed(true)}
        className="shrink-0 text-xs text-amber-600 hover:text-amber-800"
        aria-label="Dismiss"
      >
        Dismiss
      </button>
    </div>
  );
}
