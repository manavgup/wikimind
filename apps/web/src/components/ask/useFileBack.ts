import { useCallback } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  fileBackConversation,
  fileBackSelection,
  type TurnSelection,
} from "../../api/query";
import { useWebSocketStore } from "../../store/websocket";
import { useSelection } from "../../store/selection";

interface UseFileBackOptions {
  conversationId: string | undefined;
}

export function useFileBack({ conversationId }: UseFileBackOptions) {
  const queryClient = useQueryClient();
  const pushToast = useWebSocketStore((s) => s.pushToast);
  const selection = useSelection();

  // File-back mutation (whole conversation)
  const fileBack = useMutation({
    mutationFn: (id: string) => fileBackConversation(id),
    onSuccess: (response) => {
      queryClient.invalidateQueries({
        queryKey: ["conversation", conversationId],
      });
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
    mutationFn: (selections: TurnSelection[]) => fileBackSelection({ selections }),
    onSuccess: (response) => {
      selection.clear();
      queryClient.invalidateQueries({
        queryKey: ["conversation", conversationId],
      });
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

  const handleSave = useCallback(() => {
    if (conversationId) fileBack.mutate(conversationId);
  }, [conversationId, fileBack]);

  const handleSaveSelection = useCallback(() => {
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
  }, [selection, fileBackSel]);

  return {
    handleSave,
    isSaving: fileBack.isPending,
    handleSaveSelection,
    isSavingSelection: fileBackSel.isPending,
  };
}
