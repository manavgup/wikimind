import type { ConversationDetail } from "../../api/query";
import { TurnCard } from "./TurnCard";
import { SaveThreadButton } from "./SaveThreadButton";

interface Props {
  detail: ConversationDetail | undefined;
  isLoading: boolean;
  pendingQuestion: string | null;
  isStreaming: boolean;
  onSave: () => void;
  isSaving: boolean;
  onExport: () => void;
  isExporting: boolean;
  onFork?: (turnIndex: number, newQuestion: string) => void;
}

export function ConversationThread({
  detail,
  isLoading,
  pendingQuestion,
  isStreaming,
  onSave,
  isSaving,
  onExport,
  isExporting,
  onFork,
}: Props) {
  // Empty state: no existing conversation AND nothing in flight
  if (!detail && !pendingQuestion) {
    return (
      <div className="text-slate-400">
        {isLoading ? "Loading..." : "Ask a question to start a new conversation."}
      </div>
    );
  }

  const queries = detail?.queries ?? [];
  const isFiledBack = !!detail?.conversation.filed_article_id;

  return (
    <div className="space-y-6">
      {queries.map((q) => (
        <TurnCard
          key={q.id}
          query={q}
          onEdit={onFork}
          forkCount={detail?.conversation.fork_count}
        />
      ))}
      {pendingQuestion && (
        <PendingTurnCard
          turnNumber={queries.length + 1}
          question={pendingQuestion}
          isStreaming={isStreaming}
        />
      )}
      {queries.length > 0 && !pendingQuestion && (
        <div className="flex gap-2 pt-4">
          <SaveThreadButton
            isFiledBack={isFiledBack}
            isSaving={isSaving}
            onClick={onSave}
          />
          <button
            type="button"
            onClick={onExport}
            disabled={isExporting}
            className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            {isExporting ? "Exporting..." : "Export markdown"}
          </button>
        </div>
      )}
    </div>
  );
}

/**
 * Visual placeholder shown while an ask mutation is in flight.
 *
 * The QA agent returns structured JSON, so streaming raw tokens would
 * show garbage. Instead we show a "Thinking..." indicator until the
 * `done` SSE event arrives with the fully parsed answer.
 */
function PendingTurnCard({
  turnNumber,
  question,
  isStreaming,
}: {
  turnNumber: number;
  question: string;
  isStreaming: boolean;
}) {
  return (
    <article className="rounded-lg border border-slate-200 bg-slate-50 p-5 shadow-sm">
      <header className="mb-3">
        <div className="text-xs font-medium uppercase tracking-wide text-slate-400">
          Q{turnNumber}
        </div>
        <h3 className="mt-1 text-base font-semibold text-slate-900">
          {question}
        </h3>
      </header>
      <div className="flex items-center gap-2 text-sm text-slate-500">
        <div
          className="h-2 w-2 animate-pulse rounded-full bg-blue-500"
          aria-hidden
        />
        <span>{isStreaming ? "Generating answer..." : "Thinking..."}</span>
      </div>
    </article>
  );
}
