# Demo specification — pyslang AST static GH-Pages site

Authored by SA1. Locked spec for SA2–SA6.

This document specifies the static GitHub-Pages demo of the pyslang
semantic+BLOB knowledge graph. It is the single source of truth for the
downstream subagents — they must hit the acceptance criteria listed per
subagent at the bottom of this file.

---

## 1. End-user experience

A single-page web app served from `gh-pages`. User opens the site and sees:

1. The 10 .sv corpus files listed in a left rail (file picker, multi-select
   defaults to "all" so the graph reflects the whole corpus).
2. The selected file(s)' source code rendered read-only in a centre code
   pane with line numbers and SystemVerilog syntax highlighting.
3. The semantic+BLOB knowledge graph rendered to the right of the code pane
   (Cytoscape.js, force-directed layout with manual pin support).
4. A query bar at the top: canned-query dropdown + free-text input.
5. A bottom tray that hosts the guided tutorial (collapsible) and the
   payload inspector for the currently-selected node/edge.

### Page layout (ASCII mockup)

```
+---------------------------------------------------------------------------+
| KGWeave AST Demo                                  [query bar______] [Run] |
+--------+------------------------------+-----------------------------------+
| Files  |  fifo.sv                     |          Graph (Cytoscape)        |
| [x] fifo_pkg                          |                                   |
| [x] fifo_if   1  module fifo #(...)   |       ( module:fifo )             |
| [x] fifo      2    input  logic clk,  |          |  contains              |
| [x] fifo_asr  3    output logic full, |       ( port:full )---drives--->( |
| [x] top       4    ...                |                                   |
| [x] cls       5    always_ff @(...)   |                                   |
| [x] checker   6      ...              |                                   |
| [x] extern    7  endmodule            |                                   |
| [x] prim      ^^^^ highlight on click |                                   |
| [x] iface     |                       |                                   |
+--------+------------------------------+-----------------------------------+
| Tutorial: Step 3 of 12 — "Trace dataflow"  [Prev] [Next] [Skip]           |
| Inspector: edge `assign_lhs` from a1:n0173 -> a1:n0192                    |
|   payload: { kind: "ContinuousAssign", op: "=", span: 412..437 }          |
+---------------------------------------------------------------------------+
```

### Interactions

| User action                 | Result                                            |
| --------------------------- | ------------------------------------------------- |
| Click node                  | Highlight node + scroll code pane to span + open inspector |
| Hover node                  | Tooltip with kind + payload preview               |
| Click edge                  | Highlight both endpoints + scroll to edge's anchor span    |
| Select canned query         | Animate BFS traversal over graph; affected nodes flash       |
| Submit free-text query      | Parse into predicate (see query DSL §3.3); animate result    |
| Click code-pane span        | Reverse-lookup: highlight every node whose span ⊇ click loc  |
| Tutorial Next               | Run tutorial step (preselect file, run canned query, narrate) |

---

## 2. Static-only architecture confirmation

The orchestrator's static-only decision holds. SA1's probe confirms:

- pyslang is **only** needed at build time (it emits `graph.json`).
- Source ranges are stable integer byte-offsets — no need to re-parse in the
  browser.
- Multi-hop BFS over ≤ 50k nodes / ≤ 150k edges (whole corpus) is well
  within the budget for a single JS event loop on a laptop.
- Query DSL is hand-rolled — no SPARQL/Cypher endpoint needed.
- Cytoscape.js, CodeMirror 6, and Lit (for the panel shell) are all CDN-able
  ESM. No bundler required, but SA3 may opt for `esbuild` for ergonomics.

There is **no** operation the FE needs that requires a server. Confirmed.

---

## 3. JSON schema — `demo/data/graph.json`

Single artifact emitted by SA2. Schema is additive to the existing in-memory
lift+promote graph (see `src/lift.py`); SA2 must NOT mutate the in-memory
shape, only project it into the export format below.

### 3.1 Top-level

```jsonc
{
  "version": "1",                    // string, bumped on breaking change
  "generatedAt": "2026-05-16T...Z",  // ISO-8601 UTC
  "files": [ FileEntry, ... ],       // one per .sv file, in build order
  "nodes": [ NodeEntry, ... ],       // structural + semantic, see §3.2
  "edges": [ EdgeEntry, ... ],       // child + semantic, see §3.3
  "ruleFamilies": [ RuleFamily, ... ],  // tutorial-driving rollup, see §4
  "stats": {
    "nodeCount": 12345,
    "edgeCount": 23456,
    "semanticNodeCount": 678,
    "semanticEdgeCount": 901
  }
}
```

### 3.2 `FileEntry`

```jsonc
{
  "id": "fifo",                      // matches lift's id_prefix (stem)
  "path": "corpus/fifo.sv",          // repo-relative
  "source": "module fifo ...",       // raw bytes; rendered by CodeMirror
  "lineCount": 142,
  "rootNodeId": "fifo:n0001.SyntaxTree"
}
```

