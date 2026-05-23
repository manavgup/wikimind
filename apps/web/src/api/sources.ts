// Endpoints in src/wikimind/api/routes/ingest.py and jobs.py.

import { apiFetch, getBaseUrl } from "./client";
import type {
  ApproveDraftResponse,
  CompilationDraft,
  IngestStatus,
  RejectDraftResponse,
  Source,
  SourceContentResponse,
  SourceDetailResponse,
  SourceSpanResponse,
  TriggerCompileResponse,
} from "../types/api";

export interface ListSourcesParams {
  status?: IngestStatus;
  limit?: number;
  offset?: number;
}

export function listSources(params: ListSourcesParams = {}): Promise<Source[]> {
  return apiFetch<Source[]>("/api/ingest/sources", { query: { ...params } });
}

export function getSource(sourceId: string): Promise<Source> {
  return apiFetch<Source>(`/api/ingest/sources/${encodeURIComponent(sourceId)}`);
}

export function getSourceDetail(sourceId: string): Promise<SourceDetailResponse> {
  return apiFetch<SourceDetailResponse>(
    `/api/ingest/sources/${encodeURIComponent(sourceId)}/detail`,
  );
}

export function ingestUrl(url: string, autoCompile = true): Promise<Source> {
  return apiFetch<Source>("/api/ingest/url", {
    method: "POST",
    body: { url, auto_compile: autoCompile },
  });
}

export function ingestPdf(file: File): Promise<Source> {
  const form = new FormData();
  form.append("file", file);
  return apiFetch<Source>("/api/ingest/pdf", { method: "POST", body: form });
}

export function deleteSource(sourceId: string): Promise<{ deleted: string }> {
  return apiFetch(`/api/ingest/sources/${encodeURIComponent(sourceId)}`, {
    method: "DELETE",
  });
}

export function retryCompile(sourceId: string): Promise<TriggerCompileResponse> {
  return apiFetch<TriggerCompileResponse>(
    `/api/jobs/compile/${encodeURIComponent(sourceId)}`,
    { method: "POST" },
  );
}

export function getSourceContent(sourceId: string): Promise<SourceContentResponse> {
  return apiFetch<SourceContentResponse>(
    `/ingest/sources/${encodeURIComponent(sourceId)}/content`,
  );
}

export function getOriginalUrl(sourceId: string): string {
  return `${getBaseUrl()}/api/ingest/sources/${encodeURIComponent(sourceId)}/original`;
}

export function getDraft(sourceId: string): Promise<CompilationDraft> {
  return apiFetch<CompilationDraft>(
    `/api/ingest/sources/${encodeURIComponent(sourceId)}/draft`,
  );
}

export function approveDraft(
  sourceId: string,
  guidance?: string,
): Promise<ApproveDraftResponse> {
  return apiFetch<ApproveDraftResponse>(
    `/api/ingest/sources/${encodeURIComponent(sourceId)}/draft/approve`,
    {
      method: "POST",
      body: guidance ? { guidance } : {},
    },
  );
}

export function rejectDraft(sourceId: string): Promise<RejectDraftResponse> {
  return apiFetch<RejectDraftResponse>(
    `/api/ingest/sources/${encodeURIComponent(sourceId)}/draft/reject`,
    { method: "POST" },
  );
}

export function getSourceSpans(sourceId: string): Promise<SourceSpanResponse[]> {
  return apiFetch<SourceSpanResponse[]>(
    `/api/ingest/sources/${encodeURIComponent(sourceId)}/spans`,
  );
}
