import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import {
  facetedSearch,
  type FacetedSearchParams,
  getGraph,
  listArticles,
  listConcepts,
  searchFacets,
  searchWiki,
} from "../api/wiki";
import type {
  Article,
  Concept,
  ConfidenceLevel,
  FacetResponse,
  GraphResponse,
  SearchResponse,
} from "../types/api";

export interface UseArticlesParams {
  concept?: string;
  confidence?: ConfidenceLevel;
  page_type?: string;
}

export function useArticles(
  params: UseArticlesParams = {},
): UseQueryResult<Article[]> {
  return useQuery({
    queryKey: ["articles", params],
    queryFn: () => listArticles(params),
  });
}

export function useConcepts(): UseQueryResult<Concept[]> {
  return useQuery({
    queryKey: ["concepts"],
    queryFn: () => listConcepts(),
  });
}

export function useSearch(query: string): UseQueryResult<Article[]> {
  return useQuery({
    queryKey: ["wiki-search", query],
    queryFn: () => searchWiki(query),
    enabled: query.trim().length >= 2,
    staleTime: 30_000,
  });
}

export function useGraph(): UseQueryResult<GraphResponse> {
  return useQuery({
    queryKey: ["wiki-graph"],
    queryFn: () => getGraph(),
    staleTime: 60_000,
  });
}

export function useFacetedSearch(
  params: FacetedSearchParams | null,
): UseQueryResult<SearchResponse> {
  return useQuery({
    queryKey: ["faceted-search", params],
    queryFn: () => facetedSearch(params!),
    enabled: params !== null && params.q.trim().length >= 2,
    staleTime: 30_000,
  });
}

export function useSearchFacets(query: string): UseQueryResult<FacetResponse> {
  return useQuery({
    queryKey: ["search-facets", query],
    queryFn: () => searchFacets(query),
    enabled: query.trim().length >= 2,
    staleTime: 30_000,
  });
}
