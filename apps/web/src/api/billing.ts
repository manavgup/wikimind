import { apiFetch } from "./client";

export interface PlanInfo {
  id: string;
  name: string;
  display_name: string;
  price_cents: number;
  billing_interval: string | null;
  max_sources: number | null;
  max_articles: number | null;
  max_queries_per_day: number | null;
  max_storage_bytes: number | null;
  max_active_shares: number | null;
  allowed_exports: string[];
  mcp_enabled: boolean;
  byok_allowed: boolean;
  sort_order: number;
}

export interface UsageInfo {
  plan_name: string;
  plan_display_name: string;
  sources: number;
  sources_limit: number | null;
  articles: number;
  articles_limit: number | null;
  storage_bytes: number;
  storage_limit: number | null;
  queries_today: number;
  queries_limit: number | null;
  active_shares: number;
  shares_limit: number | null;
  llm_spend_cents_today: number;
  llm_spend_limit: number | null;
}

export function getPlans(): Promise<PlanInfo[]> {
  return apiFetch<PlanInfo[]>("/api/billing/plans");
}

export function getUsage(): Promise<UsageInfo> {
  return apiFetch<UsageInfo>("/api/billing/usage");
}

export function createCheckout(planId: string): Promise<{ checkout_url: string }> {
  return apiFetch<{ checkout_url: string }>("/api/billing/checkout", {
    method: "POST",
    body: { plan_id: planId },
  });
}

export function getPortalUrl(): Promise<{ portal_url: string }> {
  return apiFetch<{ portal_url: string }>("/api/billing/portal");
}
