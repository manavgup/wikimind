// Manages the lifecycle of the gateway WebSocket connection.
// On mount: connect, push events into the Zustand store, auto-reconnect on disconnect.
// Also invalidates relevant TanStack Query caches when terminal events arrive.

import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { getWebSocketUrl } from "../api/client";
import { useWebSocketStore } from "../store/websocket";
import type { WSEvent } from "../types/api";

const RECONNECT_DELAY_MS = 2000;

export function useWebSocket(): void {
  const setState = useWebSocketStore((s) => s.setState);
  const ingest = useWebSocketStore((s) => s.ingest);
  const pushToast = useWebSocketStore((s) => s.pushToast);
  const queryClient = useQueryClient();
  const socketRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<number | null>(null);
  const stoppedRef = useRef(false);

  useEffect(() => {
    stoppedRef.current = false;

    function connect(): void {
      if (stoppedRef.current) return;
      setState("connecting");

      let socket: WebSocket;
      try {
        socket = new WebSocket(getWebSocketUrl());
      } catch {
        scheduleReconnect();
        return;
      }
      socketRef.current = socket;

      socket.onopen = () => {
        setState("open");
      };

      socket.onmessage = (msg) => {
        try {
          const event = JSON.parse(msg.data) as WSEvent;
          ingest(event);

          if (event.event === "compilation.complete") {
            queryClient.invalidateQueries({ queryKey: ["sources"] });
            queryClient.invalidateQueries({ queryKey: ["articles"] });
            queryClient.invalidateQueries({ queryKey: ["concepts"] });
          }
          if (event.event === "compilation.failed") {
            queryClient.invalidateQueries({ queryKey: ["sources"] });
          }
          if (event.event === "article.recompiled") {
            queryClient.invalidateQueries({ queryKey: ["articles"] });
            queryClient.invalidateQueries({ queryKey: ["lint"] });
          }
          if (event.event === "budget.warning") {
            pushToast({
              kind: "info",
              title: "Budget warning",
              detail: `Monthly spend at ${event.pct}% of budget ($${event.spend_usd.toFixed(2)}/$${event.budget_usd.toFixed(2)})`,
            });
            queryClient.invalidateQueries({ queryKey: ["cost-breakdown"] });
          }
          if (event.event === "budget.exceeded") {
            pushToast({
              kind: "error",
              title: "Budget exceeded",
              detail: `Monthly spend exceeded budget ($${event.spend_usd.toFixed(2)}/$${event.budget_usd.toFixed(2)})`,
            });
            queryClient.invalidateQueries({ queryKey: ["cost-breakdown"] });
          }
        } catch {
          // Ignore non-JSON frames
        }
      };

      socket.onerror = () => {
        // onclose will fire and trigger reconnection
      };

      socket.onclose = () => {
        setState("closed");
        scheduleReconnect();
      };
    }

    function scheduleReconnect(): void {
      if (stoppedRef.current) return;
      if (reconnectRef.current !== null) return;
      reconnectRef.current = window.setTimeout(() => {
        reconnectRef.current = null;
        connect();
      }, RECONNECT_DELAY_MS);
    }

    connect();

    return () => {
      stoppedRef.current = true;
      if (reconnectRef.current !== null) {
        window.clearTimeout(reconnectRef.current);
        reconnectRef.current = null;
      }
      const socket = socketRef.current;
      if (socket && socket.readyState <= 1) {
        socket.close();
      }
      socketRef.current = null;
    };
  }, [setState, ingest, pushToast, queryClient]);
}
