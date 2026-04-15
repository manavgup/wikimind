// Endpoints in src/wikimind/api/routes/lint.py.

import { apiFetch } from "./client";

// --- Response types ---

export type LintSeverity = "info" | "warn" | "error";
export type LintReportStatus = "in_progress" | "complete" | "failed";

export interface LintReport {
  id: string;
  generated_at: string;
  completed_at: string | null;
  status: LintReportStatus;
  article_count: number;
  total_findings: number;
  contradictions_count: number;
  orphans_count: number;
  missing_pages_count: number;
  dismissed_count: number;
  total_pairs: number;
  checked_pairs: number;
  error_message: string | null;
  job_id: string | null;
}

interface LintFindingCommon {
  id: string;
  report_id: string;
  severity: LintSeverity;
  description: string;
  created_at: string;
  dismissed: boolean;
  dismissed_at: string | null;
  content_hash: string;
}

export interface LintContradictionFinding extends LintFindingCommon {
  kind: "contradiction";
  article_a_id: string;
  article_b_id: string;
  article_a_claim: string;
  article_b_claim: string;
  llm_confidence: "high" | "medium" | "low";
  shared_concept_id: string | null;
}

export interface LintOrphanFinding extends LintFindingCommon {
  kind: "orphan";
  article_id: string;
  article_title: string;
}

export interface LintStructuralFinding extends LintFindingCommon {
  kind: "structural";
  article_id: string;
  violation_type: string;
  auto_repaired: boolean;
  detail: string;
}

export type LintFindingKind = "contradiction" | "orphan" | "structural";

export type LintFinding =
  | LintContradictionFinding
  | LintOrphanFinding
  | LintStructuralFinding;

export interface LintReportDetail {
  report: LintReport;
  contradictions: LintContradictionFinding[];
  orphans: LintOrphanFinding[];
  structurals: LintStructuralFinding[];
  resolutions: Record<string, string>;
}

// --- API functions ---

export function runLint(): Promise<{ status: string }> {
  return apiFetch<{ status: string }>("/lint/run", { method: "POST" });
}

export function listReports(limit = 20): Promise<LintReport[]> {
  return apiFetch<LintReport[]>("/lint/reports", { query: { limit } });
}

export function getLatestReport(): Promise<LintReportDetail> {
  return apiFetch<LintReportDetail>("/lint/reports/latest");
}

export function getReport(
  id: string,
  includeDismissed = false,
): Promise<LintReportDetail> {
  return apiFetch<LintReportDetail>(`/lint/reports/${encodeURIComponent(id)}`, {
    query: { include_dismissed: includeDismissed },
  });
}

export function dismissFinding(
  kind: LintFindingKind,
  id: string,
): Promise<{ dismissed: boolean; kind: string; finding_id: string }> {
  return apiFetch(`/lint/findings/${kind}/${encodeURIComponent(id)}/dismiss`, {
    method: "POST",
  });
}

export async function recompileArticle(
  articleId: string,
  mode?: "source" | "concept",
): Promise<{ status: string; job_id: string }> {
  const params = mode ? `?mode=${mode}` : "";
  return apiFetch(`/wiki/articles/${articleId}/recompile${params}`, {
    method: "POST",
  });
}

export interface ResolutionOption {
  value: string;
  label: string;
}

export function getResolutionOptions(): Promise<ResolutionOption[]> {
  return apiFetch<ResolutionOption[]>("/wiki/contradiction-resolutions");
}

export async function resolveContradiction(
  sourceId: string,
  targetId: string,
  resolution: string,
  note?: string,
): Promise<{ resolved: boolean }> {
  return apiFetch(
    `/wiki/backlinks/${sourceId}/${targetId}/resolve`,
    {
      method: "POST",
      body: { resolution, resolution_note: note },
    },
  );
}
