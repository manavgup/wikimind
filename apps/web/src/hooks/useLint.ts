import { useEffect, useRef, useState } from "react";
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
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Clean up polling on unmount
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, []);

  const mutation = useMutation({
    mutationFn: () => runLint(),
    onSuccess: () => {
      // Capture the current report's timestamp so we can detect the NEW report
      const cached = queryClient.getQueryData<LintReportDetail>(["lint", "latest"]);
      const prevGeneratedAt = cached?.report?.generated_at ?? "";

      setIsPolling(true);
      pollRef.current = setInterval(async () => {
        try {
          const detail = await getLatestReport();
          queryClient.setQueryData(["lint", "latest"], detail);
          // Only stop when we see a NEWER report that's no longer in_progress
          const isNewer = detail.report.generated_at !== prevGeneratedAt;
          const isDone = detail.report.status !== "in_progress";
          if (isNewer && isDone) {
            if (pollRef.current) clearInterval(pollRef.current);
            if (timeoutRef.current) clearTimeout(timeoutRef.current);
            setIsPolling(false);
            queryClient.invalidateQueries({ queryKey: ["lint"] });
          }
        } catch {
          // Report not ready yet — keep polling
        }
      }, 2000);
      // Safety: stop polling after 5 minutes
      timeoutRef.current = setTimeout(() => {
        if (pollRef.current) clearInterval(pollRef.current);
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
