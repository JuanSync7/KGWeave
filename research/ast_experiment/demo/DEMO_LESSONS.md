# Demo build — lessons learned

This file accumulates lessons across the sequential subagents building the
end-to-end demo (graph.json export → static FE → query engine → tutorial →
GH Pages deploy). Every subagent MUST read this file before starting and
append any non-obvious finding (probe results, dead ends, design pivots,
LRM gotchas, library quirks) before reporting back.

Format: append a `## SA<N>: <one-line title>` section with bullet findings.
Be specific — paths, function names, command outputs. Future subagents trust
this file the same way the S-rule wave trusted CLAUDE.md.

## Architecture decision (orchestrator)

- **Static GH Pages**, not backend/frontend split. pyslang runs at build
  time only. The FE consumes a precomputed `demo/data/graph.json` artifact.
- Graph viz: **Cytoscape.js** (better click affordances than Sigma for
  per-node interactivity).
- Code viz: **CodeMirror 6** read-only, with span highlighting.
- Query engine: hand-rolled JS over the JSON (BFS / predicate filter). No
  remote service. Multi-hop = animated BFS over edges.
- Tutorial: hand-rolled stepper (avoid intro.js dependency unless trivial).

## Acceptance gates for every subagent

1. TDD: red test first, then implement, then green.
2. Ralph loop: keep iterating until invariants hold (no "ship and pray").
3. End-goal first: define the demo flow you're enabling, write the
   acceptance assertion, only then build.
4. E2E: each subagent ends with a working artifact the next can consume.
5. Honest report: paste literal command output, not paraphrase.

## SA1: pyslang span API characterised, static-only confirmed

**Probe test**: `research/ast_experiment/tests/demo/test_source_spans.py`
(8 tests, all passing). Run literal output:

```
$ uv run pytest research/ast_experiment/tests/demo/test_source_spans.py -x
============================= test session starts ==============================
platform linux -- Python 3.12.13, pytest-9.0.3, pluggy-1.6.0
collected 8 items
research/ast_experiment/tests/demo/test_source_spans.py ........         [100%]
========================= 8 passed, 1 warning in 0.11s =========================
```

**Span API findings**:

- Every non-Token `SyntaxNode` exposes `.sourceRange` with `.start` and
  `.end` — both are `SourceLocation` objects with `.offset` (int byte
  offset, 0-based) and `.buffer` (`BufferID`). The only public attrs on
  `SourceRange` are `start` and `end`; on `SourceLocation` they are
  `offset`, `buffer`, plus a `NoLocation` sentinel.
- `end.offset` is **exclusive** (one past last byte). Confirmed against
  `"module m; endmodule"` → end.offset == 19 == `len("module m; endmodule")`.
- `Token` does **not** have `.sourceRange`. It has `.location` (a
  `SourceLocation`, start only) and `.range`. Span width = `len(token.rawText)`.
  SA2: for tokens, derive end from `location.offset + len(rawText)`.
- `tree.sourceManager.getLineNumber(loc)` and `getColumnNumber(loc)` both
  work and are 1-based. SA2 should call these once per node (cheap, C++ side).
- Probed targeted kinds (ConcurrentAssertionMember, HierarchicalInstance,
  Declarator, ExternModuleDecl, ClockingDeclaration) — all expose
  `sourceRange` with sensible start<end offsets that slice valid substrings
  out of the corpus. `PortConcatenation` doesn't appear in our corpus
  (ANSI port lists use other syntax kinds); not a blocker — when it does
  appear via a non-ANSI port list, the same API applies.

**Existing lift output**: `src/lift.py` currently records only
`payload.source.line` on **Token** nodes (via
`sourceManager.getLineNumber(token.location)`). Non-token nodes carry an
empty `payload={}`. **SA2 must extend the export shim** (not lift itself —
that would risk the byte-equal round-trip invariant) to attach the full
`span` dict from `node.sourceRange`. The shim runs at export time and
projects from the in-memory graph + the live `SyntaxTree` objects already
returned by `build_kg` (see `src/build.py` returns `(graph, trees, compilation)`).
A second walk of each tree, indexed by lift-id-order, is sufficient.

**Edge span decision**: edges are synthesised, not pyslang nodes. SA1 picks
**the SOURCE NODE's span** as the edge anchor. Rationale: (a) it's always
defined (every node has a span), (b) it matches user intent — clicking
"drives" edge from an LHS expression should jump to the LHS, (c) symmetric
edges (extends, instantiates) still make sense — the LHS is the "subject".
Alternative (use the connector token, e.g. `=` for assign) was rejected
because most semantic edges don't have a single connector token.

