import type { Source, IngestURLRequest, ApiErrorBody } from "../types";
import { ApiError, withRetry } from "./retry";
import { getSettings } from "./storage";

async function getBaseUrl(): Promise<string> {
  const { gatewayUrl } = await getSettings();
  return gatewayUrl.replace(/\/$/, "");
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const base = await getBaseUrl();
  const response = await fetch(`${base}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      /* empty */
    }
    const parsed = body as ApiErrorBody | null;
    const message =
      parsed?.error?.message ??
      parsed?.detail ??
      `${response.status} ${response.statusText}`;
    throw new ApiError(response.status, message, body);
  }

  return (await response.json()) as T;
}

export function clipUrl(url: string, autoCompile = true): Promise<Source> {
  const body: IngestURLRequest = { url, auto_compile: autoCompile };
  return withRetry(() =>
    apiFetch<Source>("/ingest/url", {
      method: "POST",
      body: JSON.stringify(body),
    })
  );
}

export function getSource(sourceId: string): Promise<Source> {
  return apiFetch<Source>(
    `/ingest/sources/${encodeURIComponent(sourceId)}`
  );
}

export function listRecentSources(limit = 5): Promise<Source[]> {
  return apiFetch<Source[]>(`/ingest/sources?limit=${limit}`);
}
