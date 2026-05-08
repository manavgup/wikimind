import { useState } from "react";
import type { CompilationDraft } from "../../types/api";
import { useApproveDraft, useRejectDraft } from "../../hooks/useSources";
import { ApiError } from "../../api/client";
import { Spinner } from "../shared/Spinner";

interface DraftReviewPanelProps {
  draft: CompilationDraft;
  onDone: () => void;
}

export function DraftReviewPanel({ draft, onDone }: DraftReviewPanelProps) {
  const [guidance, setGuidance] = useState("");
  const [showBody, setShowBody] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const approveMutation = useApproveDraft();
  const rejectMutation = useRejectDraft();

  const handleApprove = async () => {
    setError(null);
    try {
      await approveMutation.mutateAsync({
        sourceId: draft.source_id,
        guidance: guidance.trim() || undefined,
      });
      onDone();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Failed to approve draft",
      );
    }
  };

  const handleReject = async () => {
    setError(null);
    try {
      await rejectMutation.mutateAsync(draft.source_id);
      onDone();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Failed to reject draft",
      );
    }
  };

  const isPending = approveMutation.isPending || rejectMutation.isPending;

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-5">
      <div className="mb-4 flex items-start justify-between">
        <div>
          <h3 className="text-lg font-semibold text-slate-900">
            Review: {draft.title}
          </h3>
          <p className="mt-1 text-sm text-slate-600">{draft.summary}</p>
        </div>
        <span className="rounded-full bg-amber-200 px-2.5 py-0.5 text-xs font-medium text-amber-800">
          Awaiting review
        </span>
      </div>

      <div className="mb-4">
        <h4 className="mb-2 text-sm font-medium text-slate-700">
          Key takeaways from this source:
        </h4>
        <ul className="space-y-1.5">
          {draft.key_takeaways.map((takeaway, i) => (
            <li
              key={i}
              className="flex items-start gap-2 text-sm text-slate-700"
            >
              <span className="mt-0.5 flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full bg-amber-200 text-xs font-medium text-amber-800">
                {i + 1}
              </span>
              {takeaway}
            </li>
          ))}
        </ul>
      </div>

      <button
        type="button"
        onClick={() => setShowBody(!showBody)}
        className="mb-4 text-sm font-medium text-indigo-600 hover:text-indigo-800"
      >
        {showBody ? "Hide draft article" : "Show draft article"}
      </button>

      {showBody && (
        <div className="mb-4 max-h-64 overflow-y-auto rounded border border-slate-200 bg-white p-4">
          <pre className="whitespace-pre-wrap text-sm text-slate-700">
            {draft.draft_body}
          </pre>
        </div>
      )}

      <div className="mb-4">
        <label
          htmlFor="guidance"
          className="mb-1 block text-sm font-medium text-slate-700"
        >
          Guidance (optional) -- tell the LLM what to focus on:
        </label>
        <textarea
          id="guidance"
          value={guidance}
          onChange={(e) => setGuidance(e.target.value)}
          placeholder="e.g. Focus on the practical implications for distributed systems. Skip the historical background."
          className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-700 placeholder-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          rows={3}
          disabled={isPending}
        />
      </div>

      {error && (
        <div className="mb-3 rounded-md border border-rose-200 bg-rose-50 p-2 text-sm text-rose-800">
          {error}
        </div>
      )}

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleApprove}
          disabled={isPending}
          className="inline-flex items-center gap-1.5 rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
        >
          {approveMutation.isPending && <Spinner size={14} />}
          {guidance.trim()
            ? "Approve with guidance"
            : "Approve as-is"}
        </button>
        <button
          type="button"
          onClick={handleReject}
          disabled={isPending}
          className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
        >
          {rejectMutation.isPending && <Spinner size={14} />}
          Skip / Reject
        </button>
      </div>
    </div>
  );
}
