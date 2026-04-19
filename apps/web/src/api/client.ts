// Thin fetch wrapper around the WikiMind gateway API.
// Reads base URL from VITE_API_URL with a localhost fallback.

// In production the frontend is served by the same origin as the API,
// so an empty BASE_URL uses relative paths. In development, VITE_API_URL
// points to the local gateway (e.g. http://localhost:7842).
const BASE_URL: string =
  (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ??
  "";

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
  // When BASE_URL is empty (production same-origin), use window.location.origin
  // as the base for URL construction.
  const base = BASE_URL || window.location.origin;
  const url = new URL(`${base}${path}`);
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
  const base = BASE_URL || window.location.origin;
  return base.replace(/^http/, "ws") + "/ws";
}
