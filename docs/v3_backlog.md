# V3 Backlog — Deferred Items

Canonical ledger of deferred V3 work. Update this file as items land or new ones surface.

## In flight (do not start duplicates)

| Agent | Task | Files |
|---|---|---|
| `aaa36b3325e9886d3` | Bazel dep-pattern genericization (constructor arg) | `buildsys_bazel.py` |
| `a4eacdde698a01dba` | V3 #2: dvsim `import_cfgs` recursive resolution | `buildsys_dvsim.py` |
| `a6ef656edb3222bd3` | V3 #7: Symbol resolver portability audit (Tier 3 #5) | `sv_*.py` stack |

## Queued (auto-fires)

- **V3 #3 — Bazel macro/`load()` auto-discovery**: fires when `aaa36b3325e9886d3` completes (both touch `buildsys_bazel.py`).

---

## Tier 1 — bit-slice + generate

1. **Bit-slice query collapse** — `Index` nodes exist (1,831+ in AES) but no query helper folds slices back to base signal. Bit-accurate trace works; aggregate "what touches any bit of `x`" requires manual `slice_of` walks. → Add `queries.collapse_slices(backend, signal_name)` helper.

2. **Generate-loop iteration disambiguation** — Process names lack `[i]` index. Per-iteration trace paths indistinguishable. Pyslang exposes per-iteration via `[i]` suffix; needs threading into Process ID minting in `sv_v2_walker.py`.

## Tier 2 — branch guard promotion

3. **Per-branch guard on `data_flows` edges** — `branch_path` lives on `Branch` node attributes today. Promoting to edge attribute on contained `data_flows` triples makes "what gates this assignment?" a one-hop attribute lookup instead of a back-walk through `Branch` ancestors. Schema doc proposed; integration didn't land.

## Tier 3 — backend + symbol resolver portability

4. **Neo4j parity** — AST emission is NetworkX-only. Neo4j backend's `add_node`/`add_edge` don't accept `attributes`; also lagging on `layer`, `lhs_slice`, `confidence_tier`. Larger PR.

5. **Symbol-grounded resolver portability** *(in flight as agent `a6ef656edb3222bd3`)*:
   - Non-OpenTitan codebases (camelCase, dotted names)
   - Vendor-specific macros (`AES_BASE_ADDRESS` no-underscore variant)
   - Conditional compilation awareness (`#include` inside `#if 0`)

6. **Cross-module dataflow bridging refinement** — `data_flows` hops cleanly within a module; cross-module bridge via `Port` nodes is currently expressed as "same predicate, different `flow_kind` attr". Could fold further or add a unified-traversal helper that ignores `flow_kind` distinction.

## Tier 4 — DV-side coverage + assertion richness

7. **DV-side mapping for submodule coverage** — Symbol-grounded resolver only matches top-level DIFs. Submodules like `prim_lc_sync` get coverage transitively via `instantiates*` but never directly. Resolve `prim_*` modules via UVM agents/sequences targeting them.

8. **Assertion bodies / randomization constraints / covergroup expressions** — Currently coarse-grained. Assertion-expression decomposition would reuse the v2 walker pattern.

## Tier 5 — evidence + semantic richness

9. **`evidence_span` capture on dataflow edges** (assignment source text) — Empty after Wave 2 prereq migration; can be re-populated.

10. **Function/task LHS modeling** — Only continuous + `always_*` assignments decompose. Function/task body assignments not yet decomposed.

11. **Clock domain crossing detection via `clocked_by` graph** — `Process` nodes carry `clocked_by`/`reset_by`; cross-domain analysis is a query-side opportunity not yet implemented.

## Build-system reader follow-ups (from Phase 9)

12. **`#if 0` / preprocessor stripping in C/SV test files** — dead-code blocks contribute false `references` edges. Needs lightweight preprocessor.

12a. **dvsim full token expansion** (`{dv_root}`, `{top_dv_path}`, `{tool}`) — V3 #2 landed `import_cfgs` recursion + `{proj_root}` expansion, but real OT chip cfgs use additional tokens that block transitive chip→IP resolution. Need a token-resolver pass with project-conventions config.

13. **Cross-format dedup keying** — when a project uses both fusesoc and dvsim, readers may emit overlapping links; could tighten to a single canonical link with `source_format=set`.

14. **Real OpenTitan `.core` fusesoc fixture wiring** — `*.core` file under `~/RagWeave/opentitan_data` never pulled into tests.

15. **Makefile `$(VAR)` single-pass expander** — resolve simple `MODULE := $(BASE_MODULE)` chains.

## Schema doc divergences (reconciliation)

- `subgraph_by_layer({"slang", "ast"})` (set arg) is doc-aspirational; actual API takes a single string.
- v1 dataflow uses `layer="sv_dataflow"` not the doc's `layer="slang"`. Tests use the actual layer name.
- `references` predicate already existed in v1 schema (`Section→Section`); doc reuses the name with broader source/target types. Loader doesn't enforce — works in practice.

→ One-pass doc reconciliation against implementation reality.
