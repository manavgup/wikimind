import { apiFetch } from "./client";

// ----- Types -----

export interface StuckSource {
  id: string;
  title: string | null;
  source_type: string;
  ingested_at: string;
  minutes_stuck: number;
}

export interface SystemStats {
  article_count: number;
  source_count: number;
  concept_count: number;
  backlink_count: number;
  orphan_count: number;
  conversation_count: number;
  articles_by_type: Record<string, number>;
  articles_by_page_type: Record<string, number>;
  articles_by_confidence: Record<string, number>;
  sources_by_type: Record<string, number>;
  sources_by_status: Record<string, number>;
  sources_stuck_processing: StuckSource[];
  compilation_queue_depth: number;
  avg_compilation_time_ms: number | null;
  last_compilation_at: string | null;
}

export interface AdminActionResult {
  action: string;
  status: string;
  job_id?: string | null;
}

// ----- Functions -----

export function getAdminStats(): Promise<SystemStats> {
  return apiFetch<SystemStats>("/api/admin/stats");
}

export function getStuckSources(): Promise<StuckSource[]> {
  return apiFetch<StuckSource[]>("/api/admin/stuck-sources");
}

export function retryStuckSource(sourceId: string): Promise<AdminActionResult> {
  return apiFetch<AdminActionResult>(
    `/api/admin/retry-stuck/${encodeURIComponent(sourceId)}`,
    { method: "POST" },
  );
}
