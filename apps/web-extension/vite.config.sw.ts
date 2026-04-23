import { defineConfig } from "vite";

export default defineConfig({
  build: {
    outDir: "dist",
    emptyOutDir: false,
    sourcemap: true,
    lib: {
      entry: "src/background/service-worker.ts",
      formats: ["iife"],
      name: "ServiceWorker",
    },
    rollupOptions: {
      output: {
        entryFileNames: "service-worker.js",
      },
    },
  },
});
