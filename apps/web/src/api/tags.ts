// Endpoints for tags and saved searches (issue #454).

import { apiFetch } from "./client";

export interface TagResponse {
  id: string;
  name: string;
  color: string;
  created_at: string;
}

export interface SavedSearchResponse {
  id: string;
  name: string;
  query: string;
  filters_json: string;
  created_at: string;
}

export interface SavedSearchExecuteResponse {
  saved_search: SavedSearchResponse;
  articles: unknown[];
}

// --- Tag CRUD ---

export function createTag(
  name: string,
  color: string = "#6366f1",
): Promise<TagResponse> {
  return apiFetch<TagResponse>("/tags", {
    method: "POST",
    body: { name, color },
  });
}

export function listTags(): Promise<TagResponse[]> {
  return apiFetch<TagResponse[]>("/tags");
}

export function deleteTag(tagId: string): Promise<void> {
  return apiFetch<void>(`/tags/${tagId}`, { method: "DELETE" });
}

// --- Article tagging ---

export function tagArticle(
  articleId: string,
  tagId: string,
): Promise<{ article_id: string; tag_id: string }> {
  return apiFetch(`/wiki/articles/${articleId}/tags`, {
    method: "POST",
    body: { tag_id: tagId },
  });
}

export function untagArticle(
  articleId: string,
  tagId: string,
): Promise<void> {
  return apiFetch<void>(`/wiki/articles/${articleId}/tags/${tagId}`, {
    method: "DELETE",
  });
}

export function getArticleTags(articleId: string): Promise<TagResponse[]> {
  return apiFetch<TagResponse[]>(`/wiki/articles/${articleId}/tags`);
}

export function getArticlesByTag(tagId: string): Promise<unknown[]> {
  return apiFetch<unknown[]>(`/tags/${tagId}/articles`);
}

// --- Saved searches ---

export function createSavedSearch(
  name: string,
  query: string = "",
  filtersJson: string = "{}",
): Promise<SavedSearchResponse> {
  return apiFetch<SavedSearchResponse>("/saved-searches", {
    method: "POST",
    body: { name, query, filters_json: filtersJson },
  });
}

export function listSavedSearches(): Promise<SavedSearchResponse[]> {
  return apiFetch<SavedSearchResponse[]>("/saved-searches");
}

export function deleteSavedSearch(id: string): Promise<void> {
  return apiFetch<void>(`/saved-searches/${id}`, { method: "DELETE" });
}

export function executeSavedSearch(
  id: string,
): Promise<SavedSearchExecuteResponse> {
  return apiFetch<SavedSearchExecuteResponse>(
    `/saved-searches/${id}/execute`,
    { method: "POST" },
  );
}
