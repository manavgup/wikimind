import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Card } from "../shared/Card";
import { Button } from "../shared/Button";
import { Spinner } from "../shared/Spinner";
import { ProviderCard } from "./ProviderCard";
import { ApiKeyModal } from "./ApiKeyModal";
import { CostDashboard } from "./CostDashboard";
import { DoclingStatus } from "./DoclingStatus";
import { SyncStatus } from "./SyncStatus";
import { WikiExportPanel } from "./WikiExportPanel";
import { ShareLinksPanel } from "./ShareLinksPanel";
import { ApiTokens } from "./ApiTokens";
import { MCPTokens } from "./MCPTokens";
import { getSettings, updateSettings } from "../../api/settings";
import { getUsage } from "../../api/billing";
import type { UsageInfo } from "../../api/billing";

export function SettingsView() {
  const [apiKeyModalProvider, setApiKeyModalProvider] = useState<string | null>(null);
  const [editingBudget, setEditingBudget] = useState(false);
  const [budgetValue, setBudgetValue] = useState("");

  const queryClient = useQueryClient();

  const { data: settings, isLoading } = useQuery({
    queryKey: ["settings"],
    queryFn: getSettings,
  });

  const patchSettings = useMutation({
    mutationFn: updateSettings,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] });
      queryClient.invalidateQueries({ queryKey: ["cost-breakdown"] });
      setEditingBudget(false);
    },
  });

  const isHosted = settings?.deployment_mode === "hosted";
  const userPlanName = settings?.user_plan?.name ?? "free";
  const showLlmProviders = !isHosted;  // System providers only in self-hosted mode

  const { data: usage } = useQuery({
    queryKey: ["billing-usage"],
    queryFn: getUsage,
    enabled: isHosted,
  });

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner size={32} />
      </div>
    );
  }

  if (!settings) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-slate-500">Failed to load settings.</p>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="p-6">
        <h1 className="mb-6 text-2xl font-bold text-slate-900">Settings</h1>

        {isHosted && (
          <section className="mb-8">
            <h2 className="mb-4 text-lg font-semibold text-slate-700">Plan & Billing</h2>
            <Card className="p-4">
              <div className="flex items-center justify-between">
                <div className="text-sm text-slate-700">
                  Current plan:{" "}
                  <span className="font-semibold capitalize">{userPlanName}</span>
                </div>
                <Link
                  to="/settings/billing"
                  className="text-sm font-medium text-brand-600 hover:text-brand-700 hover:underline"
                >
                  Manage plan & usage
                </Link>
              </div>
            </Card>
          </section>
        )}

        {isHosted && usage && (
          <UsageQuotasSection usage={usage} />
        )}

        {showLlmProviders && (
          <>
            <section className="mb-8">
              <h2 className="mb-4 text-lg font-semibold text-slate-700">LLM Providers</h2>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {Object.entries(settings.llm.providers).map(([name, info]) => (
                  <ProviderCard
                    key={name}
                    name={name}
                    info={info}
                    isDefault={name === settings.llm.default_provider}
                    onSetKey={setApiKeyModalProvider}
                  />
                ))}
              </div>
            </section>

            <section className="mb-8">
              <h2 className="mb-4 text-lg font-semibold text-slate-700">Cost</h2>
              <CostDashboard warningThresholdPct={80} />
            </section>
          </>
        )}

        <section className="mb-8">
          <h2 className="mb-4 text-lg font-semibold text-slate-700">Sync</h2>
          <SyncStatus sync={settings.sync} />
        </section>

        <section className="mb-8">
          <h2 className="mb-4 text-lg font-semibold text-slate-700">Services</h2>
          <DoclingStatus />
        </section>

        <section className="mb-8">
          <h2 className="mb-4 text-lg font-semibold text-slate-700">Export</h2>
          <WikiExportPanel />
        </section>

        <section className="mb-8">
          <h2 className="mb-4 text-lg font-semibold text-slate-700">MCP API Tokens</h2>
          <MCPTokens />
        </section>

        <section className="mb-8">
          <h2 className="mb-4 text-lg font-semibold text-slate-700">Share Links</h2>
          <ShareLinksPanel />
        </section>

        <section className="mb-8">
          <h2 className="mb-4 text-lg font-semibold text-slate-700">API Tokens</h2>
          <ApiTokens />
        </section>

        <section className="mb-8">
          <h2 className="mb-4 text-lg font-semibold text-slate-700">System</h2>
          <Card className="p-4">
            <div className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
              <span className="text-slate-500">Data directory</span>
              <span className="font-mono text-slate-700">{settings.data_dir}</span>

              <span className="text-slate-500">Default provider</span>
              <span className="capitalize text-slate-700">{settings.llm.default_provider}</span>

              <span className="text-slate-500">Fallback</span>
              <button
                type="button"
                className={`inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                  settings.llm.fallback_enabled ? "bg-emerald-500" : "bg-slate-300"
                }`}
                onClick={() =>
                  patchSettings.mutate({ fallback_enabled: !settings.llm.fallback_enabled })
                }
                disabled={patchSettings.isPending}
              >
                <span
                  className={`inline-block h-4 w-4 rounded-full bg-white transition-transform ${
                    settings.llm.fallback_enabled ? "translate-x-6" : "translate-x-1"
                  }`}
                />
              </button>

              <span className="text-slate-500">Monthly budget</span>
              {editingBudget ? (
                <form
                  className="flex items-center gap-2"
                  onSubmit={(e) => {
                    e.preventDefault();
                    const val = parseFloat(budgetValue);
                    if (val > 0) patchSettings.mutate({ monthly_budget_usd: val });
                  }}
                >
                  <span className="text-slate-500">$</span>
                  <input
                    type="number"
                    step="0.01"
                    min="0.01"
                    value={budgetValue}
                    onChange={(e) => setBudgetValue(e.target.value)}
                    aria-label="Monthly budget in USD"
                    className="w-24 rounded border border-slate-300 px-2 py-0.5 text-sm text-slate-700 focus:border-brand-300 focus:outline-none"
                    autoFocus
                  />
                  <Button variant="ghost" size="sm" type="submit" disabled={patchSettings.isPending}>
                    Save
                  </Button>
                  <Button variant="ghost" size="sm" type="button" onClick={() => setEditingBudget(false)}>
                    Cancel
                  </Button>
                </form>
              ) : (
                <button
                  type="button"
                  className="text-left text-slate-700 hover:text-brand-600 hover:underline"
                  onClick={() => {
                    setBudgetValue(settings.llm.monthly_budget_usd.toFixed(2));
                    setEditingBudget(true);
                  }}
                >
                  ${settings.llm.monthly_budget_usd.toFixed(2)}
                </button>
              )}
            </div>
          </Card>
        </section>
      </div>

      {apiKeyModalProvider !== null && (
        <ApiKeyModal
          provider={apiKeyModalProvider}
          providerInfo={settings.llm.providers[apiKeyModalProvider]}
          onClose={() => setApiKeyModalProvider(null)}
        />
      )}
    </div>
  );
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  const value = bytes / Math.pow(1024, i);
  return `${value.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function UsageQuotasSection({ usage }: { usage: UsageInfo }) {
  const items: { label: string; used: number; limit: number | null; format?: (v: number) => string }[] = [
    { label: "Sources", used: usage.sources, limit: usage.sources_limit },
    { label: "Articles", used: usage.articles, limit: usage.articles_limit },
    { label: "Queries today", used: usage.queries_today, limit: usage.queries_limit },
    { label: "Storage", used: usage.storage_bytes, limit: usage.storage_limit, format: formatBytes },
    { label: "Active shares", used: usage.active_shares, limit: usage.shares_limit },
  ];

  return (
    <section className="mb-8">
      <h2 className="mb-4 text-lg font-semibold text-slate-700">Usage quotas</h2>
      <Card className="p-4">
        <div className="space-y-3">
          {items.map((item) => {
            const displayUsed = item.format ? item.format(item.used) : item.used.toString();
            if (item.limit === null) {
              return (
                <div key={item.label} className="flex items-center justify-between text-sm">
                  <span className="text-slate-700">{item.label}</span>
                  <span className="text-slate-500">{displayUsed} (unlimited)</span>
                </div>
              );
            }
            const pct = item.limit > 0 ? Math.min((item.used / item.limit) * 100, 100) : 0;
            const displayLimit = item.format ? item.format(item.limit) : item.limit.toString();
            const barColor = pct >= 90 ? "bg-rose-500" : pct >= 80 ? "bg-amber-500" : "bg-brand-600";
            return (
              <div key={item.label}>
                <div className="mb-1 flex items-center justify-between text-sm">
                  <span className="text-slate-700">{item.label}</span>
                  <span className="text-slate-500">
                    {displayUsed} / {displayLimit}
                  </span>
                </div>
                <div className="h-1.5 w-full rounded-full bg-slate-100">
                  <div
                    className={`h-1.5 rounded-full transition-all ${barColor}`}
                    style={{ width: `${Math.max(pct, 1)}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </Card>
    </section>
  );
}