### 3.3 `NodeEntry`

Every node in `graph['nodes']` is exported, with span attached.

```jsonc
{
  "id": "fifo:n0042.ModuleDeclarationSyntax",
  "type": "ModuleDeclarationSyntax",   // Python class name
  "kind": "SyntaxKind.ModuleDeclaration", // pyslang SyntaxKind, stringified
  "isToken": false,
  "category": "semantic" | "structural" | "token" | "blob",
  // ---- span: present on EVERY non-token node, optional on tokens ----
  "span": {
    "file": "fifo",                  // FileEntry.id
    "startOffset": 412,              // byte offset, inclusive
    "endOffset": 487,                // byte offset, exclusive
    "startLine": 18,                 // 1-based
    "endLine": 21,
    "startCol": 3,                   // 1-based
    "endCol": 12
  },
  // ---- payload: the structural lift payload PLUS the semantic dict ----
  "payload": {
    // for tokens (lift):
    "rawText": "module", "valueText": "module",
    "trivia": [ {"kind": "...", "text": "..."} ],
    "isMissing": false,
    "source": {"line": 18},
    // for non-tokens (semantic promotion, when present):
    "semantic": {
      "ruleId": "S1",
      "name": "fifo",
      "path": "fifo",
      "extra": { ... rule-specific ... }
    },
    // BLOB payloads (operator/literal/type detail) — bucket1 BLOB rows:
    "blob": {
      "op": "<=",                    // operator literal text, if expr
      "literalKind": "IntegerLiteral",  // when SyntaxKind ∈ blob set
      "typeName": "logic [7:0]"      // for type-bearing nodes
    }
  }
}
```

`category` is computed by SA2 from `BUCKET_1_CHECKLIST.md`:
- semantic — node has `payload.semantic` (PROMOTE row).
- structural — CONTAINER row, no semantic promotion.
- blob — BLOB row, BLOB payload populated.
- token — `isToken=true`.

### 3.4 `EdgeEntry`

```jsonc
{
  "id": "e0042",                     // SA2 assigns sequential ids
  "src": "fifo:n0042.ModuleDeclarationSyntax",
  "dst": "fifo:n0043.NonAnsiPortListSyntax",
  "type": "child" | "of_module" | "drives" | "assign_lhs" | "assign_rhs"
        | "contains" | "extends" | "implements" | "imports" | "exports"
        | "instantiates" | "ports" | "param_of" | ... ,
  // Edge span: SA1 decision — use the SOURCE NODE's span as the edge anchor.
  // Rationale: synthesised edges have no token of their own; the source-side
  // span is the most stable click target (a user clicking the LHS of an
  // assign on line 42 expects the "drives" edge from that LHS to be in scope).
  "span": { "file": ..., "startOffset": ..., "endOffset": ..., ... },
  "payload": {
    "index": 0,                      // child-edge ordinal (lift)
    "ruleId": "S5",                  // semantic edges only
    "label": "drives"                // human-readable summary
  }
}
```

### 3.5 `RuleFamily`

Tutorial-driving rollup. SA2 emits one entry per family in §4.

```jsonc
{
  "id": "structure",
  "title": "Module / Interface / Package / Program structure",
  "ruleIds": ["S1", "S11a", "S11b", "S12b", "S12c", "S30"],
  "exemplarNodeIds": [ ... 3..5 node ids the tutorial focuses on ... ],
  "blurb": "Every top-level scope and its nested generate/modport children."
}
```

---

## 4. S-rule family showcases (tutorial coverage)

The tutorial runs through 10 family steps. Each step preselects a corpus
file, runs a canned query, and narrates the family. Coverage = S1..S89.

| # | Family               | Rule IDs                                        | Corpus file(s)       |
|---|----------------------|-------------------------------------------------|----------------------|
| 1 | Structure            | S1, S11a, S11b, S12b, S12c, S30                 | fifo, top, fifo_if, fifo_pkg |
| 2 | Ports & params       | S1 (port/param), S2, S3                         | fifo, iface_port     |
| 3 | Nets & vars          | S4                                              | fifo, fifo_pkg       |
| 4 | Continuous assign + dataflow | S5, S33..S39                            | fifo, top            |
| 5 | Procedural blocks    | S7, S8, S9, S19, S20, S21                       | fifo                 |
| 6 | Instances + hierarchy| S6, S28 (checker_instantiation)                 | top, fifo_asserts    |
| 7 | Assertions + clocking| S14, S15, S16, S17, S18                         | fifo_asserts         |
| 8 | Covergroups          | S22, S23                                        | fifo_asserts, checker_corpus |
| 9 | Classes + constraints| S24, S25, S26, S27                              | cls_corpus           |
|10 | Packages + types + externs | S31, S32, S29, S40..S57                   | fifo_pkg, extern_corpus, prim_corpus |

SA5 implements the tutorial; SA1 fixes the family ordering above. Adding a
step requires updating `ruleFamilies` in `graph.json` and the tutorial
script in lock-step.

