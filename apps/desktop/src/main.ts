/**
 * WikiMind Electron main process.
 *
 * Responsibilities:
 *  1. Spawn the local FastAPI daemon (uvicorn) as a child process on :7842.
 *  2. Wait for the daemon's /health endpoint to become reachable.
 *  3. Open a BrowserWindow loading the React renderer from `apps/web/dist`.
 *  4. Cleanly terminate the daemon when the app quits.
 *
 * This is a deliberately minimal shell — no PyInstaller bundle, no
 * code-signing, no auto-updater, no loading screen. Those belong in
 * follow-up issues.
 */

import { app, BrowserWindow } from "electron";
import { ChildProcess } from "node:child_process";

import { shutdownDaemon, spawnDaemon, waitForDaemon } from "./daemon";
import { findRendererIndex, findRepoRoot, findVenvPython } from "./paths";

let daemon: ChildProcess | null = null;
let mainWindow: BrowserWindow | null = null;
let isQuitting = false;

async function startApp(): Promise<void> {
  // __dirname is `apps/desktop/dist` after tsc; walk up to find the repo
  // root. The WIKIMIND_REPO_ROOT env var overrides for unusual layouts.
  const repoRoot = process.env.WIKIMIND_REPO_ROOT ?? findRepoRoot(__dirname);

  // Validate every external resource BEFORE spawning the daemon, so a
  // missing renderer can't leave us with an orphaned Python process.
  const python = findVenvPython(repoRoot);
  const renderer = findRendererIndex(repoRoot);

  daemon = spawnDaemon(python, repoRoot);
  daemon.once("exit", (code, signal) => {
    if (!isQuitting) {
      console.error(`WikiMind daemon exited unexpectedly: code=${code} signal=${signal}`);
      app.quit();
    }
  });

  await waitForDaemon();

  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    title: "WikiMind",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  await mainWindow.loadFile(renderer);

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

app.whenReady().then(() => {
  startApp().catch((error) => {
    console.error("Failed to start WikiMind:", error);
    app.quit();
  });
});

app.on("window-all-closed", () => {
  // Exit on all platforms — there is no useful background state to keep
  // alive once the only window is closed.
  app.quit();
});

app.on("before-quit", (event) => {
  if (isQuitting || daemon === null) return;
  event.preventDefault();
  isQuitting = true;
  shutdownDaemon(daemon).finally(() => {
    daemon = null;
    app.quit();
  });
});
