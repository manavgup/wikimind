/**
 * Lifecycle management for the WikiMind FastAPI daemon child process.
 *
 * The Electron main process spawns the daemon via `python -m uvicorn`,
 * waits for `/health` to become reachable, and shuts the daemon down
 * cleanly when the app quits. There is no PyInstaller bundle and no
 * supervisor — just a single child process owned by the Electron app.
 */

import { ChildProcess, spawn } from "node:child_process";

const DAEMON_HOST = "127.0.0.1";
const DAEMON_PORT = 7842;
const HEALTH_URL = `http://${DAEMON_HOST}:${DAEMON_PORT}/health`;
const HEALTH_TIMEOUT_MS = 15_000;
const HEALTH_POLL_INTERVAL_MS = 200;
const SHUTDOWN_GRACE_MS = 5_000;

/**
 * Spawn the WikiMind daemon as a child process.
 *
 * @param python  Absolute path to the Python interpreter (typically `.venv/bin/python`).
 * @param cwd     Working directory for the daemon (the repo root).
 * @returns       The spawned ChildProcess. Caller is responsible for shutdown.
 */
export function spawnDaemon(python: string, cwd: string): ChildProcess {
  const args = [
    "-m",
    "uvicorn",
    "wikimind.main:app",
    "--host",
    DAEMON_HOST,
    "--port",
    String(DAEMON_PORT),
  ];
  return spawn(python, args, {
    cwd,
    stdio: ["ignore", "inherit", "inherit"],
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
  });
}

/**
 * Poll the daemon's `/health` endpoint until it returns 200, or until the
 * timeout expires.
 *
 * @throws If the daemon does not become ready within `HEALTH_TIMEOUT_MS`.
 */
export async function waitForDaemon(): Promise<void> {
  const deadline = Date.now() + HEALTH_TIMEOUT_MS;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(HEALTH_URL);
      if (res.ok) return;
    } catch {
      // Daemon not yet listening — keep polling.
    }
    await new Promise((resolveTimer) => setTimeout(resolveTimer, HEALTH_POLL_INTERVAL_MS));
  }
  throw new Error(
    `Daemon at ${HEALTH_URL} did not become ready within ${HEALTH_TIMEOUT_MS}ms`,
  );
}

/**
 * Send SIGTERM to the daemon, then SIGKILL after a grace period if it has
 * not exited. On Windows there is no SIGTERM — Electron's `child.kill()`
 * falls back to a forced terminate, which is acceptable for our use case.
 *
 * @param child The ChildProcess returned by `spawnDaemon`.
 */
export function shutdownDaemon(child: ChildProcess): Promise<void> {
  return new Promise((resolveShutdown) => {
    if (child.exitCode !== null || child.signalCode !== null) {
      resolveShutdown();
      return;
    }
    const fallback = setTimeout(() => {
      try {
        child.kill("SIGKILL");
      } catch {
        // Process already gone.
      }
      resolveShutdown();
    }, SHUTDOWN_GRACE_MS);
    child.once("exit", () => {
      clearTimeout(fallback);
      resolveShutdown();
    });
    try {
      child.kill("SIGTERM");
    } catch {
      clearTimeout(fallback);
      resolveShutdown();
    }
  });
}
