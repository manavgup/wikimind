/**
 * Selection cart context for partial/multi-thread file-back.
 *
 * Persists turn selections across conversation navigation so users can
 * pick turns from multiple threads before filing them as one article.
 */

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

export interface SelectionItem {
  conversationId: string;
  turnIndex: number;
}

interface SelectionContextValue {
  /** All currently selected turns. */
  items: SelectionItem[];
  /** Add one or more turns from a conversation. */
  addTurns: (conversationId: string, turnIndices: number[]) => void;
  /** Remove a single turn. */
  removeTurn: (conversationId: string, turnIndex: number) => void;
  /** Toggle a single turn on/off. */
  toggleTurn: (conversationId: string, turnIndex: number) => void;
  /** Check if a turn is selected. */
  isSelected: (conversationId: string, turnIndex: number) => boolean;
  /** Clear all selections. */
  clear: () => void;
  /** Total number of selected turns. */
  count: number;
}

const SelectionContext = createContext<SelectionContextValue | null>(null);

export function SelectionProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<SelectionItem[]>([]);

  const addTurns = useCallback((conversationId: string, turnIndices: number[]) => {
    setItems((prev) => {
      const existing = new Set(
        prev
          .filter((i) => i.conversationId === conversationId)
          .map((i) => i.turnIndex),
      );
      const newItems = turnIndices
        .filter((idx) => !existing.has(idx))
        .map((idx) => ({ conversationId, turnIndex: idx }));
      return [...prev, ...newItems];
    });
  }, []);

  const removeTurn = useCallback((conversationId: string, turnIndex: number) => {
    setItems((prev) =>
      prev.filter(
        (i) => !(i.conversationId === conversationId && i.turnIndex === turnIndex),
      ),
    );
  }, []);

  const toggleTurn = useCallback((conversationId: string, turnIndex: number) => {
    setItems((prev) => {
      const exists = prev.some(
        (i) => i.conversationId === conversationId && i.turnIndex === turnIndex,
      );
      if (exists) {
        return prev.filter(
          (i) => !(i.conversationId === conversationId && i.turnIndex === turnIndex),
        );
      }
      return [...prev, { conversationId, turnIndex }];
    });
  }, []);

  const isSelected = useCallback(
    (conversationId: string, turnIndex: number) =>
      items.some(
        (i) => i.conversationId === conversationId && i.turnIndex === turnIndex,
      ),
    [items],
  );

  const clear = useCallback(() => setItems([]), []);

  const value = useMemo<SelectionContextValue>(
    () => ({
      items,
      addTurns,
      removeTurn,
      toggleTurn,
      isSelected,
      clear,
      count: items.length,
    }),
    [items, addTurns, removeTurn, toggleTurn, isSelected, clear],
  );

  return (
    <SelectionContext.Provider value={value}>{children}</SelectionContext.Provider>
  );
}

export function useSelection(): SelectionContextValue {
  const ctx = useContext(SelectionContext);
  if (!ctx) {
    throw new Error("useSelection must be used within a SelectionProvider");
  }
  return ctx;
}
