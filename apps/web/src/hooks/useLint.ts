import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";
import {
  dismissFinding,
  getLatestReport,
  listReports,
  runLint,
  type LintFindingKind,
  type LintReport,
  type LintReportDetail,
} from "../api/lint";

export function useLatestReport(): UseQueryResult<LintReportDetail> {
  return useQuery({
    queryKey: ["lint", "latest"],
    queryFn: () => getLatestReport(),
    retry: false,
  });
}

export function useLintReports(limit = 20): UseQueryResult<LintReport[]> {
  return useQuery({
    queryKey: ["lint", "reports", limit],
    queryFn: () => listReports(limit),
  });
}

export function useRunLint(): UseMutationResult<
  { status: string },
  Error,
  void
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => runLint(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["lint"] });
    },
  });
}

export function useDismissFinding(): UseMutationResult<
  { dismissed: boolean; kind: string; finding_id: string },
  Error,
  { kind: LintFindingKind; id: string }
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ kind, id }) => dismissFinding(kind, id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["lint"] });
    },
  });
}
