import { apiFetch } from "./client";

export interface ProviderInfo {
  enabled: boolean;
  model: string;
  configured: boolean;
  base_url?: string | null;
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
  return apiFetch<SettingsResponse>("/api/settings");
}

export function getCostBreakdown(): Promise<CostBreakdown> {
  return apiFetch<CostBreakdown>("/api/settings/llm/cost/breakdown");
}

export function setApiKey(provider: string, apiKey: string): Promise<void> {
  return apiFetch<void>(`/api/settings/api-keys/${encodeURIComponent(provider)}`, {
    method: "PUT",
    body: { api_key: apiKey },
  });
}

export function testProvider(provider: string): Promise<TestResult> {
  return apiFetch<TestResult>("/api/settings/llm/test", {
    method: "POST",
    query: { provider },
  });
}

export function setDefaultProvider(provider: string): Promise<{ provider: string; status: string }> {
  return apiFetch("/api/settings/llm/default-provider", {
    method: "POST",
    body: { provider },
  });
}

export function updateSettings(updates: {
  monthly_budget_usd?: number;
  fallback_enabled?: boolean;
  openai_compatible_base_url?: string;
  openai_compatible_model?: string;
  openai_compatible_supports_json_response_format?: boolean;
  openai_compatible_supports_stream_usage?: boolean;
  openai_compatible_supports_reasoning_effort?: boolean;
  openai_compatible_max_tokens_field?: "max_tokens" | "max_completion_tokens";
  openai_compatible_reasoning_format?: "none" | "openai" | "openrouter";
}): Promise<{ status: string }> {
  return apiFetch("/api/settings", {
    method: "PATCH",
    body: updates,
  });
}

export interface OnboardingStatus {
  completed: boolean;
  step: number;
}

export function getOnboardingStatus(): Promise<OnboardingStatus> {
  return apiFetch<OnboardingStatus>("/api/settings/onboarding-status");
}

export function completeOnboarding(): Promise<OnboardingStatus> {
  return apiFetch<OnboardingStatus>("/api/settings/onboarding-status", {
    method: "POST",
  });
}
