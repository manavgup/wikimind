import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState, useRef } from "react";
import {
  askQuestion,
  askQuestionStream,
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

  // Streaming state
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [hasReceivedChunk, setHasReceivedChunk] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

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

  // Non-streaming fallback mutation (used when streaming fails to connect)
  const askFallback = useMutation({
    mutationFn: (req: AskRequest) => askQuestion(req),
    onSuccess: (response) => {
      setPendingError(null);
      setPendingQuestion(null);
      const newId = response.conversation.id;
      if (!conversationId) {
        navigate(`/ask/${newId}`, { replace: true });
      }
      queryClient.setQueryData<ConversationDetail>(
        ["conversation", newId],
        (old) => ({
          conversation: response.conversation,
          queries: [...(old?.queries ?? []), response.query],
        }),
      );
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
    onError: (err: Error) => {
      setPendingQuestion(null);
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

  const handleSubmit = useCallback(async (question: string) => {
    const req: AskRequest = { question, conversation_id: conversationId };

    setPendingError(null);
    setPendingQuestion(question);
    setIsStreaming(true);
    setHasReceivedChunk(false);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      for await (const event of askQuestionStream(req, controller.signal)) {
        switch (event.type) {
          case "chunk":
            // The QA agent returns structured JSON, so we don't render
            // partial tokens — just track that the stream is active.
            if (!hasReceivedChunk) setHasReceivedChunk(true);
            break;
          case "done": {
            const response = event.response;
            const newId = response.conversation.id;
            if (!conversationId) {
              navigate(`/ask/${newId}`, { replace: true });
            }
            queryClient.setQueryData<ConversationDetail>(
              ["conversation", newId],
              (old) => ({
                conversation: response.conversation,
                queries: [...(old?.queries ?? []), response.query],
              }),
            );
            queryClient.invalidateQueries({ queryKey: ["conversations"] });
            // Also refetch the conversation detail to get full citations
            queryClient.invalidateQueries({ queryKey: ["conversation", newId] });
            setPendingQuestion(null);
            break;
          }
          case "error":
            setPendingError(event.message);
            setPendingQuestion(null);
            break;
        }
      }
    } catch (err) {
      // If the stream fails to connect, fall back to non-streaming endpoint
      if (controller.signal.aborted) return;
      setPendingError(null);
      askFallback.mutate(req);
    } finally {
      setIsStreaming(false);
      setHasReceivedChunk(false);
      abortRef.current = null;
    }
  }, [conversationId, navigate, queryClient, askFallback]);

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
      const rawTitle =
        conversationDetail.data?.conversation.title ?? "conversation";
      const safeName = rawTitle
        .replace(/[^a-zA-Z0-9_ -]/g, "")
        .replace(/ +/g, " ")
        .trim()
        || "conversation";
      a.download = safeName + ".md";
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

  const isBusy = isStreaming || askFallback.isPending;

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
            isStreaming={hasReceivedChunk}
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
          <QueryInput onSubmit={handleSubmit} disabled={isBusy} />
        </div>
      </main>
    </div>
  );
}
