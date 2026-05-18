#!/usr/bin/env node
/**
 * Capture Playwright screenshots of the local WikiMind dev server for PR evidence.
 *
 * Usage:
 *   cd apps/web
 *   node scripts/capture-local-evidence.mjs
 *
 * Prerequisites:
 *   - API server running on :7842 (make dev-api)
 *   - Frontend running on :5174 (npx vite --port 5174)
 *   - npx playwright install chromium
 */

import { chromium } from "@playwright/test";
import { mkdirSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUTPUT_DIR = resolve(
  __dirname,
  "../../../docs/evidence/prod-dashboard-2026-05-15"
);
const BASE_URL = process.env.BASE_URL || "http://localhost:5174";

mkdirSync(OUTPUT_DIR, { recursive: true });

async function capture() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });

  const page = await context.newPage();

  // Helper: navigate and screenshot with error resilience.
  async function snap(
    url,
    filename,
    { waitFor = "networkidle", timeout = 30000 } = {}
  ) {
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
        console.warn(
          `  !! Could not save even a partial screenshot for ${filename}`
        );
      }
    }
  }

  console.log("\n=== WikiMind Local Evidence Capture ===\n");

  // 1. Inbox view
  await snap(`${BASE_URL}/inbox`, "local-01-inbox.png");

  // 2. Wiki explorer
  await snap(`${BASE_URL}/wiki`, "local-02-wiki.png");

  // 3. Settings (Docling status card)
  await snap(`${BASE_URL}/settings`, "local-03-settings.png");

  // 4. Admin dashboard (traces section)
  await snap(`${BASE_URL}/admin`, "local-04-admin.png");

  // 5. Synthesis page (suggestions)
  await snap(`${BASE_URL}/synthesis`, "local-05-synthesis.png");

  // 6. Source detail -- click first source in inbox
  console.log("  Navigating to inbox for source detail...");
  try {
    await page.goto(`${BASE_URL}/inbox`, {
      waitUntil: "networkidle",
      timeout: 30000,
    });
    await page.waitForTimeout(2000);

    // Click the first source item in the list
    const firstSource = page.locator(
      'a[href*="/sources/"], [data-testid="source-item"], .source-item, tr[class*="source"], li[class*="source"], .inbox-item, table tbody tr'
    ).first();

    if (await firstSource.isVisible({ timeout: 5000 })) {
      await firstSource.click();
      await page.waitForTimeout(2000);
      const path = resolve(OUTPUT_DIR, "local-06-source-detail.png");
      await page.screenshot({ path, fullPage: true });
      console.log("  -> saved local-06-source-detail.png");
    } else {
      // Try clicking any link that looks like a source
      const anyLink = page.locator("a").filter({ hasText: /.+/ }).first();
      if (await anyLink.isVisible({ timeout: 3000 })) {
        await anyLink.click();
        await page.waitForTimeout(2000);
      }
      const path = resolve(OUTPUT_DIR, "local-06-source-detail.png");
      await page.screenshot({ path, fullPage: true });
      console.log("  -> saved local-06-source-detail.png (fallback)");
    }
  } catch (err) {
    console.warn(`  !! FAILED source-detail: ${err.message}`);
    try {
      const path = resolve(OUTPUT_DIR, "local-06-source-detail.png");
      await page.screenshot({ path, fullPage: true });
      console.log("  -> saved partial local-06-source-detail.png");
    } catch {
      console.warn("  !! Could not capture source detail at all");
    }
  }

  await browser.close();
  console.log("\n=== Done ===\n");
  console.log(`Screenshots saved to: ${OUTPUT_DIR}`);
}

capture().catch((err) => {
  console.error("Fatal:", err);
  process.exit(1);
});