---

## 5. Canned queries (required minimum 6)

SA4 must implement all six. Each query is a JS function
`(graph) => { nodes: NodeId[], edges: EdgeId[], path?: NodeId[][] }`.

| #  | Name                              | What it returns                                    | Edge types exercised   | Hops  |
|----|-----------------------------------|----------------------------------------------------|------------------------|-------|
| Q1 | "What drives `wr_data`?"          | Path from `port:fifo.wr_data` walking `drives`-inverse, `assign_rhs`, `assign_lhs` | drives, assign_*       | multi |
| Q2 | "All instances of `fifo`"         | All nodes with edge `of_module -> module:fifo`     | of_module              | 1     |
| Q3 | "Modules importing `fifo_pkg`"    | All scopes with edge `imports -> package:fifo_pkg` | imports                | 1     |
| Q4 | "Path from `top.dut_positional` to `a_imm_modscope`" | Hierarchical-name-resolved path across `contains` + `instantiates` | contains, instantiates | multi |
| Q5 | "Every concurrent assertion under `top`" | DFS from `module:top` filtered to `kind=ConcurrentAssertionMember` | contains               | multi |
| Q6 | "Class inheritance chain for `derived_cls`" | Follow `extends` edges to root           | extends                | multi |

Recommended additions (SA4 may include): Q7 "all checkers", Q8 "covergroups
with > N coverpoints", Q9 "extern declarations and their implementations".

### 5.1 Free-text query DSL (subset SA4 must support)

```
kind:<SyntaxKind>            # filter by SyntaxKind
rule:<S-id>                  # filter by semantic ruleId
name:<glob>                  # name index match
in:<file>                    # restrict to file
from:<nodeId> via:<edgeType> # path query, BFS
```

Composable with `&` (AND). E.g. `kind:ConcurrentAssertionMember in:fifo_asserts`.

---

## 6. Acceptance criteria per downstream subagent

Each subagent must end green on the six invariants (see ast_experiment
CLAUDE.md §6) **and** the acceptance criteria below.

### SA2 — graph export (`scripts/export_demo_graph.py`, `demo/data/graph.json`)
1. Re-runs `build_kg` on all 10 corpus files; emits the schema in §3 verbatim.
2. Every non-Token node carries a `span` with `startOffset < endOffset` and
   `startLine <= endLine`.
3. Edge `span` equals the source-node's span (SA1 decision §3.4).
4. `ruleFamilies` entries match §4 exactly, with non-empty `exemplarNodeIds`.
5. `tests/demo/test_export_graph.py` enforces schema with a JSON-schema
   validator (SA2 writes the schema file + the validator test).
6. Round-trip unaffected: `pytest research/ast_experiment/tests/ -x` green.

### SA3 — static FE skeleton (`demo/web/`)
1. Loads `data/graph.json` lazily; renders Cytoscape + CodeMirror panes.
2. Click node ⇒ code pane scrolls + highlights node's span (line range).
3. Click code-pane line ⇒ all nodes whose span covers that offset get
   selection ring; inspector shows top-most semantic node.
4. Inspector renders `payload.semantic` and `payload.blob` distinctly.
5. Lighthouse perf score ≥ 80 on a desktop run.
6. No remote network calls at runtime (CSP `connect-src 'self'`).

### SA4 — query engine + traversal viz
1. All 6 canned queries (§5) work, with animated multi-hop traversal.
2. Free-text DSL (§5.1) parses and runs; bad input shows inline error.
3. Result set ≤ 200 ms on the full-corpus graph (laptop, Chrome stable).
4. `tests/demo/test_query_engine.spec.ts` (or equivalent) covers Q1–Q6
   against the committed `graph.json` as a fixture.

### SA5 — tutorial / gallery
1. 10 steps matching §4; each step (a) selects file, (b) runs canned query,
   (c) narrates with text.
2. Resumable via `?step=N` URL param.
3. Skip-to-end works without state corruption.
4. Coverage check: every rule family in §4 visited at least once.

### SA6 — GH Pages deploy + E2E
1. `.github/workflows/demo.yml` builds graph.json (running pyslang in
   Python) and publishes `demo/web/` + `demo/data/` to `gh-pages`.
2. Playwright E2E (`tests/demo/e2e/*.spec.ts`):
   - Site loads; first paint < 3s.
   - Click `module:fifo` in graph ⇒ code pane shows line containing
     "module fifo".
   - Run Q1; assert at least one path is returned and animated.
   - Step through tutorial steps 1, 5, 10; assert each runs.
3. CI green on a fresh PR.

---

## 7. Non-negotiables (from `research/ast_experiment/CLAUDE.md`)

- No `import re` in `src/semantic/`.
- Byte-equal round-trip preserved (lift output untouched; SA2 only projects).
- bucket1 totals 135/88/213/42/58 = 536 (regenerate after any rule churn).
- TDD/Ralph loop on every subagent.
- Honest reporting: paste literal command output in DEMO_LESSONS.md.
