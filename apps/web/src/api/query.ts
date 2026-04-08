// Endpoints in src/wikimind/api/routes/query.py.

import { apiFetch } from "./client";

// ----- Types -----

export interface AskRequest {
  question: string;
  conversation_id?: string;
  file_back?: boolean; // deprecated; ignored by new conversation-aware backend
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
}

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  filed_article_id: string | null;
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
