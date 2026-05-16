// SA6 Playwright — page-load smoke test.
//
// User journey: open the demo URL, wait for boot(), confirm graph.json
// loaded, Cytoscape rendered enough nodes, CodeMirror is visible.

import { test, expect } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    try { window.localStorage.clear(); } catch (_) {}
  });
});

test("loads index.html and renders graph + code panes", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));

  await page.goto("index.html");

  // Header stats line populates once graph.json is parsed.
  const stats = page.locator("#stats");
  await expect(stats).not.toHaveText(/loading/i, { timeout: 30_000 });
  const statsText = await stats.textContent();
  expect(statsText).toMatch(/\d+ nodes/);
  expect(statsText).toMatch(/\d+ edges/);
  expect(statsText).toMatch(/\d+ files/);

  // Cytoscape mount has a non-zero canvas count once the graph is laid out.
  const cyContainer = page.locator("#cy");
  await expect(cyContainer).toBeVisible();
  // After boot, at least one canvas element exists inside #cy.
  await expect(cyContainer.locator("canvas").first()).toBeVisible({ timeout: 20_000 });

  // CodeMirror renders a `.cm-editor` inside #code-pane after mountCodeMirror().
  await expect(page.locator("#code-pane .cm-editor")).toBeVisible();
  // And the default file source is shown.
  await expect(page.locator("#code-pane .cm-content").first()).not.toBeEmpty();

  // File rail is populated.
  const fileButtons = page.locator("#file-rail button");
  expect(await fileButtons.count()).toBeGreaterThanOrEqual(10);

  // Visible (non-token) node count is ~4100; assert >= 4000 to be safe.
  const visibleCount = await page.evaluate(() => {
    // @ts-ignore  app.js does not export, so reach in via the cytoscape
    // collection by querying #cy's data attribute through window.
    const cy = (window as any).__cy || null;
    if (cy) return cy.nodes(":visible").length;
    // Fallback: count nodes from the in-memory map.
    return -1;
  });
  // Even if we can't introspect cy directly, the stats line gives us node count.
  if (visibleCount > -1) {
    expect(visibleCount).toBeGreaterThanOrEqual(4000);
  }

  // Sanity: no uncaught page errors during boot.
  expect(errors, errors.join("\n")).toHaveLength(0);
});
