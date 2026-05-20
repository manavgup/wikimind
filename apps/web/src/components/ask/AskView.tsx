import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  getConversation,
  listConversations,
} from "../../api/query";
import { SelectionProvider } from "../../store/selection";
import { ConversationHistory } from "./ConversationHistory";
import { ConversationThread } from "./ConversationThread";
import { QueryInput } from "./QueryInput";
import { useAskStream } from "./useAskStream";
import { useFileBack } from "./useFileBack";
import { useExportConversation } from "./useExportConversation";

export function AskView() {
  return (
    <SelectionProvider>
      <AskViewInner />
    </SelectionProvider>
  );
}

function AskViewInner() {
  const { conversationId } = useParams<{ conversationId?: string }>();

  // Load the current conversation's full thread (only if we have an id)
  const conversationDetail = useQuery({
    queryKey: ["conversation", conversationId],
    queryFn: () => getConversation(conversationId!),
    enabled: !!conversationId,
  });

  // Sidebar
  const conversations = useQuery({
    queryKey: ["conversations"],
    queryFn: () => listConversations(50),
  });

  const {
    pendingQuestion,
    pendingError,
    isStreaming,
    isBusy,
    handleSubmit,
    handleFork,
  } = useAskStream({ conversationId });

  const { handleSave, isSaving, handleSaveSelection, isSavingSelection } =
    useFileBack({ conversationId });

  const { handleExport, isExporting } = useExportConversation({
    conversationId,
    conversationTitle: conversationDetail.data?.conversation.title,
  });

  return (
    <div className="flex h-full">
      <aside className="w-64 border-r border-slate-200 overflow-y-auto">
        <ConversationHistory
          conversations={conversations.data ?? []}
          activeId={conversationId}
        />
      </aside>
      <main className="flex-1 flex flex-col overflow-hidden">
        <div className="flex-1 overflow-y-auto p-6">
          <ConversationThread
            detail={conversationDetail.data}
            isLoading={conversationDetail.isLoading}
            pendingQuestion={pendingQuestion}
            isStreaming={isStreaming}
            onSave={handleSave}
            isSaving={isSaving}
            onExport={handleExport}
            isExporting={isExporting}
            onFork={handleFork}
            onSaveSelection={handleSaveSelection}
            isSavingSelection={isSavingSelection}
          />
          {pendingError && (
            <div className="mt-4 rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
              {pendingError}
            </div>
          )}
        </div>
        <div className="border-t border-slate-200 p-4">
          <QueryInput onSubmit={handleSubmit} disabled={isBusy} />
        </div>
      </main>
    </div>
  );
}
