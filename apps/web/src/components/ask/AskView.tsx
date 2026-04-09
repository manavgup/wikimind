import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  askQuestion,
  getConversation,
  listConversations,
  fileBackConversation,
  exportConversation,
  type AskRequest,
  type ConversationDetail,
} from "../../api/query";
import { useWebSocketStore } from "../../store/websocket";
import { ConversationHistory } from "./ConversationHistory";
import { ConversationThread } from "./ConversationThread";
import { QueryInput } from "./QueryInput";

export function AskView() {
  const { conversationId } = useParams<{ conversationId?: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const pushToast = useWebSocketStore((s) => s.pushToast);
  const [pendingError, setPendingError] = useState<string | null>(null);

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

  // Ask mutation — appends a turn to the current conversation, or starts a new one
  const ask = useMutation({
    mutationFn: (req: AskRequest) => askQuestion(req),
    onSuccess: (response) => {
      setPendingError(null);
      const newId = response.conversation.id;
      // If we were on /ask (no id), navigate to /ask/:newId
      if (!conversationId) {
        navigate(`/ask/${newId}`, { replace: true });
      }
      // Eagerly merge the new turn into the cache so the UI updates
      // instantly without an invalidation roundtrip. This masks the
      // network delay between "answer ready" and "conversation refetched".
      queryClient.setQueryData<ConversationDetail>(
        ["conversation", newId],
        (old) => ({
          conversation: response.conversation,
          queries: [...(old?.queries ?? []), response.query],
        }),
      );
      // The sidebar list still needs a refresh for the updated turn count.
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
    onError: (err: Error) => {
      setPendingError(err.message || "Failed to ask question");
    },
  });

  // File-back mutation
  const fileBack = useMutation({
    mutationFn: (id: string) => fileBackConversation(id),
    onSuccess: (response) => {
      queryClient.invalidateQueries({ queryKey: ["conversation", conversationId] });
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      pushToast({
        kind: "success",
        title: response.was_update ? "Updated wiki article" : "Saved thread to wiki",
        detail: response.article.title,
      });
    },
    onError: (err: Error) => {
      pushToast({
        kind: "error",
        title: "Failed to save thread",
        detail: err.message,
      });
    },
  });

  const handleSubmit = (question: string) => {
    ask.mutate({ question, conversation_id: conversationId });
  };

  const handleSave = () => {
    if (conversationId) fileBack.mutate(conversationId);
  };

  const [isExporting, setIsExporting] = useState(false);
  const handleExport = async () => {
    if (!conversationId) return;
    setIsExporting(true);
    try {
      const markdown = await exportConversation(conversationId);
      const blob = new Blob([markdown], { type: "text/markdown" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download =
        (conversationDetail.data?.conversation.title ?? "conversation") + ".md";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      pushToast({
        kind: "error",
        title: "Failed to export conversation",
        detail: "Could not download the markdown file.",
      });
    } finally {
      setIsExporting(false);
    }
  };

  // Optimistic UI: while the ask mutation is in flight, show the user's
  // question in a "pending" turn card so they get immediate visual feedback
  // instead of staring at a frozen UI for 5-30 seconds.
  const pendingQuestion = ask.isPending ? (ask.variables?.question ?? null) : null;

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
            onSave={handleSave}
            isSaving={fileBack.isPending}
            onExport={handleExport}
            isExporting={isExporting}
          />
          {pendingError && (
            <div className="mt-4 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-700">
              {pendingError}
            </div>
          )}
        </div>
        <div className="border-t border-slate-200 p-4">
          <QueryInput onSubmit={handleSubmit} disabled={ask.isPending} />
        </div>
      </main>
    </div>
  );
}
