import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Backend gateway address — single source of truth for all proxy rules.
const BACKEND = "http://localhost:7842";

// Proxy options: changeOrigin must be false so the backend receives
// Host: localhost:5173 (the proxy origin) instead of the target host.
// This is critical for OAuth — the backend builds redirect_uri from Host.
const api = { target: BACKEND, changeOrigin: false };

// All backend route prefixes.  Requests matching these are forwarded to
// the gateway; everything else is served by Vite (SPA routes, assets).
// Since PR #500 all API routes live under /api, so only /api, /auth,
// /health, and /public need proxying.  The old bare prefixes (/wiki,
// /ingest, etc.) conflicted with SPA routes like /wiki/search.
const API_PREFIXES = [
  "/api",
  "/auth",
  "/health",
  "/public",
];

export default defineConfig({
  plugins: [react()],
  // Relative base so the built index.html works under both `http://` (Vite
  // dev server) and `file://` (Electron renderer loaded via loadFile).
  // Without this, Vite emits absolute `/assets/...` paths that resolve to
  // the filesystem root under file:// and the page loads blank.
  base: "./",
  server: {
    port: 5173,
    strictPort: false,
    // Proxy API and auth routes to the backend so that dev mode is
    // single-origin, matching production.  HttpOnly cookies, OAuth
    // redirects, and relative API paths all just work.
    proxy: {
      ...Object.fromEntries(API_PREFIXES.map((p) => [p, api])),
      "/ws": { ...api, ws: true },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
