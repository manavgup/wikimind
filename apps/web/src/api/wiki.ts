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

export function getGraph(): Promise<GraphResponse> {
  return apiFetch<GraphResponse>("/wiki/graph");
}
