// Endpoints in src/wikimind/api/routes/wiki.py.

import { apiFetch } from "./client";
import type {
  Article,
  ArticleResponse,
  Concept,
  ConfidenceLevel,
  GraphResponse,
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
  return apiFetch<Article[]>("/wiki/articles", { query: { ...params } });
}

export function getArticle(slug: string): Promise<ArticleResponse> {
  return apiFetch<ArticleResponse>(`/wiki/articles/${encodeURIComponent(slug)}`);
}

export function listConcepts(): Promise<Concept[]> {
  return apiFetch<Concept[]>("/wiki/concepts");
}

export function searchWiki(q: string, limit = 20): Promise<Article[]> {
  return apiFetch<Article[]>("/wiki/search", { query: { q, limit } });
}

export function getRandomArticle(): Promise<Article> {
  return apiFetch<Article>("/wiki/articles/random");
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
    `/wiki/articles/${encodeURIComponent(slug)}`,
    { method: "PATCH", body },
  );
}

export function getGraph(): Promise<GraphResponse> {
  return apiFetch<GraphResponse>("/wiki/graph");
}
