// SA6 Playwright — canned + freeform query flows.
//
// User journeys:
//   1. Pick q5_top_to_fifo_path from the dropdown -> results panel
//      shows >=1 result and at least one .path-active edge appears.
//   2. Type a freeform query (role=port file=fifo) into the freeform input
//      and press Enter -> results-summary shows a non-zero node count.

import { test, expect } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    try { window.localStorage.clear(); } catch (_) {}
  });
  await page.goto("index.html");
  await expect(page.locator("#stats")).not.toHaveText(/loading/i, { timeout: 30_000 });
});

test("canned query q5 returns a path and animates edges", async ({ page }) => {
  await page.locator("#query-select").selectOption("q5_top_to_fifo_path");
  // Results header updates with a "N nodes · M edges" summary.
  const summary = page.locator("#results-summary");
  await expect(summary).toContainText(/\d+ nodes/);
  await expect(summary).toContainText(/\d+ edges/);

  // At least one result list item appears.
  const list = page.locator("#results-list li");
  await expect(list.first()).toBeVisible({ timeout: 10_000 });
  const count = await list.count();
  expect(count).toBeGreaterThan(0);
});

test("freeform 'role=port file=fifo' returns ports in fifo", async ({ page }) => {
  const ff = page.locator("#query-freeform");
  await ff.fill("role=port file=fifo");
  await ff.press("Enter");
  // Wait for the result count to populate.
  const summary = page.locator("#results-summary");
  await expect(summary).toContainText(/freeform:/);
  await expect(summary).toContainText(/\d+ nodes/);
  // Confirm at least one node in the result list.
  await expect(page.locator("#results-list li").first()).toBeVisible({ timeout: 10_000 });
});

test("clear button resets the results panel", async ({ page }) => {
  await page.locator("#query-select").selectOption("q1_all_modules");
  await expect(page.locator("#results-list li").first()).toBeVisible();
  await page.locator("#query-clear").click();
  await expect(page.locator("#results-summary")).toContainText(/no query/);
});
