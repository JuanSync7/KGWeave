// SA6 Playwright — use-case gallery.
//
// User journey: click "Use-case Gallery", confirm 10 cards render, click
// a "Run this" button on one card and confirm the gallery closes and the
// results panel populates with a non-zero count.

import { test, expect } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    try { window.localStorage.clear(); } catch (_) {}
  });
  await page.goto("index.html");
  await expect(page.locator("#stats")).not.toHaveText(/loading/i, { timeout: 30_000 });
});

test("gallery shows 10 family cards and runs an example", async ({ page }) => {
  await page.locator("#gallery-open").click();
  const overlay = page.locator("#gallery-overlay");
  await expect(overlay).toHaveClass(/visible/);

  const cards = page.locator(".gallery-card");
  await expect(cards).toHaveCount(10);

  // Click the first "Run this" button on the first card.
  const firstRun = page.locator(".gallery-run").first();
  await firstRun.click();

  // Gallery closes after running an example.
  await expect(overlay).not.toHaveClass(/visible/);

  // Results panel populates with at least one entry.
  await expect(page.locator("#results-list li").first()).toBeVisible({ timeout: 10_000 });
  await expect(page.locator("#results-summary")).toContainText(/\d+ nodes/);
});
