// Endpoints in src/wikimind/api/routes/wiki.py.

import { apiFetch } from "./client";
import type {
  Article,
  ArticleResponse,
  Concept,
  ConfidenceLevel,
  CreateStubRequest,
  CreateStubResponse,
  GraphResponse,
  WikilinkMatch,
} from "../types/api";

export interface ListArticlesParams {
  concept?: string;
  confidence?: ConfidenceLevel;
  page_type?: string;
  limit?: number;
  offset?: number;
}

export function listArticles(
  params: ListArticlesParams = {},
): Promise<Article[]> {
  return apiFetch<Article[]>("/api/wiki/articles", { query: { ...params } });
}

export function getArticle(slug: string): Promise<ArticleResponse> {
  return apiFetch<ArticleResponse>(`/api/wiki/articles/${encodeURIComponent(slug)}`);
}

export function listConcepts(): Promise<Concept[]> {
  return apiFetch<Concept[]>("/api/wiki/concepts");
}

export function searchWiki(q: string, limit = 20): Promise<Article[]> {
  return apiFetch<Article[]>("/api/wiki/search", { query: { q, limit } });
}

export function getRandomArticle(): Promise<Article> {
  return apiFetch<Article>("/api/wiki/articles/random");
}

export interface ArticleEditRequest {
  content?: string;
  title?: string;
}

export function editArticle(
  slug: string,
  body: ArticleEditRequest,
): Promise<ArticleResponse> {
  return apiFetch<ArticleResponse>(
    `/api/wiki/articles/${encodeURIComponent(slug)}`,
    { method: "PATCH", body },
  );
}

export function getGraph(): Promise<GraphResponse> {
  return apiFetch<GraphResponse>("/api/wiki/graph");
}

export function createStubArticle(
  body: CreateStubRequest,
): Promise<CreateStubResponse> {
  return apiFetch<CreateStubResponse>("/wiki/articles/stub", {
    method: "POST",
    body,
  });
}

export function resolveWikilinks(
  q: string,
  limit = 10,
): Promise<WikilinkMatch[]> {
  return apiFetch<WikilinkMatch[]>("/wiki/wikilinks/resolve", {
    query: { q, limit },
  });
}
