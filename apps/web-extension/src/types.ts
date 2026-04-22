export type IngestStatus = "pending" | "processing" | "compiled" | "failed";

export interface Source {
  id: string;
  source_type: string;
  source_url: string | null;
  title: string | null;
  status: IngestStatus;
  ingested_at: string;
  compiled_at: string | null;
  error_message: string | null;
}

export interface IngestURLRequest {
  url: string;
  auto_compile: boolean;
}

export interface ApiErrorBody {
  error?: {
    code: string;
    message: string;
    request_id?: string;
  };
  detail?: string;
}

export interface ClipRecord {
  sourceId: string;
  url: string;
  title: string | null;
  status: IngestStatus;
  clippedAt: string;
}

export interface ExtensionSettings {
  gatewayUrl: string;
}
