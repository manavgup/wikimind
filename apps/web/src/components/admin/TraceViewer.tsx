import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card } from "../shared/Card";
import { Badge } from "../shared/Badge";
import { Button } from "../shared/Button";
import { Spinner } from "../shared/Spinner";
import { getTraces, type LLMTrace } from "../../api/admin";

// ---------------------------------------------------------------------------
// Single trace row (expandable)
// ---------------------------------------------------------------------------

function TraceRow({ trace }: { trace: LLMTrace }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <>
      <tr
        className="cursor-pointer border-t border-slate-100 hover:bg-slate-50"
        onClick={() => setExpanded(!expanded)}
      >
        <td className="py-2 pr-3 text-xs text-slate-500">
          {new Date(trace.created_at).toLocaleString()}
        </td>
        <td className="py-2 pr-3">
          <Badge tone="neutral">{trace.operation}</Badge>
        </td>
        <td className="py-2 pr-3 text-sm text-slate-700">{trace.model}</td>
        <td className="py-2 pr-3 text-sm tabular-nums text-slate-600">
          {trace.total_tokens.toLocaleString()}
        </td>
        <td className="py-2 pr-3 text-sm tabular-nums text-slate-600">
          {trace.latency_ms.toLocaleString()}ms
        </td>
        <td className="py-2 text-xs text-slate-400">
          {expanded ? "\u25B2" : "\u25BC"}
        </td>
      </tr>
      {expanded && (
        <tr className="border-t border-slate-50 bg-slate-50">
          <td colSpan={6} className="px-4 py-3">
            <div className="grid gap-3 text-xs sm:grid-cols-2">
              <div>
                <span className="font-semibold text-slate-600">
                  Prompt tokens:
                </span>{" "}
                {trace.prompt_tokens.toLocaleString()}
              </div>
              <div>
                <span className="font-semibold text-slate-600">
                  Completion tokens:
                </span>{" "}
                {trace.completion_tokens.toLocaleString()}
              </div>
              {trace.source_id && (
                <div className="sm:col-span-2">
                  <span className="font-semibold text-slate-600">
                    Source ID:
                  </span>{" "}
                  <code className="text-xs text-slate-500">
                    {trace.source_id}
                  </code>
                </div>
              )}
              {trace.prompt_text && (
                <div className="sm:col-span-2">
                  <span className="mb-1 block font-semibold text-slate-600">
                    Prompt
                  </span>
                  <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded bg-white p-2 text-xs text-slate-700 border border-slate-200">
                    {trace.prompt_text}
                  </pre>
                </div>
              )}
              {trace.completion_text && (
                <div className="sm:col-span-2">
                  <span className="mb-1 block font-semibold text-slate-600">
                    Completion
                  </span>
                  <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded bg-white p-2 text-xs text-slate-700 border border-slate-200">
                    {trace.completion_text}
                  </pre>
                </div>
              )}
              {!trace.prompt_text && !trace.completion_text && (
                <div className="sm:col-span-2 text-slate-400 italic">
                  Content storage not enabled (set WIKIMIND_LLM__TRACE_STORE_CONTENT=true)
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Main trace viewer
// ---------------------------------------------------------------------------

const PAGE_SIZE = 50;

export function TraceViewer() {
  const [page, setPage] = useState(0);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["admin-traces", page],
    queryFn: () => getTraces(PAGE_SIZE, page * PAGE_SIZE),
    refetchInterval: 10_000,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Spinner size={24} />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <p className="py-4 text-sm text-slate-500">
        Failed to load traces. Ensure tracing is enabled
        (WIKIMIND_LLM__TRACE_ENABLED=true).
      </p>
    );
  }

  const totalPages = Math.ceil(data.total / PAGE_SIZE);

  if (data.total === 0) {
    return (
      <p className="py-4 text-sm text-slate-400">
        No traces recorded yet. Enable tracing with
        WIKIMIND_LLM__TRACE_ENABLED=true.
      </p>
    );
  }

  return (
    <Card className="overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-slate-200 text-xs font-medium text-slate-500">
              <th className="px-3 py-2">Time</th>
              <th className="px-3 py-2">Operation</th>
              <th className="px-3 py-2">Model</th>
              <th className="px-3 py-2">Tokens</th>
              <th className="px-3 py-2">Latency</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((trace) => (
              <TraceRow key={trace.id} trace={trace} />
            ))}
          </tbody>
        </table>
      </div>
      {totalPages > 1 && (
        <div className="flex items-center justify-between border-t border-slate-200 px-4 py-2">
          <span className="text-xs text-slate-500">
            {data.total} total traces
          </span>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
            >
              Prev
            </Button>
            <span className="flex items-center text-xs text-slate-500">
              {page + 1} / {totalPages}
            </span>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}
