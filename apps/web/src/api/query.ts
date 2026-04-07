// Endpoints in src/wikimind/api/routes/query.py.

import { apiFetch } from "./client";

export interface AskRequest {
  question: string;
  file_back?: boolean;
}

export interface QueryRecord {
  id: string;
  question: string;
  answer: string;
  confidence: string | null;
  source_article_ids: string | null;
  filed_back: boolean;
  filed_article_id: string | null;
  created_at: string;
}

export function askQuestion(req: AskRequest): Promise<QueryRecord> {
  return apiFetch<QueryRecord>("/query", { method: "POST", body: req });
}

export function queryHistory(limit = 50): Promise<QueryRecord[]> {
  return apiFetch<QueryRecord[]>("/query/history", { query: { limit } });
}
