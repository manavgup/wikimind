import fs from "node:fs/promises";
import path from "node:path";

import { chromium } from "@playwright/test";

const PR_CONFIG = {
  550: {
    title: "Production Monitoring",
    capability: "Health/docs monitoring surfaces in deployed UI",
    route: "https://wikimind.fly.dev/docs",
    screenshot: "ui-discovery-docs.png",
    expectedTexts: ["Swagger UI", "health", "/health"],
  },
  558: {
    title: "Migration Replay CI",
    capability: "Migration replay workflow is visible in deployed UI",
    route: "https://wikimind.fly.dev/docs",
    screenshot: "ui-discovery-docs.png",
    expectedTexts: ["migration replay", "alembic upgrade head", "migration-replay"],
  },
  559: {
    title: "Tooling Drift Fix",
    capability: "Tooling drift fix has a user-facing surface in deployed UI",
    route: "https://wikimind.fly.dev/",
    screenshot: "ui-discovery-home.png",
    expectedTexts: ["tooling drift", "pre-commit", "uv run python"],
  },
  560: {
    title: "Zombie Source Guard",
    capability: "Zombie-source handling is visible in deployed UI",
    route: "https://wikimind.fly.dev/",
    screenshot: "ui-discovery-home.png",
    expectedTexts: ["zombie", "stuck source", "compile retry"],
  },
  561: {
    title: "Production Config Guard",
    capability: "Production health/config guard is visible in deployed UI",
    route: "https://wikimind.fly.dev/health",
    screenshot: "ui-discovery-health.png",
    expectedTexts: ["background_mode", "\"status\"", "\"version\""],
  },
  563: {
    title: "Functional Staging Smoke Tests",
    capability: "Staging smoke-test protections are visible in deployed UI",
    route: "https://wikimind.fly.dev/docs",
    screenshot: "ui-discovery-docs.png",
    expectedTexts: ["smoke", "staging", "rollback-production"],
  },
  565: {
    title: "Staging/Prod DB Separation",
    capability: "Environment database separation is visible in deployed UI",
    route: "https://wikimind.fly.dev/docs",
    screenshot: "ui-discovery-docs.png",
    expectedTexts: ["staging", "database", "postgres"],
  },
};

function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--pr") {
      args.pr = Number(argv[++i]);
    } else if (arg === "--timeout-ms") {
      args.timeoutMs = Number(argv[++i]);
    }
  }
  return args;
}

async function ensureDir(dir) {
  await fs.mkdir(dir, { recursive: true });
}

async function run() {
  const { pr, timeoutMs = 15000 } = parseArgs(process.argv);
  if (!pr || !PR_CONFIG[pr]) {
    console.error(`Unsupported or missing --pr. Supported PRs: ${Object.keys(PR_CONFIG).join(", ")}`);
    process.exit(2);
  }

  const config = PR_CONFIG[pr];
  const repoRoot = path.resolve(import.meta.dirname, "..", "..", "..");
  const evidenceDir = path.join(repoRoot, "docs", "evidence", `pr-${pr}`);
  const resultPath = path.join(evidenceDir, "ui-discovery.json");
  const screenshotPath = path.join(evidenceDir, config.screenshot);

  await ensureDir(evidenceDir);

  let gotoOk = false;
  let screenshotTaken = false;
  let error = null;
  let foundTexts = [];
  let pageTitle = "";
  let finalUrl = config.route;
  let status = "not_found";
  let browser = null;
  let context = null;

  try {
    browser = await chromium.launch({ headless: true });
    context = await browser.newContext({
      viewport: { width: 1440, height: 1024 },
      ignoreHTTPSErrors: true,
    });
    const page = await context.newPage();

    try {
      const response = await page.goto(config.route, {
        waitUntil: "domcontentloaded",
        timeout: timeoutMs,
      });
      gotoOk = Boolean(response);
      finalUrl = page.url();
      pageTitle = await page.title();
      const bodyText = await page.locator("body").innerText().catch(() => "");
      const lowerBody = bodyText.toLowerCase();
      foundTexts = config.expectedTexts.filter((text) => lowerBody.includes(text.toLowerCase()));
      status = foundTexts.length > 0 ? "found" : "not_found";
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
      pageTitle = await page.title().catch(() => "");
      status = "blocked";
    }

    await page.screenshot({ path: screenshotPath, fullPage: true }).then(() => {
      screenshotTaken = true;
    }).catch(async (err) => {
      error = error ?? (err instanceof Error ? err.message : String(err));
    });
  } catch (err) {
    error = err instanceof Error ? err.message : String(err);
    status = "blocked";
  } finally {
    if (context) {
      await context.close().catch(() => {});
    }
    if (browser) {
      await browser.close().catch(() => {});
    }
  }

  const capabilityFound = status === "found";
  const result = {
    pr,
    title: config.title,
    capability: config.capability,
    attempted_route: config.route,
    final_url: finalUrl,
    page_title: pageTitle,
    screenshot: path.basename(screenshotPath),
    screenshot_taken: screenshotTaken,
    capability_found: capabilityFound,
    found_texts: foundTexts,
    status,
    blocked_reason: status === "blocked" ? error : null,
    navigation_ok: gotoOk,
    checked_at: new Date().toISOString(),
  };

  await fs.writeFile(resultPath, `${JSON.stringify(result, null, 2)}\n`);
  process.stdout.write(`${JSON.stringify(result)}\n`);
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
