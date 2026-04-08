import type { ConversationDetail } from "../../api/query";
import { TurnCard } from "./TurnCard";
import { SaveThreadButton } from "./SaveThreadButton";

interface Props {
  detail: ConversationDetail | undefined;
  isLoading: boolean;
  pendingQuestion: string | null;
  onSave: () => void;
  isSaving: boolean;
}

export function ConversationThread({
  detail,
  isLoading,
  pendingQuestion,
  onSave,
  isSaving,
}: Props) {
  // Empty state: no existing conversation AND nothing in flight
  if (!detail && !pendingQuestion) {
    return (
      <div className="text-slate-400">
        {isLoading ? "Loading…" : "Ask a question to start a new conversation."}
      </div>
    );
  }

  const queries = detail?.queries ?? [];
  const isFiledBack = !!detail?.conversation.filed_article_id;

  return (
    <div className="space-y-6">
      {queries.map((q) => (
        <TurnCard key={q.id} query={q} />
      ))}
      {pendingQuestion && (
        <PendingTurnCard
          turnNumber={queries.length + 1}
          question={pendingQuestion}
        />
      )}
      {queries.length > 0 && !pendingQuestion && (
        <div className="pt-4">
          <SaveThreadButton
            isFiledBack={isFiledBack}
            isSaving={isSaving}
            onClick={onSave}
          />
        </div>
      )}
    </div>
  );
}

/**
 * Visual placeholder shown while an ask mutation is in flight.
 * Renders the user's question immediately so they get feedback that
 * their submission landed, with a pulsing "Thinking…" affordance
 * where the real answer will appear.
 */
function PendingTurnCard({
  turnNumber,
  question,
}: {
  turnNumber: number;
  question: string;
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
        <span>Thinking…</span>
      </div>
    </article>
  );
}
