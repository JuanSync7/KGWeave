// SA6 Playwright config — drives the static demo through a real browser.
//
// The demo is pure static files under research/ast_experiment/demo/. We
// launch `python3 -m http.server 8765` rooted at `demo/` so the FE can
// fetch `../data/graph.json` from `/web/index.html` (matching the GH-Pages
// layout, where `web/` and `data/` are siblings).

import { defineConfig, devices } from "@playwright/test";

const PORT = 8765;
const HOST = "127.0.0.1";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: process.env.CI ? "line" : [["list"], ["html", { open: "never" }]],
  timeout: 60_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: `http://${HOST}:${PORT}/web/`,
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command: `python3 -m http.server ${PORT} --bind ${HOST}`,
    cwd: "..",
    url: `http://${HOST}:${PORT}/web/index.html`,
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
    stdout: "ignore",
    stderr: "pipe",
  },
});
