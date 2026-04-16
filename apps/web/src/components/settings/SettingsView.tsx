import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Card } from "../shared/Card";
import { Button } from "../shared/Button";
import { Spinner } from "../shared/Spinner";
import { ProviderCard } from "./ProviderCard";
import { ApiKeyModal } from "./ApiKeyModal";
import { CostDashboard } from "./CostDashboard";
import { SyncStatus } from "./SyncStatus";
import { getSettings, updateSettings } from "../../api/settings";

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
    <div className="h-full overflow-y-auto p-6">
      <h1 className="mb-6 text-2xl font-bold text-slate-800">Settings</h1>

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

      <section className="mb-8">
        <h2 className="mb-4 text-lg font-semibold text-slate-700">Sync</h2>
        <SyncStatus sync={settings.sync} />
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

      {apiKeyModalProvider !== null && (
        <ApiKeyModal
          provider={apiKeyModalProvider}
          onClose={() => setApiKeyModalProvider(null)}
        />
      )}
    </div>
  );
}
