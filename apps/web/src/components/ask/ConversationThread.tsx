import { useEffect, useRef, useState } from "react";
import type { ConversationDetail } from "../../api/query";
import { useSelection } from "../../store/selection";
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
  onSaveSelection: () => void;
  isSavingSelection: boolean;
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
  onSaveSelection,
  isSavingSelection,
}: Props) {
  const pendingRef = useRef<HTMLDivElement>(null);
  const [selectionMode, setSelectionMode] = useState(false);
  const selection = useSelection();
  const conversationId = detail?.conversation.id;

  useEffect(() => {
    if (pendingQuestion && pendingRef.current) {
      pendingRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [pendingQuestion]);

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

  const handleToggleSelectionMode = () => {
    if (selectionMode) {
      // Exiting selection mode — clear selections for this conversation
      if (conversationId) {
        for (const q of queries) {
          if (selection.isSelected(conversationId, q.turn_index)) {
            selection.removeTurn(conversationId, q.turn_index);
          }
        }
      }
    }
    setSelectionMode((v) => !v);
  };

  return (
    <div className="space-y-6">
      {queries.map((q) => (
        <TurnCard
          key={q.id}
          query={q}
          onEdit={onFork}
          forkCount={detail?.conversation.fork_count}
          selectionMode={selectionMode}
          isSelected={
            selectionMode && conversationId
              ? selection.isSelected(conversationId, q.turn_index)
              : undefined
          }
          onToggleSelect={
            selectionMode && conversationId
              ? () => selection.toggleTurn(conversationId, q.turn_index)
              : undefined
          }
        />
      ))}
      {pendingQuestion && (
        <div ref={pendingRef}>
          <PendingTurnCard
            turnNumber={queries.length + 1}
            question={pendingQuestion}
            isStreaming={isStreaming}
          />
        </div>
      )}
      {queries.length > 0 && !pendingQuestion && (
        <div className="flex flex-wrap gap-2 pt-4">
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
          <button
            type="button"
            onClick={handleToggleSelectionMode}
            className={`rounded-lg border px-4 py-2 text-sm font-medium ${
              selectionMode
                ? "border-blue-400 bg-blue-50 text-blue-700"
                : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
            }`}
          >
            {selectionMode ? "Cancel selection" : "Select turns"}
          </button>
          {selectionMode && selection.count > 0 && (
            <button
              type="button"
              onClick={onSaveSelection}
              disabled={isSavingSelection}
              className="rounded-lg border border-blue-500 bg-blue-500 px-4 py-2 text-sm font-medium text-white hover:bg-blue-600 disabled:opacity-50"
            >
              {isSavingSelection
                ? "Saving..."
                : `Save ${selection.count} turn${selection.count !== 1 ? "s" : ""} to wiki`}
            </button>
          )}
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