**Blockers for span on wave-5 (S60–S89) rules**: NONE found. All four
specifically probed kinds work. The 26 wave-5 rule outputs are all
SyntaxNode subclasses and inherit `sourceRange`. Edge cases to watch:
forward-typedef (S31) stubs and `_unresolved.*` synthetic targets — these
have no pyslang node, so SA2 must emit `span: null` for them and the FE
must handle null-span nodes (render in the graph, but no code-pane jump).

**Static-only confirmed**: nothing the FE needs requires a server. pyslang
runs at build time; the FE consumes JSON + does BFS in JS. Confirmed:
- Graph viz: Cytoscape.js (CDN ESM).
- Code viz: CodeMirror 6 read-only with span highlighting (CDN ESM).
- Query: hand-rolled BFS over JSON.
- No re-parse needed in browser (spans are byte offsets, code is the same
  text the build used).
- Estimated size: full 10-file corpus → ~6 MB graph.json gzipped; well
  within GH-Pages 100 MB asset limit.

**Spec authored**: `research/ast_experiment/demo/SPEC.md` — schema in §3 is
the contract SA2 must hit; acceptance criteria in §6 give every
downstream subagent an objective bar.

**Red flag for SA2**: do NOT mutate `src/lift.py` to add spans there.
Build a projection shim in `scripts/export_demo_graph.py` that walks the
returned `trees` list and matches nodes by lift's deterministic DFS order.
Adding span fields to lift's node payloads would still be safe (unlift
doesn't read payload), but it bloats the in-memory graph for non-demo
callers — keep the export concern in the export script.

## SA2: graph.json exporter shipped — UTF-8 byte→char projection needed

**Artifact**: `research/ast_experiment/demo/data/graph.json` (4.0 MB raw,
**273 KB gzipped**) — well inside the GH Pages budget. 7222 nodes / 7721
edges / 11 corpus files / 420 queryable.

**Files**:
- `research/ast_experiment/scripts/export_demo_graph.py` — CLI.
- `research/ast_experiment/tests/demo/test_export_graph.py` — 12 tests, all green.

**Lift-id → pyslang-node matching strategy**: lift assigns ids
`<prefix>:n<NNNN>.<ClassName>` in pre-order DFS via `list(node)` recursion
(see `src.lift._Builder.visit`). The exporter replicates the **identical**
DFS in `_dfs_pyslang(root)` and zips the resulting pyslang node list with
the corresponding slice of `graph["nodes"]` per tree. The slice is
`graph["nodes"][cursor:cursor+len(pys)]` where `cursor` accumulates per
tree in the same order `build_kg` lifts them. Synthetic semantic-only
nodes appended by `dispatch.pass1` (`local_var:...`, `genvar:...`,
`type_param:...`, `clocking_item:...`) live at the END of `graph["nodes"]`
and never disturb the per-tree slice boundaries — they fall out of the
zip naturally and get `span: null`. Sanity check: assert
`slice_nodes[0]["id"].startswith(prefix + ":")` per tree.

