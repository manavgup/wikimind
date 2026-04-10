import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ConversationDetail } from "../../api/query";
import { TurnCard } from "./TurnCard";
import { SaveThreadButton } from "./SaveThreadButton";

interface Props {
  detail: ConversationDetail | undefined;
  isLoading: boolean;
  pendingQuestion: string | null;
  streamingAnswer: string | null;
  onSave: () => void;
  isSaving: boolean;
  onExport: () => void;
  isExporting: boolean;
}

export function ConversationThread({
  detail,
  isLoading,
  pendingQuestion,
  streamingAnswer,
  onSave,
  isSaving,
  onExport,
  isExporting,
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
        <TurnCard key={q.id} query={q} />
      ))}
      {pendingQuestion && (
        <PendingTurnCard
          turnNumber={queries.length + 1}
          question={pendingQuestion}
          streamingAnswer={streamingAnswer}
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
 * When streamingAnswer is null, shows a "Thinking..." indicator.
 * When streamingAnswer has content, renders the partial markdown answer
 * progressively as tokens arrive from the SSE stream.
 */
function PendingTurnCard({
  turnNumber,
  question,
  streamingAnswer,
}: {
  turnNumber: number;
  question: string;
  streamingAnswer: string | null;
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
      {streamingAnswer ? (
        <div className="prose prose-sm max-w-none text-slate-700">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {streamingAnswer}
          </ReactMarkdown>
          <span
            className="ml-1 inline-block h-3 w-1.5 animate-pulse bg-blue-500"
            aria-label="Streaming"
          />
        </div>
      ) : (
        <div className="flex items-center gap-2 text-sm text-slate-500">
          <div
            className="h-2 w-2 animate-pulse rounded-full bg-blue-500"
            aria-hidden
          />
          <span>Thinking...</span>
        </div>
      )}
    </article>
  );
}
