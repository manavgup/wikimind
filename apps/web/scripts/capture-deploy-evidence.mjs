#!/usr/bin/env node
/**
 * Capture screenshots of the WikiMind production deployment for deploy-pipeline evidence.
 *
 * Usage:
 *   cd apps/web
 *   JWT=<token> node scripts/capture-deploy-evidence.mjs
 *
 * Prerequisites:
 *   cd apps/web && npx playwright install chromium
 */

import { chromium } from "@playwright/test";
import { mkdirSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUTPUT_DIR = resolve(__dirname, "../../../docs/evidence/deploy-pipeline");
const BASE_URL = "https://wikimind.fly.dev";
const COOKIE_NAME = "wikimind_session";

const JWT = process.env.JWT;
if (!JWT) {
  console.error("ERROR: JWT environment variable is required.");
  console.error("Run the magic-link flow first to obtain a JWT token.");
  process.exit(1);
}

mkdirSync(OUTPUT_DIR, { recursive: true });

async function capture() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });

  // Set the auth cookie so protected routes are accessible.
  await context.addCookies([
    {
      name: COOKIE_NAME,
      value: JWT,
      domain: "wikimind.fly.dev",
      path: "/",
      httpOnly: true,
      secure: true,
      sameSite: "Lax",
    },
  ]);

  const page = await context.newPage();

  // Helper: navigate and screenshot with error resilience.
  async function snap(url, filename, { waitFor = "networkidle", timeout = 30000 } = {}) {
    const path = resolve(OUTPUT_DIR, filename);
    console.log(`  Capturing ${filename} ... (${url})`);
    try {
      await page.goto(url, { waitUntil: waitFor, timeout });
      // Extra settle time for SPA hydration.
      await page.waitForTimeout(2000);
      await page.screenshot({ path, fullPage: true });
      console.log(`  -> saved ${filename}`);
    } catch (err) {
      console.warn(`  !! FAILED ${filename}: ${err.message}`);
      // Take a screenshot of whatever state we're in.
      try {
        await page.screenshot({ path, fullPage: true });
        console.log(`  -> saved partial ${filename}`);
      } catch {
        console.warn(`  !! Could not save even a partial screenshot for ${filename}`);
      }
    }
  }

  console.log("\n=== WikiMind Deploy Evidence Capture ===\n");

  // (a) Landing page (with cookie, may redirect to /inbox).
  await snap(`${BASE_URL}/`, "landing.png");

  // (b) Health endpoint -- rendered as raw JSON in browser.
  await snap(`${BASE_URL}/health`, "health.png");

  // (c) Deep health -- rendered as raw JSON in browser.
  await snap(`${BASE_URL}/health/deep`, "deep-health.png");

  // (d) Swagger docs.
  await snap(`${BASE_URL}/docs`, "swagger-docs.png", { timeout: 40000 });

  // (e) Inbox / Articles list -- the default authenticated view.
  await snap(`${BASE_URL}/inbox`, "articles.png");

  // (f) Wiki explorer (sources/articles list).
  await snap(`${BASE_URL}/wiki`, "sources.png");

  // (g) Knowledge graph / concepts page.
  await snap(`${BASE_URL}/graph`, "concepts.png");

  // (h) Admin dashboard.
  await snap(`${BASE_URL}/admin`, "admin.png");

  // (i) Synthesis view (compilation schemas).
  await snap(`${BASE_URL}/synthesis`, "schemas.png");

  // Bonus: settings page.
  await snap(`${BASE_URL}/settings`, "settings.png");

  // Bonus: faceted search.
  await snap(`${BASE_URL}/wiki/search`, "faceted-search.png");

  await browser.close();
  console.log("\n=== Done. Screenshots saved to docs/evidence/deploy-pipeline/ ===\n");
}

capture().catch((err) => {
  console.error("Fatal error:", err);
  process.exit(1);
});
