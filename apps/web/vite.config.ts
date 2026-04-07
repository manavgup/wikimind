import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

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
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
