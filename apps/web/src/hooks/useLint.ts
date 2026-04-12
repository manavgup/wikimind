import { useState } from "react";
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
> & { isPolling: boolean } {
  const queryClient = useQueryClient();
  const [isPolling, setIsPolling] = useState(false);

  const mutation = useMutation({
    mutationFn: () => runLint(),
    onSuccess: () => {
      // Start polling for completion
      setIsPolling(true);
      const poll = setInterval(async () => {
        try {
          const report = await getLatestReport();
          queryClient.setQueryData(["lint", "latest"], report);
          if (report.report.status !== "in_progress") {
            clearInterval(poll);
            setIsPolling(false);
            queryClient.invalidateQueries({ queryKey: ["lint"] });
          }
        } catch {
          // Report not ready yet — keep polling
        }
      }, 2000);
      // Safety: stop polling after 5 minutes
      setTimeout(() => {
        clearInterval(poll);
        setIsPolling(false);
      }, 300_000);
    },
  });

  return { ...mutation, isPolling };
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
