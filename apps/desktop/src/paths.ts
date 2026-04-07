/**
 * Cross-platform path helpers used by the Electron main process to locate
 * the WikiMind repository, the Python interpreter inside the dev `.venv`,
 * and the built React renderer produced by `apps/web`.
 *
 * These helpers assume a developer-mode layout: the Electron app is launched
 * from a checkout of the repo with `make install-dev` already run. Production
 * packaging (PyInstaller bundle, signed installers) is intentionally out of
 * scope for this minimal shell.
 */

import { existsSync } from "node:fs";
import { join, resolve } from "node:path";
import { platform } from "node:process";

/**
 * Walk up from `startDir` until we find a directory that looks like the
 * WikiMind repo root (contains both `pyproject.toml` and `apps/`).
 *
 * @param startDir Absolute path to start the search from.
 * @returns        The absolute path of the repo root.
 * @throws         If no repo root is found before reaching the filesystem root.
 */
export function findRepoRoot(startDir: string): string {
  let current = resolve(startDir);
  while (true) {
    const hasPyproject = existsSync(join(current, "pyproject.toml"));
    const hasApps = existsSync(join(current, "apps"));
    if (hasPyproject && hasApps) {
      return current;
    }
    const parent = resolve(current, "..");
    if (parent === current) {
      throw new Error(
        `Could not find WikiMind repo root by walking up from ${startDir}. ` +
          `Set WIKIMIND_REPO_ROOT to override.`,
      );
    }
    current = parent;
  }
}

/**
 * Locate the venv Python interpreter for the current platform.
 *
 * @param repoRoot Absolute path to the WikiMind repo root.
 * @returns        Absolute path to the venv `python` (or `python.exe` on win32).
 * @throws         If the expected interpreter does not exist on disk.
 */
export function findVenvPython(repoRoot: string): string {
  const candidate =
    platform === "win32"
      ? join(repoRoot, ".venv", "Scripts", "python.exe")
      : join(repoRoot, ".venv", "bin", "python");
  if (!existsSync(candidate)) {
    throw new Error(
      `Python venv not found at ${candidate}. Run 'make install-dev' from the repo root first.`,
    );
  }
  return candidate;
}

/**
 * Locate the built React app produced by `npm run build` in `apps/web/`.
 *
 * @param repoRoot Absolute path to the WikiMind repo root.
 * @returns        Absolute path to `apps/web/dist/index.html`.
 * @throws         If the renderer has not been built yet.
 */
export function findRendererIndex(repoRoot: string): string {
  const candidate = join(repoRoot, "apps", "web", "dist", "index.html");
  if (!existsSync(candidate)) {
    throw new Error(
      `React build not found at ${candidate}. Run 'make frontend-build' from the repo root first.`,
    );
  }
  return candidate;
}