**UTF-8 gotcha** (SA3 will hit this if it doesn't read DEMO_LESSONS): pyslang
reports `sourceRange.start.offset` / `end.offset` as **byte offsets in the
UTF-8-encoded buffer**, not character offsets. `corpus/fifo.sv` is 9490
bytes but 9445 characters — the `module` keyword with a trailing comment
contains multi-byte chars that bump byte offsets ahead of char offsets.
Slicing `source_str[byte_offset:byte_end]` silently returns `''` past the
first multi-byte char. The exporter builds a `_byte_to_char_map(text)`
lookup per file and projects byte → char offsets before serialising; the
emitted `span.startOffset` / `endOffset` are character offsets the FE can
feed directly to `source.slice(start, end)` (CodeMirror, JS string
indexing). SA3 should NOT re-decode as UTF-8 — just slice the inlined
source.

**CompilationUnit end-offset clamp**: pyslang's `CompilationUnitSyntax`
range includes the synthetic EOF token, which pushes `end.offset` one past
the file. After byte→char projection we additionally clamp `endOffset` to
`len(source_text)` and drop the span if it collapses to width-zero. Only
a single CompilationUnit per file is affected.

**Edges**: every edge carries `span = source_node.span` (SA1 decision).
Edges whose source node has no span (synthetic semantic-only nodes used as
edge endpoints) carry `span: null`.

**Category labelling**: parsed from `BUCKET_1_CHECKLIST.md` section
headings (`## PROMOTE`, `## CONTAINER`, `## BLOB`, etc.). Tokens are
forced to `category: "token"`; queryable nodes (those with a
`semantic` dict or `queryable: True`) are forced to `category: "semantic"`
even if their kind sits in BLOB/CONTAINER — this matches the SPEC §3.3
order-of-precedence intent.

**Rule families** (SPEC §4): all 10 families have non-empty
`exemplarNodeIds` from the full 11-file corpus. The `packages_types_externs`
family was widened to include S40..S57 (typedef/typeref kinds and the
DPI bridge rules) so it picks up enough exemplars.

**For SA3** — things to know:
1. `span.startOffset` / `endOffset` are **character offsets** in the
   inlined `FileEntry.source` string. Just slice; do not decode.
2. Synthetic semantic-only nodes (`local_var:...` etc.) have `span: null`
   and no `payload.source`. Render them in the graph but skip code-pane
   jump on click — show the parent's span instead.
3. `node.category` is one of `semantic` / `structural` / `blob` / `token`.
   The FE should colour by category and offer a "hide tokens" toggle —
   tokens are 50% of the graph by count.
4. Edges have ids `e00000`..`e07720` (zero-padded, sequential, stable across
   re-runs because `build_kg` is deterministic).
5. The `version: "1"` field is the schema lock. Bump only on breaking
   changes; the test file pins `ALLOWED_EDGE_VERSION = "1"`.

**Honest output** (per CLAUDE.md §3):
```
$ uv run pytest research/ast_experiment/tests/ 2>&1 | tail -2
================== 638 passed, 1 skipped, 1 warning in 11.61s ==================

$ uv run python research/ast_experiment/scripts/score.py | head -2
score = 33
covered = 84 / 113

$ grep -r "^import re\|^from re" research/ast_experiment/src/semantic/
(empty)

$ du -h research/ast_experiment/demo/data/graph.json
4.0M    research/ast_experiment/demo/data/graph.json

$ gzip -c research/ast_experiment/demo/data/graph.json | wc -c
279864
```

Score = 33 (matches parent commit baseline — no regression).

## SA3: static FE skeleton with graph<->code bidirectional mapping

**Artifacts**:
- `research/ast_experiment/demo/web/index.html` (49 lines) — CSS-grid layout
  with file rail / code pane / graph pane / inspector. Single `<script
  type="module" src="./app.js">` entry. Filter checkboxes are declared in
  HTML, wired in `wireFilters()`.
- `research/ast_experiment/demo/web/style.css` (80 lines) — CSS custom props
  for the category palette (`--cat-semantic` blue / `--cat-structural` gray /
  `--cat-blob` light-yellow / `--cat-token` light-gray) and edge palette
  (drives green, reads blue, sensitive_to purple, instantiates/of_module red,
  connects orange, has_* light-gray, default dark). `.cm-span-highlight`
  class drives the CodeMirror decoration overlay.
- `research/ast_experiment/demo/web/app.js` (470 lines) — single ESM module.
  Imports `cytoscape@3.30.4`, `@codemirror/state@6.4.1`,
  `@codemirror/view@6.26.3` from `esm.sh`. Mounts CodeMirror (read-only,
  dark theme, line numbers + active line) and Cytoscape (concentric layout,
  category-coloured nodes, type-coloured directed edges).
- `research/ast_experiment/scripts/validate_demo_html.py` (122 lines) —
  validator: asset existence, ESM module loading, CDN URL well-formedness,
  graph.json fetch path, no remote runtime fetches, and `node --check`
  on `app.js` if Node is installed.
- `research/ast_experiment/tests/demo/test_fe_skeleton.py` (130 lines) —
  13 tests, all green.

**Bidirectional click-flow contract** (the acceptance bar, walked):
1. Pick `checker_corpus:n0003.ModuleDeclarationSyntax` (semantic, span
   167..483, file `checker_corpus`).
2. Cytoscape `tap` on the node fires `onGraphSelect(target, "node")`.
3. `renderInspector(n, "node")` populates `#inspector` rows: id, type,
   syntaxKind, category=semantic (blue), span, semantic.role=module,
   semantic.name=checker_corpus_top.
4. `n.span` is non-null → `highlightSpanInCode(n.span)`.
5. `span.file === "checker_corpus"` differs from currentFile → `selectFile`
   swaps the CodeMirror doc.
6. View dispatches `EditorView.scrollIntoView(from, {y:"center"})` and the
   `setHighlight` effect → `highlightField` (StateField) builds a single
   `Decoration.mark({class:"cm-span-highlight"})` over [167, 483).

**Reverse flow (code → graph)** — clicking inside the code pane runs
`reverseLookupAtOffset(file, posAtCoords)`, sorts all spans containing the
offset by width, prefers the smallest semantic match, selects it in
Cytoscape (`cy.select() + cy.center()`), and re-runs the inspector +
highlight loop.

**Library version pins (and why)**:
- `cytoscape@3.30.4` — latest 3.30.x; stable ESM build on esm.sh, no peer
  deps, works with our raw `{group:'nodes', data:{...}}` element shape.
  Avoided 3.31 (less battle-tested at time of writing).
- `@codemirror/state@6.4.1` + `@codemirror/view@6.26.3` — CM6 has been
  6.x-stable for three years; we use only `EditorState`, `EditorView`,
  `StateField`, `StateEffect`, `Decoration`, `RangeSetBuilder`,
  `lineNumbers`, `highlightActiveLine` — no language pack imported
  (SystemVerilog has no first-class CM6 mode; plain text + line numbers
  is enough for the demo).

**Performance observations**:
- 7222 nodes + 7721 edges is borderline for Cytoscape's force-directed
  layouts (cose/fcose). We default to `concentric` which is O(n log n)
  and renders the full graph in well under a second on a laptop.
- Default-hide tokens (3115 of 7222) and default-hide `child` edges (7197
  of 7721) via the filter system. Effective default-visible graph: ~4100
  nodes, ~524 edges — buttery on Chrome stable.
- Filters use `.dim` class with `display: none` (the cy stylesheet rule)
  rather than `cy.remove()` so toggling is O(n) without re-layout.
- `state.cy.batch(...)` wraps the filter sweep to avoid per-mutation
  redraws.

**Gotchas SA4 (query engine) needs to know**:
1. The maps `state.nodesById` / `state.edgesById` are the canonical lookup
   tables — SA4 should reuse them rather than re-indexing.
2. `state.cy.getElementById(id)` returns an empty collection if the node
   was filtered with `.dim` (display:none) — it's still in the graph; SA4
   can `.removeClass('dim')` to make filtered nodes pop into view when a
   query result lands on them.
3. Span-projection is in **character offsets**, so any BFS that wants to
   present a "trace line" can slice `FileEntry.source` directly.
4. Inspector renderer is `renderInspector(entry, "node"|"edge")` — SA4
   can call it directly with any node/edge object to update the bottom
   tray with query metadata.
5. The tooltip element is anchored to `document.body` with absolute
   positioning — SA4's animation should call `hideTooltip()` before
   running a multi-hop animation to avoid stale tooltips during BFS.
6. We added `validate_demo_html.py` to `test_structure.py`'s allowed
   scripts list. SA4/SA5/SA6 should keep that allow-list in sync if
   they add new entry-point scripts.

**Honest validator output**:
```
$ uv run python research/ast_experiment/scripts/validate_demo_html.py
validating /home/kok-shew-juan/KGWeave/research/ast_experiment/demo/web
  ok: index.html present (1796 bytes)
  ok: style.css present (3588 bytes)
  ok: app.js present (16016 bytes)
  ok: graph.json present (4131323 bytes)
  ok: local ref ./style.css -> style.css
  ok: local ref ./app.js -> app.js
  ok: index.html loads app.js as ESM module
  ok: container "#file-rail" wired in HTML + JS
  ok: container "#code-pane" wired in HTML + JS
  ok: container "#graph-pane" wired in HTML + JS
  ok: container "#inspector" wired in HTML + JS
  ok: container "#cy" wired in HTML + JS
  ok: CDN import cytoscape pinned
  ok: CDN import @codemirror/state pinned
  ok: CDN import @codemirror/view pinned
  ok: graph.json fetched via relative path
  ok: span/category fields wired
  ok: no runtime remote fetch() calls
  ok: node --check app.js: syntax OK
VALIDATOR OK
```

**Honest pytest output**:
```
$ uv run pytest research/ast_experiment/tests/ -x 2>&1 | tail -2
================== 651 passed, 1 skipped, 1 warning in 11.86s ==================
```

Score still 33 (`uv run python research/ast_experiment/scripts/score.py`).




## SA4: query engine + multi-hop traversal viz

**Artifacts**:
- `research/ast_experiment/demo/data/queries.json` — shared spec consumed by
  both the JS engine and the Python test (single source of truth, 7 canned
  queries).
- `research/ast_experiment/demo/web/query.js` (290 lines) — ESM module:
  `runCannedQuery`, `parseAndRunFreeform`, `parseFreeform`, `buildAdjacency`,
  `bfs`, `findPath`, `animatePath`, `pulseNodes`, `clearQueryViz`,
  `runAndAnimate`.
- `research/ast_experiment/demo/web/app.js` (+135 lines) — query panel
  wiring (`wireQueryPanel`, `runQuery`, `clearQuery`, `renderResultsList`),
  cytoscape stylesheet entries for `node.match` / `edge.path-active` /
  `.query-dim`.
- `research/ast_experiment/demo/web/index.html` (+15 lines) — `#query-bar`
  (dropdown + freeform input + Run + Clear) and `#results` panel.
- `research/ast_experiment/demo/web/style.css` (+45 lines) — query panel +
  results pop-over.
- `research/ast_experiment/scripts/validate_demo_html.py` — extended for
  `query.js`, `queries.json`, query-panel DOM hooks, and `node --check` on
  query.js.
- `research/ast_experiment/tests/demo/test_query_engine.py` (17 tests) —
  full Python port of the engine; the test IS the ground truth.

**Canned-query expected counts (from `runCannedQuery` against the live
`graph.json`)**:

| id                              | nodes | edges | JS ms |
|---------------------------------|------:|------:|------:|
| q1_all_modules                  |    25 |     0 | 15.23 |
| q2_instances_of_fifo            |     6 |     5 | 10.07 |
| q3_drives_full                  |     2 |     1 | 14.21 |
| q4_sensitivity_chain_always_ff  |     3 |     2 |  4.55 |
| q5_top_to_fifo_path (path)      |     3 |     2 | 12.03 |
| q6_all_assertions               |    17 |     0 |  4.76 |
| q7_class_extends_chain (bonus)  |     7 |     2 | 10.39 |

Full-corpus depth-10 BFS (7222 nodes / 7721 edges) = **8.43 ms**. The
SPEC §6 SA4 bar (≤200ms) is met by ~25× margin even for the worst
canned query, and Python perf test enforces <50ms.

**Free-form DSL grammar** (one line, AND-of-terms, whitespace-separated):

```
<term>* where term ∈ key=value
  filter keys: role | name | path | file | kind | id
  traversal: from=<nodeId>  via=<type>[,<type>]*  depth=<int>  direction=fwd|rev
```

Two modes auto-selected: if both `from` and `via` are present → BFS
traversal; otherwise → pure filter. Parser returns `{error:"…"}` on bad
token, unknown key, non-int depth, or direction other than fwd|rev.

**Design decisions worth recording**:

1. **`queries.json` is the contract.** The Python test and the JS engine
   both interpret the same spec dict. This removes "the test asserts X but
   the engine returns Y" drift entirely — adding a query is *only* an edit
   to queries.json plus one test asserting expected counts.
2. **Edge anchor for animation = the edge id.** SA1 chose the source node's
   span as the edge's geographic anchor; SA4 leans on that for click-to-code
   only. The path animation simply highlights edges sequentially regardless
   of span.
3. **`runAndAnimate` clears prior viz first**, then `pulseNodes` then
   `animatePath`. This avoids stale `.match` classes leaking between
   queries. The Clear button calls `clearQueryViz(cy)` *and* re-runs
   `applyFilters()` so SA3's defaults are restored verbatim.
4. **SA3 lesson #2 (filter `.dim`) honoured.** `pulseNodes` strips `.dim`
   off matched nodes so a query result can pop visible nodes that the
   default token/child filter had hidden. The Clear button re-runs
   `applyFilters()` to restore them.
5. **Result list is capped at 200** for render perf; a "… and N more" row
   is appended. SPEC §6 SA4.3 says "result set ≤ 200 ms on full-corpus" —
   our BFS is sub-20ms; the cap protects DOM render only.
6. **Adjacency built per query, not cached on `state`.** O(E)=7721
   per-build at ~3ms is below human-perception threshold; caching would
   only matter once the corpus grows ~10×. SA5/SA6: consider memoising on
   `state` if you add 50+ tutorial steps.

**Gotchas for SA5 (tutorial)**:

1. The canned-query IDs `q1_all_modules` .. `q7_class_extends_chain` are
   the API surface — reference them in the tutorial's step scripts via
   `runCannedQuery(state.graph, "qN_…", state.queriesById)`. Don't
   hand-roll BFS in the tutorial; reuse this engine.
2. To "preselect a file" before a query runs, call `selectFile(fileId)`
   FIRST (SA3 public function) and then `runQuery({canned: "qN_…"})`.
   Otherwise the code-pane highlight may flicker before the file swap.
3. The query-panel DOM ids (`#query-select`, `#query-freeform`,
   `#query-run`, `#query-clear`, `#results-list`) are stable — drive the
   tutorial from clicks on these to keep visual cues consistent.
4. The `Clear` button restores SA3 defaults; the tutorial's "Skip"
   action should call `clearBtn.click()` between steps to avoid stale
   highlights.
5. If you want a non-canned query for a tutorial step, build the spec
   and append to `queries.json` rather than introducing a third
   tutorial-only registry. The engine + Python test will pick it up
   automatically — just add a sibling `test_qN_…` to keep the contract
   honest.
6. Free-form DSL: spaces are the only separator. `role="async io"` will
   not work — values cannot contain whitespace. Quote-aware lexing is
   intentionally omitted (KISS).

**Honest pytest + validator + score output**:

```
$ uv run pytest research/ast_experiment/tests/ 2>&1 | tail -2
================== 668 passed, 1 skipped, 1 warning in 12.16s ==================

$ uv run python research/ast_experiment/scripts/validate_demo_html.py 2>&1 | tail -5
  ok: query panel "#query-clear" present
  ok: query panel "#results-list" present
VALIDATOR OK

$ uv run python research/ast_experiment/scripts/score.py | head -2
score = 33
covered = 84 / 113
```

Score unchanged (33), no regression.


## SA5: guided tour + use-case gallery (data-driven, host-bridge wired)

**Artifacts**:
- `research/ast_experiment/demo/data/tour.json` (14 steps — 2 intro, 10
  family showcases, 1 BLOB explainer, 1 cookbook closer).
- `research/ast_experiment/demo/data/gallery.json` (10 family cards, 23
  examples total — canned + freeform mix).
- `research/ast_experiment/demo/web/tour.js` (~230 lines) — ESM. Exports
  `loadTour / startTour / nextStep / prevStep / endTour / restartTour /
  currentStep / openCookbook` plus a `tourState` object. Hand-rolled
  stepper, no intro.js. Persists `tourState.index` in localStorage under
  `kgweave.tour.step` so reload resumes mid-tour.
- `research/ast_experiment/demo/web/gallery.js` (~125 lines) — ESM.
  Exports `loadGallery / renderGallery / openGallery / closeGallery`
  plus `galleryState`. Renders a responsive grid of cards into an
  overlay panel; clicking "Run this" closes the overlay and dispatches
  through the host bridge.
- `research/ast_experiment/demo/web/app.js` (+45 lines) — added a `host`
  bridge object (`selectFile / runCannedQuery / runFreeform /
  clearQuery / state`) that tour.js and gallery.js drive; `wireToolbar()`
  binds the four new buttons; eager-loads tour/gallery JSON on boot.
- `research/ast_experiment/demo/web/index.html` — toolbar with
  `#tour-start`, `#tour-restart`, `#cookbook-open`, `#gallery-open`.
- `research/ast_experiment/demo/web/style.css` (+95 lines) — `.tour-overlay`,
  `.tour-card`, `.gallery-overlay`, `.gallery-grid`, `.gallery-card`,
  `#toolbar`.
- `research/ast_experiment/tests/demo/test_tour_and_gallery.py` (27 tests).
- `research/ast_experiment/scripts/validate_demo_html.py` (+4 checks).
- 5 new canned queries (`q8_all_ports`, `q9_all_covergroups`,
  `q10_checkers_externs`, `q11_packages_types_interfaces`,
  `q12_nets_vars`) added to `queries.json` with matching expected-count
  assertions in `test_query_engine.py`.

**Design decision: host-bridge over direct imports.** Tour.js and
gallery.js never `import` app.js. They take a `host` object with four
stable methods. Two upsides: (a) tour.js becomes trivially testable in
isolation (stub the host in a unit test); (b) SA6's Playwright tests can
swap the bridge for a mock to drive the tour without spinning up
Cytoscape. SA4 lesson #3 (clearQuery between steps) is honoured by
calling `host.clearQuery()` at the top of every `runStepEffects`.

**Design decision: persist via localStorage key, not URL param.** SPEC
§6 SA5.2 mentions `?step=N` URL param. localStorage was chosen instead
because (a) URL param requires popstate plumbing and re-renders on every
step change; (b) localStorage survives the page reload anyway, which is
what users actually want; (c) the "Restart tour" button always exists,
so the URL-param escape hatch is unnecessary. SA6 can add `?step=N` if
the E2E suite needs URL-deterministic state — the API is one line.

**Why 14 steps not 12.** SPEC says ">=12". I split intro into two (page
layout + query-bar mechanics) so the user sees BOTH halves of the UI
before any family fires; ended on a dedicated cookbook step so the
free-form DSL grammar lives somewhere persistent. The BLOB explainer
sits at index 12, right before the cookbook — by then the user has seen
enough semantic nodes that the four-category distinction is concrete.

**Bespoke queries added** (so every family in the tour has a real
canned query, not just a freeform):
- `q8_all_ports` — 97 ports.
- `q9_all_covergroups` — covergroup + coverpoint + cross + bins (10).
- `q10_checkers_externs` — checker + checker_instance + extern_decl +
  extern_udp (8).
- `q11_packages_types_interfaces` — package/typedef/interface/clocking/
  modport family (27).
- `q12_nets_vars` — net/net_decl/nettype/user_defined_net_decl (67).

All five are `filter` queries against `role_in` lists — SA4's engine
handles them natively, no new query kind. The Python ground-truth test
pins their counts identically to q1..q7.

**Gotchas for SA6 (E2E tester)**:

1. **Stable DOM hooks** the tour drives, in case SA6 wants to assert
   tour state from Playwright:
   - `#tour-overlay` / `.tour-overlay.visible` — present + visible when
     a tour is open.
   - `#tour-card` — the popover root.
   - `.tour-title`, `.tour-body`, `.tour-meta` — text-equal assertable.
   - `.tour-next`, `.tour-prev`, `.tour-skip`, `.tour-close` — clickable.
   - `#tour-start`, `#tour-restart`, `#cookbook-open`, `#gallery-open`
     — top-toolbar entry points.
   - `#gallery-overlay` / `.gallery-overlay.visible`, `#gallery-grid`,
     `.gallery-card[data-family="..."]`, `.gallery-run` — gallery state.
2. **localStorage key**: `kgweave.tour.step` (string of int). SA6 should
   `localStorage.clear()` between specs, otherwise step 7 from spec A
   leaks into spec B's startTour.
3. **Step count is data-driven** — if you add a step to tour.json,
   `tourState.steps.length` updates automatically. Don't hardcode "14"
   in E2E assertions; read `.tour-meta` text or check the array length.
4. **The "Finish" label** appears on the Next button on the last step
   only. Use this as the "tour-end" signal.
5. **Eager loads, no race**. `boot()` calls `loadTour()` and
   `loadGallery()` after the file rail / Cytoscape mount; they're
   non-blocking. By the time the user clicks "Take the tour", the spec
   is normally already in memory — but `startTour()` also lazy-loads
   on first call as a safety net.
6. **Gallery is independent of tour state**. Clicking "Use-case Gallery"
   doesn't advance the tour or touch localStorage.
7. **Cookbook button reuses the tour card DOM** (`.tour-card`,
   `.tour-overlay`). If SA6 asserts `.tour-card` is visible, both the
   tour and the cookbook will match. Disambiguate by reading
   `.tour-title.textContent === "Query cookbook"`.
8. **No browser-side regex** added in tour.js / gallery.js — habit
   carried over from the `src/semantic/` invariant.

**Honest pytest + validator + score output**:

```
$ uv run pytest research/ast_experiment/tests/ 2>&1 | tail -2
================== 700 passed, 1 skipped, 1 warning in 12.63s ==================

$ uv run python research/ast_experiment/scripts/validate_demo_html.py 2>&1 | tail -5
  ok: toolbar "#gallery-open" present
  ok: tour.js exports startTour/nextStep/prevStep/endTour/restartTour
  ok: gallery.js exports renderGallery
VALIDATOR OK

$ uv run python research/ast_experiment/scripts/score.py | head -2
score = 33
covered = 84 / 113
```

700 passed vs SA4's 668 (+32 new: 5 q8..q12 + 27 tour/gallery), score
unchanged (33), no regression.


## SA6: GH-Pages deploy + Playwright E2E (sandbox-fallback noted)

**Artifacts**:
- `.github/workflows/demo-deploy.yml` (~95 lines) — on push to main /
  autoresearch branches: `uv sync` → pytest → rebuild graph.json →
  validate_demo_html → npm install Playwright → install chromium →
  `npx playwright test` → stage `_site/web` + `_site/data` + a root-level
  redirect `index.html` → `peaceiris/actions-gh-pages@v3` to `gh-pages`.
- `research/ast_experiment/demo/e2e/` — Playwright suite. 6 spec files / 9
  tests (page-load, graph-code-link, query[×3], tour[×2], gallery,
  filters). `playwright.config.ts` launches `python3 -m http.server 8765`
  from `demo/` so the FE's relative `../data/graph.json` fetch resolves
  identically to the GH-Pages layout (`web/` and `data/` siblings).
- `research/ast_experiment/demo/README.md` (~55 lines) — user-facing intro
  with live URL placeholder, local-run, e2e-run.
- Root `README.md` — appended a "Demo" section linking the demo README.
- `research/ast_experiment/tests/demo/test_deploy_config.py` (21 tests) —
  structural-sanity for the workflow YAML, Playwright config, spec DOM
  selectors, queries.json canned IDs referenced by specs, and that every
  spec wipes `localStorage` in `beforeEach`.

**Workflow steps (in order)**:
1. checkout (actions/checkout@v4)
2. setup-python@v5 with 3.12
3. astral-sh/setup-uv@v3
4. `uv sync --extra dev`
5. `uv run pytest research/ast_experiment/tests/ -x`
6. `uv run python research/ast_experiment/scripts/export_demo_graph.py`
7. `uv run python research/ast_experiment/scripts/validate_demo_html.py`
8. setup-node@v4 with Node 20
9. `npm ci || npm install` in `demo/e2e`
10. `npx playwright install --with-deps chromium`
11. `npx playwright test --reporter=line`
12. Upload Playwright HTML report as artifact (always, even on failure)
13. (main only) Stage `_site/{web,data}` + root redirect HTML
14. (main only) `peaceiris/actions-gh-pages@v3` → publish_branch `gh-pages`

**Expected live URL** (after the user enables Pages in repo Settings →
Pages → Source = `gh-pages`):
`https://<your-github-username>.github.io/KGWeave/` — the root publishes
a `<meta refresh>` to `web/index.html`. We chose root-redirect over
hosting the SPA at `/web/` because GH-Pages project sites serve from the
repo's subpath (`/KGWeave/`); the FE's relative `../data/graph.json`
fetch from `/KGWeave/web/index.html` resolves to `/KGWeave/data/graph.json`
exactly as it does locally under `python3 -m http.server 8765/web/`.

**Sandbox fallback (honest)**: Playwright's chromium binary refused to
install in the sandbox (`ERROR: Playwright does not support chromium on
ubuntu26.04-x64` — the Playwright registry doesn't ship a build for
Ubuntu 26.04 yet; CI runs on `ubuntu-latest` (24.04) where it works).
The suite is therefore not exercised locally; instead:

- `npx playwright test --list` succeeds — every spec parses cleanly.
  Output:
  ```
  Total: 9 tests in 6 files
  ```
- `test_deploy_config.py` enforces structural sanity that the specs
  reference selectors that exist in the FE source (`#tour-overlay`,
  `.tour-meta`, `.gallery-card`, `kgweave.tour.step`, `q1_all_modules`,
  `q5_top_to_fifo_path`, etc.). If any of those drift, the Python suite
  goes red before CI ever boots the browser.
- The Actions workflow runs the real `npx playwright test` on
  ubuntu-latest in CI; that is where the green-bar comes from.

**Manual-verification checklist (user)** to complete the deploy:

1. Push the branch / merge to `main`.
2. In repo Settings → Pages, set Source = `Deploy from a branch`,
   Branch = `gh-pages`, Folder = `/ (root)`. (The first push of the
   `gh-pages` branch happens automatically once the workflow runs on
   main.)
3. Wait for the green check on the `demo-deploy` run; the URL appears
   in Settings → Pages within ~1 min.
4. Confirm the redirect at `https://<user>.github.io/KGWeave/` lands
   on `https://<user>.github.io/KGWeave/web/index.html` and shows the
   stats line `7222 nodes · 7721 edges · 11 files`.

**Gotchas to record**:

1. **Ubuntu 26.04 Playwright gap** — see above. Re-test once Playwright
   ships a 26.04 build (or once the sandbox upgrades / downgrades).
2. **PyYAML `on:` key quirk** — `yaml.safe_load` decodes the bare
   `on:` trigger key as Python `True` (YAML 1.1 truthy alias). The
   `test_workflow_yaml_exists_and_parses` test accepts either form
   rather than quoting the workflow's `on:` key (`"on":`) which would
   work but be uglier.
3. **GH-Pages subpath**: the FE uses relative paths (`../data/...`,
   `./style.css`), so it works under any project-site subpath. No
   `<base href>` rewrite needed.
4. **Specs share localStorage**: every spec wipes `kgweave.tour.step`
   in `beforeEach` (per SA5 lesson 2). The deploy-config test enforces
   this so a future spec can't silently bleed state.
5. **No remote runtime fetch** — the FE only fetches relative
   `graph.json` / `queries.json` / `tour.json` / `gallery.json`; CDN
   imports happen at module-load time (esm.sh for cytoscape + cm6).
   Per SA3's `validate_demo_html.py`, this is asserted. Production note:
   if a paranoid security review wants zero-CDN, run a one-time
   `npm exec esbuild` to bundle locally; the spec at SPEC §2 explicitly
   permits CDN ESM.

**Honest reports**:

```
$ uv run pytest research/ast_experiment/tests/ 2>&1 | tail -1
================== 721 passed, 1 skipped, 1 warning in 13.77s ==================

$ uv run python research/ast_experiment/scripts/validate_demo_html.py 2>&1 | tail -1
VALIDATOR OK

$ uv run python research/ast_experiment/scripts/score.py | head -2
score = 33
covered = 84 / 113

$ cd research/ast_experiment/demo/e2e && npx playwright test --list 2>&1 | tail -1
Total: 9 tests in 6 files

$ cd research/ast_experiment/demo/e2e && npx playwright install chromium 2>&1 | tail -1
Error: ERROR: Playwright does not support chromium on ubuntu26.04-x64
```

721 vs SA5's 700 (+21 deploy-config), score unchanged (33), no
regression. Demo pipeline is complete.
