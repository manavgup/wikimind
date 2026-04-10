// TypeScript mirrors of the Pydantic models in src/wikimind/models.py.
// Keep in sync with the backend. The openapi.yaml is the source of truth.

export type SourceType =
  | "url"
  | "pdf"
  | "youtube"
  | "audio"
  | "text"
  | "rss"
  | "email"
  | "obsidian";

export type IngestStatus = "pending" | "processing" | "compiled" | "failed";

export type ConfidenceLevel = "sourced" | "mixed" | "inferred" | "opinion";

export type JobStatus = "queued" | "running" | "complete" | "failed";

export type JobType =
  | "compile_source"
  | "lint_wiki"
  | "reindex"
  | "embed_chunks"
  | "sync_push"
  | "sync_pull";

export interface Source {
  id: string;
  source_type: SourceType;
  source_url: string | null;
  title: string | null;
  author: string | null;
  published_date: string | null;
  status: IngestStatus;
  ingested_at: string;
  compiled_at: string | null;
  token_count: number | null;
  error_message: string | null;
  file_path: string | null;
}

export interface Article {
  id: string;
  slug: string;
  title: string;
  summary: string | null;
  confidence: ConfidenceLevel | null;
  linter_score: number | null;
  created_at: string;
  updated_at: string;
}

export interface BacklinkEntry {
  id: string;
  title: string;
  slug: string;
}

export interface ArticleResponse extends Article {
  content: string;
  backlinks_in: BacklinkEntry[];
  backlinks_out: BacklinkEntry[];
  concepts: string[];
}

export interface Concept {
  id: string;
  name: string;
  parent_id: string | null;
  article_count: number;
  description: string | null;
}

export interface Job {
  id: string;
  job_type: JobType;
  status: JobStatus;
  source_id: string | null;
  priority: number;
  queued_at: string;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
  result_summary: string | null;
}

export interface IngestURLRequest {
  url: string;
  auto_compile?: boolean;
}

export interface TriggerCompileResponse {
  job_id: string;
  status: string;
}

// WebSocket event shapes (see src/wikimind/api/routes/ws.py)
export type WSEvent =
  | { event: "connected"; message?: string }
  | { event: "keepalive" }
  | { event: "pong" }
  | { event: "job.progress"; job_id: string; pct: number; message?: string }
  | { event: "source.progress"; source_id: string; pct: number; message?: string }
  | { event: "compilation.complete"; article_slug: string; article_title: string }
  | { event: "compilation.failed"; source_id: string; error: string }
  | { event: "sync.complete"; pushed: number; pulled: number; conflicts?: number }
  | { event: "linter.alert"; type: string; articles: string[] };
