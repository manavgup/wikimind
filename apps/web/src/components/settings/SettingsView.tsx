import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card } from "../shared/Card";
import { Spinner } from "../shared/Spinner";
import { ProviderCard } from "./ProviderCard";
import { ApiKeyModal } from "./ApiKeyModal";
import { CostDashboard } from "./CostDashboard";
import { SyncStatus } from "./SyncStatus";
import { getSettings } from "../../api/settings";

export function SettingsView() {
  const [apiKeyModalProvider, setApiKeyModalProvider] = useState<string | null>(null);

  const { data: settings, isLoading } = useQuery({
    queryKey: ["settings"],
    queryFn: getSettings,
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
            <span className="text-slate-700">{settings.llm.fallback_enabled ? "Enabled" : "Disabled"}</span>

            <span className="text-slate-500">Monthly budget</span>
            <span className="text-slate-700">${settings.llm.monthly_budget_usd.toFixed(2)}</span>
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
