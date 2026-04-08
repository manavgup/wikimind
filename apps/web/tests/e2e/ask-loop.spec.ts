import { test, expect } from "@playwright/test";

/**
 * The Karpathy loop closure test, end-to-end through the actual UI.
 *
 * Prerequisites:
 *   - The FastAPI backend must be running on http://localhost:7842 with
 *     at least one Article already ingested in the wiki database.
 *   - The frontend dev server is launched automatically by Playwright's
 *     webServer config in playwright.config.ts.
 *
 * If this test fails, the user-facing Ask loop is broken at some layer.
 */
test("user can ask, follow up, and save a thread to the wiki", async ({ page }) => {
  // --- Open the Ask view ---
  await page.goto("/ask");
  await expect(
    page.getByRole("heading", { name: /conversations/i }),
  ).toBeVisible();
  // Empty-state message until a question is asked
  await expect(
    page.getByText(/ask a question to start a new conversation/i),
  ).toBeVisible();

  // --- Ask the first question ---
  const input = page.getByPlaceholder(/ask a question about your wiki/i);
  await input.fill("What is the WikiMind project about?");
  await input.press("Enter");

  // The first turn card (TurnCard or PendingTurnCard) appears
  await expect(page.locator("article").first()).toBeVisible({ timeout: 30_000 });

  // Wait for the pending state to resolve into a real answer.
  // The PendingTurnCard's "Thinking…" label disappears once the real
  // TurnCard replaces it, so we wait for that transition.
  await expect(page.getByText(/thinking…/i)).toHaveCount(0, { timeout: 60_000 });

  // The new conversation appears in the sidebar
  await expect(
    page.locator("aside").getByText(/what is the wikimind project about/i),
  ).toBeVisible();

  // --- Ask a follow-up question ---
  await input.fill("How does it close the loop?");
  await input.press("Enter");

  // Two turn cards should eventually be present (Q1 + Q2 real + transient pending).
  // Playwright's toHaveCount waits for stability, and the pending card replaces
  // itself with the real card at the same DOM position, so the stable count is 2.
  await expect(page.locator("article")).toHaveCount(2, { timeout: 60_000 });
  await expect(page.getByText(/thinking…/i)).toHaveCount(0, { timeout: 60_000 });

  // --- Save the thread to the wiki ---
  const saveButton = page.getByRole("button", { name: /save thread to wiki/i });
  await expect(saveButton).toBeVisible();
  await saveButton.click();

  // Toast appears in the top-right of the main area with the expected title.
  // This is the pushToast path from AskView.tsx, NOT window.alert.
  await expect(page.getByText("Saved thread to wiki")).toBeVisible({
    timeout: 10_000,
  });

  // After save, the button label transitions to "Update wiki article"
  await expect(
    page.getByRole("button", { name: /update wiki article/i }),
  ).toBeVisible();
});
