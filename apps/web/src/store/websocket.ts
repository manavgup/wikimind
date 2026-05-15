// Zustand store for the WikiMind WebSocket connection.
//
// Tracks connection state, per-source status messages, and recent toasts.
// `useWebSocket` (in hooks/) is responsible for the actual socket lifecycle.

import { create } from "zustand";
import type { WSEvent } from "../types/api";

export type WSConnectionState = "idle" | "connecting" | "open" | "closed";

export interface Toast {
  id: string;
  kind: "success" | "error" | "info";
  title: string;
  detail?: string;
  createdAt: number;
}

interface WebSocketStore {
  state: WSConnectionState;
  lastEvent: WSEvent | null;
  /** Human-readable status message per source_id. */
  sourceStatus: Record<string, string>;
  toasts: Toast[];
  setState: (state: WSConnectionState) => void;
  ingest: (event: WSEvent) => void;
  pushToast: (input: { kind: Toast["kind"]; title: string; detail?: string }) => void;
  dismissToast: (id: string) => void;
}

const MAX_TOASTS = 5;
const TOAST_AUTO_DISMISS_MS = 5_000;

function makeId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export const useWebSocketStore = create<WebSocketStore>((set) => ({
  state: "idle",
  lastEvent: null,
  sourceStatus: {},
  toasts: [],

  setState: (state) => set({ state }),

  ingest: (event) => {
    const toastId = makeId();
    set((store) => {
      const next: Partial<WebSocketStore> = { lastEvent: event };

      if (event.event === "source.progress") {
        next.sourceStatus = {
          ...store.sourceStatus,
          [event.source_id]: event.message ?? "",
        };
      }

      if (event.event === "compilation.complete") {
        // Clear status for this source (it's done)
        const { [event.article_slug]: _, ...rest } = store.sourceStatus;
        next.sourceStatus = rest;
        next.toasts = [
          {
            id: toastId,
            kind: "success" as const,
            title: "Compilation complete",
            detail: event.article_title,
            createdAt: Date.now(),
          },
          ...store.toasts,
        ].slice(0, MAX_TOASTS);
      }

      if (event.event === "compilation.failed") {
        next.toasts = [
          {
            id: toastId,
            kind: "error" as const,
            title: "Compilation failed",
            detail: event.error,
            createdAt: Date.now(),
          },
          ...store.toasts,
        ].slice(0, MAX_TOASTS);
      }

      return next;
    });
    if (event.event === "compilation.complete" || event.event === "compilation.failed") {
      setTimeout(() => useWebSocketStore.getState().dismissToast(toastId), TOAST_AUTO_DISMISS_MS);
    }
  },

  pushToast: (input) => {
    const id = makeId();
    set((store) => ({
      toasts: [
        { id, kind: input.kind, title: input.title, detail: input.detail, createdAt: Date.now() },
        ...store.toasts,
      ].slice(0, MAX_TOASTS),
    }));
    setTimeout(() => useWebSocketStore.getState().dismissToast(id), TOAST_AUTO_DISMISS_MS);
  },

  dismissToast: (id) =>
    set((store) => ({ toasts: store.toasts.filter((t) => t.id !== id) })),
}));
