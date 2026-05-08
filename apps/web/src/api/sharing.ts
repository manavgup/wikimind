// Endpoints for share links and wiki export.

import { apiFetch, getBaseUrl } from "./client";

export interface ShareLink {
  id: string;
  article_id: string;
  token: string;
  created_at: string;
  expires_at: string | null;
  revoked: boolean;
  view_count: number;
  last_viewed_at: string | null;
  article_title: string | null;
}

export interface CreateShareLinkRequest {
  article_id: string;
  expires_in_days?: number | null;
}

export function createShareLink(
  body: CreateShareLinkRequest,
): Promise<ShareLink> {
  return apiFetch<ShareLink>("/api/wiki/share-links", {
    method: "POST",
    body,
  });
}

export function revokeShareLink(linkId: string): Promise<void> {
  return apiFetch<void>(`/api/wiki/share-links/${linkId}`, {
    method: "DELETE",
  });
}

export function listShareLinks(articleId?: string): Promise<ShareLink[]> {
  return apiFetch<ShareLink[]>("/api/wiki/share-links", {
    query: articleId ? { article_id: articleId } : {},
  });
}

export function getPublicArticleUrl(token: string): string {
  const base = getBaseUrl() || window.location.origin;
  return `${base}/public/articles/${token}`;
}

export type WikiExportFormat = "obsidian" | "markdown_json";

export function exportWiki(format: WikiExportFormat = "obsidian"): void {
  const base = getBaseUrl() || window.location.origin;
  const url = `${base}/api/wiki/export/wiki?format=${format}`;

  // Use a form POST to trigger download with credentials
  const form = document.createElement("form");
  form.method = "POST";
  form.action = url;
  form.style.display = "none";
  document.body.appendChild(form);
  form.submit();
  document.body.removeChild(form);
}
