import { useCallback, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  askQuestion,
  askQuestionStream,
  forkConversation,
  type AskRequest,
  type ConversationDetail,
} from "../../api/query";
import { useWebSocketStore } from "../../store/websocket";

interface UseAskStreamOptions {
  conversationId: string | undefined;
}

export function useAskStream({ conversationId }: UseAskStreamOptions) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const pushToast = useWebSocketStore((s) => s.pushToast);

  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const [pendingError, setPendingError] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

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
    mutationFn: ({
      id,
      turnIndex,
      newQuestion,
    }: {
      id: string;
      turnIndex: number;
      newQuestion: string;
    }) => forkConversation(id, { turn_index: turnIndex, new_question: newQuestion }),
    onSuccess: (response) => {
      setPendingQuestion(null);
      setPendingError(null);
      const newId = response.conversation.id;
      navigate(`/ask/${newId}`, { replace: true });
      queryClient.setQueryData<ConversationDetail>(["conversation", newId], {
        conversation: response.conversation,
        queries: [response.query],
      });
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      // Invalidate parent to update fork_count
      if (conversationId) {
        queryClient.invalidateQueries({
          queryKey: ["conversation", conversationId],
        });
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

  const handleSubmit = useCallback(
    async (question: string) => {
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
              queryClient.invalidateQueries({
                queryKey: ["conversation", newId],
              });
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
    },
    [conversationId, navigate, queryClient, askFallback],
  );

  const handleFork = useCallback(
    (turnIndex: number, newQuestion: string) => {
      if (!conversationId) return;
      setPendingQuestion(newQuestion);
      fork.mutate({ id: conversationId, turnIndex, newQuestion });
    },
    [conversationId, fork],
  );

  const isBusy = isStreaming || askFallback.isPending || fork.isPending;

  return {
    pendingQuestion,
    pendingError,
    isStreaming,
    isBusy,
    handleSubmit,
    handleFork,
  };
}
