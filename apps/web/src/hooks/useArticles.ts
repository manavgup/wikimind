import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { listArticles, listConcepts, searchWiki } from "../api/wiki";
import type { Article, Concept, ConfidenceLevel } from "../types/api";

export interface UseArticlesParams {
  concept?: string;
  confidence?: ConfidenceLevel;
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
