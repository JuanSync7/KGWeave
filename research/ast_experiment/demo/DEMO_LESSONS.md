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


