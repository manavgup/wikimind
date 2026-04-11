// Endpoints in src/wikimind/api/routes/query.py.

import { apiFetch, getBaseUrl } from "./client";

// ----- Types -----

export interface AskRequest {
  question: string;
  conversation_id?: string;
  file_back?: boolean; // deprecated; ignored by new conversation-aware backend
}

export interface SourceResponse {
  id: string;
  source_type: string;
  title: string | null;
  source_url: string | null;
  ingested_at: string;
}

export interface CitationResponse {
  article: { slug: string; title: string };
  sources: SourceResponse[];
}

export interface QueryRecord {
  id: string;
  question: string;
  answer: string;
  confidence: string | null;
  source_article_ids: string | null;
  related_article_ids: string | null;
  filed_back: boolean;
  filed_article_id: string | null;
  created_at: string;
  conversation_id: string | null;
  turn_index: number;
  citations?: CitationResponse[];
}

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  filed_article_id: string | null;
  parent_conversation_id: string | null;
  forked_at_turn_index: number | null;
  fork_count: number;
}

export interface ConversationSummary extends Conversation {
  turn_count: number;
}

export interface ConversationDetail {
  conversation: Conversation;
  queries: QueryRecord[];
}

export interface AskResponse {
  query: QueryRecord;
  conversation: Conversation;
}

export interface FileBackResponse {
  article: { id: string; slug: string; title: string };
  was_update: boolean;
}

export interface ForkRequest {
  turn_index: number;
  new_question: string;
}

export interface TurnSelection {
  conversation_id: string;
  turn_indices: number[];
}

export interface FileBackSelectionRequest {
  selections: TurnSelection[];
  title?: string;
}

export interface FileBackSelectionResponse {
  article: { id: string; slug: string; title: string };
}

// ----- Functions -----

export function askQuestion(req: AskRequest): Promise<AskResponse> {
  return apiFetch<AskResponse>("/query", { method: "POST", body: req });
}

export function queryHistory(limit = 50): Promise<QueryRecord[]> {
  return apiFetch<QueryRecord[]>("/query/history", { query: { limit } });
}

export function listConversations(limit = 50): Promise<ConversationSummary[]> {
  return apiFetch<ConversationSummary[]>("/query/conversations", { query: { limit } });
}

export function getConversation(id: string): Promise<ConversationDetail> {
  return apiFetch<ConversationDetail>(`/query/conversations/${id}`);
}

export function fileBackConversation(id: string): Promise<FileBackResponse> {
  return apiFetch<FileBackResponse>(`/query/conversations/${id}/file-back`, { method: "POST" });
}

export function fileBackSelection(req: FileBackSelectionRequest): Promise<FileBackSelectionResponse> {
  return apiFetch<FileBackSelectionResponse>("/query/conversations/file-back", {
    method: "POST",
    body: req,
  });
}

export async function exportConversation(id: string): Promise<string> {
  const res = await fetch(`${getBaseUrl()}/query/conversations/${id}/export`);
  if (!res.ok) throw new Error("Export failed");
  return res.text();
}

export function forkConversation(id: string, req: ForkRequest): Promise<AskResponse> {
  return apiFetch<AskResponse>(`/query/conversations/${id}/fork`, {
    method: "POST",
    body: req,
  });
}

// ----- SSE Streaming -----

export type StreamEvent =
  | { type: "chunk"; text: string }
  | { type: "done"; response: AskResponse }
  | { type: "error"; code: string; message: string };

/**
 * POST to /query/stream and yield parsed SSE events.
 *
 * Uses native fetch + ReadableStream (not EventSource, which only supports GET).
 * The caller iterates with `for await (const event of askQuestionStream(req))`.
 */
export async function* askQuestionStream(
  req: AskRequest,
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const res = await fetch(`${getBaseUrl()}/query/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(req),
    signal,
  });

  if (!res.ok) {
    let detail = `Stream request failed: ${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // ignore parse failures
    }
    throw new Error(detail);
  }

  const reader = res.body?.getReader();
  if (!reader) throw new Error("Response body is not readable");

  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // SSE messages are separated by double newlines
      const messages = buffer.split("\n\n");
      // Keep the last (possibly incomplete) chunk in the buffer
      buffer = messages.pop() ?? "";

      for (const msg of messages) {
        const event = parseSSEMessage(msg);
        if (event) yield event;
      }
    }

    // Process any remaining buffer
    if (buffer.trim()) {
      const event = parseSSEMessage(buffer);
      if (event) yield event;
    }
  } finally {
    reader.releaseLock();
  }
}

function parseSSEMessage(raw: string): StreamEvent | null {
  let eventType = "";
  let data = "";

  for (const line of raw.split("\n")) {
    if (line.startsWith("event: ")) {
      eventType = line.slice(7).trim();
    } else if (line.startsWith("data: ")) {
      data = line.slice(6);
    } else if (line.startsWith("data:")) {
      data = line.slice(5);
    }
  }

  if (!eventType || !data) return null;

  try {
    const parsed = JSON.parse(data);
    switch (eventType) {
      case "chunk":
        return { type: "chunk", text: parsed.text ?? "" };
      case "done":
        return { type: "done", response: parsed as AskResponse };
      case "error":
        return {
          type: "error",
          code: parsed.code ?? "unknown",
          message: parsed.message ?? "Unknown streaming error",
        };
      default:
        return null;
    }
  } catch {
    return null;
  }
}
