import type { ConversationDetail } from "../../api/query";
import { TurnCard } from "./TurnCard";
import { SaveThreadButton } from "./SaveThreadButton";

interface Props {
  detail: ConversationDetail | undefined;
  isLoading: boolean;
  onSave: () => void;
  isSaving: boolean;
}

export function ConversationThread({ detail, isLoading, onSave, isSaving }: Props) {
  if (!detail) {
    return (
      <div className="text-slate-400">
        {isLoading ? "Loading…" : "Ask a question to start a new conversation."}
      </div>
    );
  }

  const { conversation, queries } = detail;
  const isFiledBack = !!conversation.filed_article_id;

  return (
    <div className="space-y-6">
      {queries.map((q) => (
        <TurnCard key={q.id} query={q} />
      ))}
      {isLoading && (
        <div className="text-sm text-slate-400">Thinking…</div>
      )}
      {queries.length > 0 && !isLoading && (
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
