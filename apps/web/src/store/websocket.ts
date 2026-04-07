// Zustand store for the WikiMind WebSocket connection.
//
// Tracks connection state, the latest job-progress percentages keyed by job_id,
// and a small list of recent toasts derived from broadcast events.
// `useWebSocket` (in hooks/) is responsible for the actual socket lifecycle.

import { create } from "zustand";
import type { WSEvent } from "../types/api";

export type WSConnectionState = "idle" | "connecting" | "open" | "closed";

export interface JobProgress {
  jobId: string;
  pct: number;
  message: string;
  updatedAt: number;
}

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
  jobs: Record<string, JobProgress>;
  toasts: Toast[];
  setState: (state: WSConnectionState) => void;
  ingest: (event: WSEvent) => void;
  dismissToast: (id: string) => void;
}

const MAX_TOASTS = 5;

function makeId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export const useWebSocketStore = create<WebSocketStore>((set) => ({
  state: "idle",
  lastEvent: null,
  jobs: {},
  toasts: [],

  setState: (state) => set({ state }),

  ingest: (event) =>
    set((store) => {
      const next: Partial<WebSocketStore> = { lastEvent: event };

      if (event.event === "job.progress") {
        next.jobs = {
          ...store.jobs,
          [event.job_id]: {
            jobId: event.job_id,
            pct: event.pct,
            message: event.message ?? "",
            updatedAt: Date.now(),
          },
        };
      }

      if (event.event === "compilation.complete") {
        const toast: Toast = {
          id: makeId(),
          kind: "success",
          title: "Compilation complete",
          detail: event.article_title,
          createdAt: Date.now(),
        };
        next.toasts = [toast, ...store.toasts].slice(0, MAX_TOASTS);
      }

      if (event.event === "compilation.failed") {
        const toast: Toast = {
          id: makeId(),
          kind: "error",
          title: "Compilation failed",
          detail: event.error,
          createdAt: Date.now(),
        };
        next.toasts = [toast, ...store.toasts].slice(0, MAX_TOASTS);
      }

      return next;
    }),

  dismissToast: (id) =>
    set((store) => ({ toasts: store.toasts.filter((t) => t.id !== id) })),
}));
