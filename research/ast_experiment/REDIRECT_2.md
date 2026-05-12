# Redirect #2 — hierarchical-path keying + multi-module semantic layer

Date: 2026-05-12. Issued after sem-final (score=0, S1..S5 green on fifo.sv).

## Decisions locked

1. **Edge endpoint key = hierarchical path** (e.g. `top.u_fifo.count`).
   - Within a flat SV scope, names are unique by language rule, so the path's leaf component is unambiguous.
   - Across scopes (modules, generate blocks, always_ff named blocks, functions, packages), the path chain disambiguates.
   - Pyslang elaboration already constructs this hierarchy — use it; do not invent our own naming.
   - `type` (net | port | param | instance | …) rides along as **node metadata** for query-time filtering, not as part of the lookup key.

2. **Structural lift/unlift is unchanged.** It is already multi-module-clean because it is class-generic. Round-trip remains the oracle.

3. **Semantic layer extended to multi-module.** S1..S5 fire per-module instead of only on `topInstances[0].body`; a new S6 rule handles instantiation + port-connection edges.

## Mandate for this loop

### Step 1 — switch `semantic_name_index` to hierarchical-path keys
- Replace bare `"count"` keys with `"<scope_path>.<name>"`, e.g. `"fifo.count"` or `"top.u_fifo.count"`.
- Build the path by walking the elaborated `InstanceBodySymbol` chain (or syntax-tree enclosing-scope chain if symbol path is not reachable).
- Every S1..S5 query test must still pass after the keying change — the existing fifo.sv has disjoint names, so paths just become `fifo.<name>`. No behavior change there.
- If a name lookup is performed with a bare name, expand it against the current scope's path first; record any unresolved lookup in `semantic_leaks` (and fail the iteration if leaks are non-empty for inputs that should resolve).

### Step 2 — add `top.sv` as a second source file
- New file: `research/ast_experiment/top.sv`. Top module instantiates `fifo` once (`u_fifo`), passes through clock/reset, drives `push`/`pop` with simple stimulus signals, observes `dout`/`full`/`empty`.
- Keep it small — single hierarchy level, no generate blocks, no parameter overrides initially. Goal is the *minimum* multi-module case.
- Inventory `top.sv` + `fifo.sv` together. `ast_classes.json` will grow; **the structural round-trip must cover the new classes**. Likely additions: `HierarchyInstantiationSyntax`, `HierarchicalInstanceSyntax`, `NamedPortConnectionSyntax`, `PortConnectionSyntax`. Run Ralph structurally first to drive score back to 0 over the combined corpus.

### Step 3 — Ralph the structural delta
- Re-run inventory on the combined corpus (`fifo.sv` + `top.sv`).
- Score is now `|combined_classes| - |covered_classes|`. Iterate until 0. Each iter: failing per-class assertion → forward+reverse → covered → commit.
- No regex.

### Step 4 — S6 rule: InstantiationSyntax / HierarchicalInstanceSyntax / NamedPortConnectionSyntax
- Promote each hierarchical instance to a queryable node typed `instance`, anchored at `<parent_path>.<inst_name>` (e.g. `top.u_fifo`).
- Edges:
  - `top --instantiates--> top.u_fifo`
  - `top.u_fifo --of_module--> fifo`  (note: module *definition* is a separate node from the *instance*)
  - For each port connection: `top.<connected_net> --connects--> top.u_fifo.<port_name>` (and its reverse via direction)
- For unconnected / `.*` / wildcard connections, follow pyslang's elaborated binding — never guess from text.
- TDD via new `tests/test_queries_multi.py`:
  - `instantiates_of('top')` returns `[top.u_fifo]`
  - `module_of('top.u_fifo')` returns `fifo`
  - `port_connections('top.u_fifo')` returns the mapping
  - **cross-module cone**: `cone_of_influence('top.u_fifo.count')` reaches `top.push`, `top.pop`, `top.rst_n` — proves the connect+drives chain works.

### Step 5 — extend S1..S5 to fire per-module
- S1 currently fires on `topInstances[0].body`. Change to: iterate every `InstanceBodySymbol` in the compilation and fire S1 on each.
- S2/S3/S4/S5 already work on syntax subtrees, but their identifier resolution must use the **enclosing module's** path prefix.
- Re-run all S1..S5 tests; they must remain green AND now also cover the second module.

### Step 6 — final verification + writeup
- `score.py` = 0 over combined corpus.
- All structural + semantic + multi-module query tests pass.
- `semantic_leaks` is empty for both files.
- Update `RESULT.md` — add a "multi-module" section, restate the proof statement covering both files, remove caveats #1 and #3 (or mark them resolved), keep caveat #2 (snip-and-ref still unused).
- Update `schema.md` — add `instance`, `of_module`, `instantiates`, `connects` to the edge/node table. Document the hierarchical-path keying convention.
- Update `docs/code_elab_graph_mapping.md` with rows for `HierarchyInstantiationSyntax`, `HierarchicalInstanceSyntax`, `NamedPortConnectionSyntax`.

## Invariants (do not break)
- Round-trip remains the fidelity oracle. Every iteration must leave it green.
- No regex anywhere in lift/unlift/semantic.
- Hierarchical path is the **only** new keying mechanism — do not introduce a parallel string-name fast-path.
- One iteration = one structural class OR one semantic rule. Commit per iter.

## Stop conditions
- Combined `score.py` = 0 AND all multi-module query tests pass AND fifo-only S1..S5 still green → success.
- 3 iters with no score drop on either axis → stop and report.

## Out of scope (still)
- Generate blocks, interfaces, classes — defer to a future loop. If `top.sv` would naturally include one, omit it and keep the example flat.
- Parameter overrides on instantiation (`#(.DEPTH(16))`) — can include if trivial, otherwise defer; the key issue is the parameter-override resolution path which is a whole sub-experiment.
- Symbol-pointer-anchored edges — explicitly superseded by hierarchical-path keying.

## Why this redirect
Caveat #1 (`name-anchored` collision risk) and caveat #3 (multi-module out of scope) are the only two real correctness gaps in the previous loop. Both close with hierarchical-path keying + one new structural cluster + one new semantic rule. The structural backbone needs no change because it is class-generic. The semantic layer needs the key swap and one promotion rule. Bounded work, clear oracles, both caveats removed.
