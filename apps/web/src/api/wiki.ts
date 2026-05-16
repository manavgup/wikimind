// Endpoints in src/wikimind/api/routes/wiki.py.

import { apiFetch } from "./client";
import type {
  Article,
  ArticleResponse,
  Concept,
  ConfidenceLevel,
  CreateStubRequest,
  CreateStubResponse,
  FacetResponse,
  GraphResponse,
  SearchResponse,
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

export async function searchWiki(q: string, limit = 20): Promise<Article[]> {
  const resp = await apiFetch<SearchResponse>("/api/wiki/search", { query: { q, limit } });
  return (resp.results ?? []) as unknown as Article[];
}

export interface FacetedSearchParams {
  q: string;
  limit?: number;
  offset?: number;
  source_kind?: string;
  page_type?: string;
  concept?: string;
  tag?: string;
  date_range?: string;
  staleness?: string;
  sort?: string;
}

export function facetedSearch(
  params: FacetedSearchParams,
): Promise<SearchResponse> {
  return apiFetch<SearchResponse>("/api/wiki/search", {
    query: { ...params } as Record<string, string | number>,
  });
}

export function searchFacets(q: string): Promise<FacetResponse> {
  return apiFetch<FacetResponse>("/api/wiki/search/facets", { query: { q } });
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

// ---------------------------------------------------------------------------
// Synthesis pages
// ---------------------------------------------------------------------------

export interface CreateSynthesisRequest {
  query: string;
  article_ids?: string[];
}

export interface SynthesisResponse {
  id: string;
  slug: string;
  title: string;
  query: string;
  summary: string;
  themes: string[];
  source_count: number;
  source_article_ids: string[];
  created_at: string;
  page_type: "synthesis";
}

export function createSynthesis(
  body: CreateSynthesisRequest,
): Promise<SynthesisResponse> {
  return apiFetch<SynthesisResponse>("/api/wiki/synthesize", {
    method: "POST",
    body,
  });
}

export function listSynthesisPages(): Promise<Article[]> {
  return apiFetch<Article[]>("/api/wiki/synthesis");
}

export interface SynthesisSuggestion {
  article_ids: string[];
  article_titles: string[];
  reason: string;
  suggested_type: string;
}

export function getSynthesisSuggestions(): Promise<SynthesisSuggestion[]> {
  return apiFetch<SynthesisSuggestion[]>("/api/wiki/synthesis/suggestions");
}

// ---------------------------------------------------------------------------
// Synthesis wizard (preview → refine → confirm)
// ---------------------------------------------------------------------------

export type SynthesisType =
  | "comparative"
  | "chronological"
  | "thematic"
  | "gap_analysis";

export interface PreviewSynthesisRequest {
  synthesis_type: SynthesisType;
  article_ids: string[];
  guidance?: string;
}

export interface SynthesisPreviewResponse {
  preview_id: string;
  title: string;
  draft_markdown: string;
  themes: string[];
  source_count: number;
}

export interface RefineSynthesisRequest {
  preview_id: string;
  feedback: string;
}

export interface ConfirmSynthesisRequest {
  preview_id: string;
}

export function previewSynthesis(
  body: PreviewSynthesisRequest,
): Promise<SynthesisPreviewResponse> {
  return apiFetch<SynthesisPreviewResponse>("/api/wiki/synthesis/preview", {
    method: "POST",
    body,
  });
}

export function refineSynthesis(
  body: RefineSynthesisRequest,
): Promise<SynthesisPreviewResponse> {
  return apiFetch<SynthesisPreviewResponse>("/api/wiki/synthesis/refine", {
    method: "POST",
    body,
  });
}

export function confirmSynthesis(
  body: ConfirmSynthesisRequest,
): Promise<SynthesisResponse> {
  return apiFetch<SynthesisResponse>("/api/wiki/synthesis/confirm", {
    method: "POST",
    body,
  });
}
