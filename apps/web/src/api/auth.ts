// Auth API calls for the WikiMind OAuth2 flow.

import type { AuthUser } from "../store/auth";
import { apiFetch } from "./client";

export function fetchCurrentUser(): Promise<AuthUser> {
  return apiFetch<AuthUser>("/auth/me");
}
