// SA6 Playwright — guided-tour stepper.
//
// User journey: click "Take the tour", confirm the overlay opens and the
// step counter advances. Confirm localStorage persists across reload.
// Confirm the "Finish" label appears on the last step.

import { test, expect } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  // NOTE: do NOT use addInitScript to clear localStorage — Playwright re-runs
  // init scripts on every page nav including page.reload(), which would wipe
  // the tour step state this suite explicitly tests for persistence.
  await page.goto("index.html");
  await page.evaluate(() => {
    try { window.localStorage.clear(); } catch (_) {}
  });
  await page.reload();
  await expect(page.locator("#stats")).not.toHaveText(/loading/i, { timeout: 30_000 });
});

test("tour opens, advances steps, and persists in localStorage", async ({ page }) => {
  await page.locator("#tour-start").click();
  const overlay = page.locator("#tour-overlay");
  await expect(overlay).toHaveClass(/visible/);

  // First step shows "Step 1 of N".
  const meta = page.locator(".tour-meta");
  await expect(meta).toContainText(/Step 1 of \d+/);

  // Pull the total step count from the meta text.
  const metaText = (await meta.textContent()) || "";
  const m = metaText.match(/Step \d+ of (\d+)/);
  expect(m).not.toBeNull();
  const total = parseInt(m![1], 10);
  expect(total).toBeGreaterThanOrEqual(12);

  // Advance once.
  await page.locator(".tour-next").click();
  await expect(meta).toContainText(/Step 2 of/);

  // localStorage should now hold step index = 1.
  const stored = await page.evaluate(() => window.localStorage.getItem("kgweave.tour.step"));
  expect(stored).toBe("1");

  // Reload — tour should resume at step 2 once we re-open (the overlay
  // closes on reload, but startTour() reads the stored index).
  await page.reload();
  await expect(page.locator("#stats")).not.toHaveText(/loading/i, { timeout: 30_000 });
  await page.locator("#tour-start").click();
  await expect(page.locator(".tour-meta")).toContainText(/Step 2 of/);

  // Jump to the last step via repeated Next clicks.
  for (let i = 2; i < total; i++) {
    await page.locator(".tour-next").click();
  }
  await expect(meta).toContainText(new RegExp(`Step ${total} of ${total}`));
  await expect(page.locator(".tour-next")).toHaveText("Finish");

  // Clicking Finish closes the overlay.
  await page.locator(".tour-next").click();
  await expect(overlay).not.toHaveClass(/visible/);
});

test("restart tour resets to step 1", async ({ page }) => {
  // Seed localStorage with a non-zero index.
  await page.evaluate(() => window.localStorage.setItem("kgweave.tour.step", "5"));
  await page.locator("#tour-restart").click();
  await expect(page.locator("#tour-overlay")).toHaveClass(/visible/);
  await expect(page.locator(".tour-meta")).toContainText(/Step 1 of/);
});
