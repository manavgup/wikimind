import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";
import {
  approveDraft,
  deleteSource,
  getDraft,
  getSourceDetail,
  getSourceSpans,
  ingestPdf,
  ingestUrl,
  listSources,
  rejectDraft,
  retryCompile,
  type ListSourcesParams,
} from "../api/sources";
import type { Source, SourceDetailResponse, SourceSpanResponse } from "../types/api";

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

export function useDeleteSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sourceId: string) => deleteSource(sourceId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: SOURCES_KEY });
    },
  });
}

const SOURCE_DETAIL_KEY = ["source-detail"] as const;

export function useSourceDetail(
  sourceId: string | undefined,
): UseQueryResult<SourceDetailResponse> {
  return useQuery({
    queryKey: [...SOURCE_DETAIL_KEY, sourceId],
    queryFn: () => getSourceDetail(sourceId!),
    enabled: !!sourceId,
  });
}

const SOURCE_SPANS_KEY = ["source-spans"] as const;

export function useSourceSpans(
  sourceId: string | undefined,
): UseQueryResult<SourceSpanResponse[]> {
  return useQuery({
    queryKey: [...SOURCE_SPANS_KEY, sourceId],
    queryFn: () => getSourceSpans(sourceId!),
    enabled: !!sourceId,
  });
}

const DRAFT_KEY = ["draft"] as const;

export function useDraft(sourceId: string | null) {
  return useQuery({
    queryKey: [...DRAFT_KEY, sourceId],
    queryFn: () => getDraft(sourceId!),
    enabled: !!sourceId,
  });
}

export function useApproveDraft() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      sourceId,
      guidance,
    }: {
      sourceId: string;
      guidance?: string;
    }) => approveDraft(sourceId, guidance),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: SOURCES_KEY });
      qc.invalidateQueries({ queryKey: DRAFT_KEY });
    },
  });
}

export function useRejectDraft() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (sourceId: string) => rejectDraft(sourceId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: SOURCES_KEY });
      qc.invalidateQueries({ queryKey: DRAFT_KEY });
    },
  });
}
