// Endpoints in src/wikimind/api/routes/ingest.py and jobs.py.

import { apiFetch, getBaseUrl } from "./client";
import type { IngestStatus, Source, SourceContentResponse, TriggerCompileResponse } from "../types/api";

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
