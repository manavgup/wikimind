import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";
import {
  ingestPdf,
  ingestUrl,
  listSources,
  retryCompile,
  type ListSourcesParams,
} from "../api/sources";
import type { Source } from "../types/api";

const SOURCES_KEY = ["sources"] as const;

// 5s polling acts as the WebSocket fallback per #17 acceptance criteria.
const POLL_INTERVAL_MS = 5000;

export function useSources(
  params: ListSourcesParams = {},
): UseQueryResult<Source[]> {
  return useQuery({
    queryKey: [...SOURCES_KEY, params],
    queryFn: () => listSources(params),
    refetchInterval: POLL_INTERVAL_MS,
    refetchOnWindowFocus: true,
  });
}

export function useIngestUrl() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (url: string) => ingestUrl(url),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: SOURCES_KEY });
    },
  });
}

export function useIngestPdf() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => ingestPdf(file),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: SOURCES_KEY });
    },
  });
}

export function useRetryCompile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sourceId: string) => retryCompile(sourceId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: SOURCES_KEY });
    },
  });
}
