import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState, useRef } from "react";
import {
  askQuestion,
  askQuestionStream,
  getConversation,
  listConversations,
  fileBackConversation,
  fileBackSelection,
  exportConversation,
  forkConversation,
  type AskRequest,
  type ConversationDetail,
  type TurnSelection,
} from "../../api/query";
import { useWebSocketStore } from "../../store/websocket";
import { SelectionProvider, useSelection } from "../../store/selection";
import { ConversationHistory } from "./ConversationHistory";
import { ConversationThread } from "./ConversationThread";
import { QueryInput } from "./QueryInput";

export function AskView() {
  return (
    <SelectionProvider>
      <AskViewInner />
    </SelectionProvider>
  );
}

function AskViewInner() {
  const { conversationId } = useParams<{ conversationId?: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const pushToast = useWebSocketStore((s) => s.pushToast);
  const [pendingError, setPendingError] = useState<string | null>(null);

  // Streaming state
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
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

  // Fork mutation
  const fork = useMutation({
    mutationFn: ({ id, turnIndex, newQuestion }: { id: string; turnIndex: number; newQuestion: string }) =>
      forkConversation(id, { turn_index: turnIndex, new_question: newQuestion }),
    onSuccess: (response) => {
      setPendingQuestion(null);
      setPendingError(null);
      const newId = response.conversation.id;
      navigate(`/ask/${newId}`, { replace: true });
      queryClient.setQueryData<ConversationDetail>(
        ["conversation", newId],
        {
          conversation: response.conversation,
          queries: [response.query],
        },
      );
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      // Invalidate parent to update fork_count
      if (conversationId) {
        queryClient.invalidateQueries({ queryKey: ["conversation", conversationId] });
      }
      pushToast({
        kind: "success",
        title: "Created branch",
        detail: `Forked at turn ${response.query.turn_index + 1}`,
      });
    },
    onError: (err: Error) => {
      setPendingQuestion(null);
      setPendingError(err.message || "Failed to create branch");
    },
  });

  const handleFork = useCallback(
    (turnIndex: number, newQuestion: string) => {
      if (!conversationId) return;
      setPendingQuestion(newQuestion);
      fork.mutate({ id: conversationId, turnIndex, newQuestion });
    },
    [conversationId, fork],
  );

  const selection = useSelection();

  // File-back mutation (whole conversation)
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

  // File-back selection mutation (partial / multi-thread)
  const fileBackSel = useMutation({
    mutationFn: (selections: TurnSelection[]) =>
      fileBackSelection({ selections }),
    onSuccess: (response) => {
      selection.clear();
      queryClient.invalidateQueries({ queryKey: ["conversation", conversationId] });
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      pushToast({
        kind: "success",
        title: "Saved selected turns to wiki",
        detail: response.article.title,
      });
    },
    onError: (err: Error) => {
      pushToast({
        kind: "error",
        title: "Failed to save selection",
        detail: err.message,
      });
    },
  });

  const handleSubmit = useCallback(async (question: string) => {
    const req: AskRequest = { question, conversation_id: conversationId };

    setPendingError(null);
    setPendingQuestion(question);
    setIsStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      for await (const event of askQuestionStream(req, controller.signal)) {
        switch (event.type) {
          case "chunk":
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
      if (controller.signal.aborted) return;
      setPendingError(null);
      askFallback.mutate(req);
    } finally {
      setIsStreaming(false);
      abortRef.current = null;
    }
  }, [conversationId, navigate, queryClient, askFallback]);

  const handleSave = () => {
    if (conversationId) fileBack.mutate(conversationId);
  };

  const handleSaveSelection = () => {
    if (selection.count === 0) return;
    // Group selections by conversation_id
    const byConv = new Map<string, number[]>();
    for (const item of selection.items) {
      const indices = byConv.get(item.conversationId) ?? [];
      indices.push(item.turnIndex);
      byConv.set(item.conversationId, indices);
    }
    const selections: TurnSelection[] = Array.from(byConv.entries()).map(
      ([conversation_id, turn_indices]) => ({
        conversation_id,
        turn_indices: turn_indices.sort((a, b) => a - b),
      }),
    );
    fileBackSel.mutate(selections);
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

  const isBusy = isStreaming || askFallback.isPending || fork.isPending;

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
            isSaving={fileBack.isPending}
            onExport={handleExport}
            isExporting={isExporting}
            onFork={handleFork}
            onSaveSelection={handleSaveSelection}
            isSavingSelection={fileBackSel.isPending}
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
