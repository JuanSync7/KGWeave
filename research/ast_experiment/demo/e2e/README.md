# KGWeave AST demo — Playwright E2E suite (SA6)

End-to-end tests that drive the static GH-Pages demo in a real headless
Chromium browser. They cover the SPEC §6 SA6 acceptance criteria:

- page-load.spec.ts — graph.json fetch, Cytoscape mount, CodeMirror render
- graph-code-link.spec.ts — click semantic node -> inspector + code highlight
- query.spec.ts — canned + freeform DSL flows
- tour.spec.ts — stepper navigation + localStorage persistence
- gallery.spec.ts — 10 use-case cards + "Run this" dispatch
- filters.spec.ts — category/edge filter toggles

## Local run

```
cd research/ast_experiment/demo/e2e
npm install                       # one-time install of @playwright/test
npx playwright install chromium   # one-time download of the browser
npx playwright test               # runs every spec headless
npx playwright test --headed      # watch the browser drive itself
npx playwright show-report        # open the HTML report after a run
```

The Playwright config (`playwright.config.ts`) launches
`python3 -m http.server 8765` rooted at `research/ast_experiment/demo/`
so the FE's relative `../data/graph.json` fetch resolves the same way it
does in GH-Pages. `baseURL` is `http://127.0.0.1:8765/web/`.

## CI

GitHub Actions runs this suite in `.github/workflows/demo-deploy.yml`
between the Python tests and the gh-pages deploy. A failed E2E run blocks
the deploy.
