import { apiFetch } from "./client";

export interface ProviderInfo {
  enabled: boolean;
  model: string;
  configured: boolean;
}

export interface SettingsResponse {
  data_dir: string;
  gateway_port: number;
  llm: {
    default_provider: string;
    fallback_enabled: boolean;
    monthly_budget_usd: number;
    providers: Record<string, ProviderInfo>;
  };
  sync: {
    enabled: boolean;
    interval_minutes: number;
    bucket: string | null;
  };
}

export interface CostEntry {
  cost_usd: number;
  call_count: number;
}

export interface CostBreakdown {
  month: string;
  total_usd: number;
  budget_usd: number;
  budget_pct: number;
  by_provider: Record<string, CostEntry>;
  by_task_type: Record<string, CostEntry>;
}

export interface TestResult {
  provider: string;
  status: "ok" | "error";
  latency_ms?: number;
  error?: string;
}

export function getSettings(): Promise<SettingsResponse> {
  return apiFetch<SettingsResponse>("/settings");
}

export function getCostBreakdown(): Promise<CostBreakdown> {
  return apiFetch<CostBreakdown>("/settings/llm/cost/breakdown");
}

export function setApiKey(provider: string, apiKey: string): Promise<void> {
  return apiFetch<void>("/settings/llm/api-key", {
    method: "POST",
    body: { provider, api_key: apiKey },
  });
}

export function testProvider(provider: string): Promise<TestResult> {
  return apiFetch<TestResult>("/settings/llm/test", {
    method: "POST",
    query: { provider },
  });
}

export function setDefaultProvider(provider: string): Promise<{ provider: string; status: string }> {
  return apiFetch("/settings/llm/default-provider", {
    method: "POST",
    body: { provider },
  });
}

export function updateSettings(updates: {
  monthly_budget_usd?: number;
  fallback_enabled?: boolean;
}): Promise<{ status: string }> {
  return apiFetch("/settings", {
    method: "PATCH",
    body: updates,
  });
}
