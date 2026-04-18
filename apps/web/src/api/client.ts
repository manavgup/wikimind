// Thin fetch wrapper around the WikiMind gateway API.
// Reads base URL from VITE_API_URL with a localhost fallback.

const BASE_URL: string =
  (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ??
  "http://localhost:7842";

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.status = status;
    this.body = body;
    this.name = "ApiError";
  }
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE" | "PATCH";
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = new URL(`${BASE_URL}${path}`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null) {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return url.toString();
}

export async function apiFetch<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { method = "GET", body, query, headers = {}, signal } = options;

  const token = localStorage.getItem("wikimind_token");
  const authHeaders: Record<string, string> = token
    ? { Authorization: `Bearer ${token}` }
    : {};

  const init: RequestInit = {
    method,
    headers: {
      Accept: "application/json",
      ...authHeaders,
      ...headers,
    },
    signal,
  };

  if (body !== undefined) {
    if (body instanceof FormData) {
      init.body = body;
    } else {
      init.headers = {
        ...init.headers,
        "Content-Type": "application/json",
      };
      init.body = JSON.stringify(body);
    }
  }

  const response = await fetch(buildUrl(path, query), init);

  if (!response.ok) {
    let parsed: unknown = null;
    try {
      parsed = await response.json();
    } catch {
      parsed = await response.text().catch(() => null);
    }
    const message =
      typeof parsed === "object" &&
      parsed !== null &&
      "detail" in parsed &&
      typeof (parsed as { detail: unknown }).detail === "string"
        ? (parsed as { detail: string }).detail
        : `Request failed: ${response.status} ${response.statusText}`;
    throw new ApiError(response.status, message, parsed);
  }

  // 204 / empty body
  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export function getBaseUrl(): string {
  return BASE_URL;
}

export function getWebSocketUrl(): string {
  // Convert http(s):// → ws(s)://
  return BASE_URL.replace(/^http/, "ws") + "/ws";
}
