# V2 Dataflow Schema — Elaborated AST as Graph

> **Terminology note**: throughout this doc and the codebase, "AST" and
> `layer="ast"` refer to the **post-elaboration** tree (pyslang's
> `Compilation` of resolved `Symbol` objects), **not** the raw parse tree
> (`SyntaxTree`). Cross-references are already resolved, generates unrolled,
> parameters substituted, modports oriented. The layer tag is shorthand —
> `layer="elab"` would be more accurate; v3 may rename.

## Goal

The graph holds the full elaborated AST of every RTL module body, so that any
trace question — "what gates this assignment?", "what bits drive this
output?", "does reset reach this register?" — is answered by graph traversal,
not by falling back to source text.

This is the *graph as deterministic AST mirror* model: every meaningful
elaborated syntax node becomes a graph node, every parent-child link becomes
an edge, every name reference becomes a cross-edge to the declaration it
resolves to.

## Non-goals

- Type system / parameter resolution beyond what pyslang already gives us
- Assertion bodies, randomization constraints, covergroup expressions
  (separate extractors already cover these at coarser granularity)
- Tokens that carry no semantic content (parens, `begin`/`end`, commas)

## Scope of decomposition

Pyslang exposes both the parse tree and the elaborated semantic tree. V2
walks the **elaborated** tree because:

1. Cross-references (`NamedValueExpression` → `Symbol`) are already resolved.
2. Generate loops are unrolled — per-iteration content is real.
3. Parameter substitutions are applied — bit-slice ranges resolve to ints
   where possible.
4. Function inlining / interface modport resolution is done.

## Node types

### Existing (carried forward unchanged)

`RTL_Module`, `Interface`, `Program`, `Port`, `Signal`, `SW_Test`,
`Process`, `Spec_Claim`, etc. (See `config/kg_schema.yaml`.)

### New in v2

| Type           | Represents                                                | Example                                  |
| -------------- | --------------------------------------------------------- | ---------------------------------------- |
| `Operator`     | A single elaborated operator expression                   | `&&`, `==`, `+`, `~`, `?:`               |
| `Literal`      | A constant value (numeric, string, parameter-resolved)    | `4'b1010`, `32'h0`, `WIDTH`              |
| `Condition`    | A boolean expression at a control-flow gate (if/case/?:)  | The `(sel && !rst)` of an `if`           |
| `Branch`       | A specific arm of an `if`/`case`/ternary                  | The `then` arm, an `else if` arm         |
| `IfStatement`  | The `if`/`else if`/`else` chain itself                    | Container holding Branch nodes           |
| `CaseStatement`| `case` / `casex` / `casez` / `unique case`                | Container holding case-item Branch nodes |
| `Loop`         | `for`/`while`/`repeat`/`forever`/`foreach`                | Loop body container                      |
| `Assignment`   | A single `=` / `<=` / `assign` site                       | LHS + RHS reified as a node              |
| `Index`        | `signal[i]` / `signal[hi:lo]` slice node                  | Connects to base signal via `slice_of`   |
| `Call`         | Function/task invocation expression                       | `$display(...)`, `my_func(a)`            |

### Naming / stable IDs

Internal nodes (operators, conditions, branches, etc.) need names. Convention:

```
<scope>.<process_kind>_<idx>.<path_hash>
```

- `<scope>` — the module the process lives in (e.g. `aes_ctrl`).
- `<process_kind>_<idx>` — the existing v1 process naming
  (e.g. `always_ff_3`, `always_comb_0`, `assign_7`).
- `<path_hash>` — a short stable hash of the syntax path from the process
  root to the node: `(child_index_at_each_level, syntax_kind_at_each_level)`.
  Stable across reformats and unrelated edits, changes only when the
  expression itself is modified.

Example: `aes_ctrl.always_ff_3.4f2a` for the `&&` operator inside the first
`if` of that process.

`Literal` nodes are **shared by value** within a module —
`aes_ctrl.lit.32h0` once, not once per occurrence — to keep literal-edges
queryable as "everywhere `0` is used."

## Edge predicates

### Structural (parent-child in elaborated tree)

| Predicate    | Subject → Object                          | Notes                                |
| ------------ | ----------------------------------------- | ------------------------------------ |
| `contains`   | Module → Process / Process → Statement    | Generic structural containment       |
| `body_of`    | Statement → IfStatement/CaseStatement/Loop| Inverse of contains for clarity      |
| `then_branch`| IfStatement → Branch                      | The "if" arm                         |
| `elif_branch`| IfStatement → Branch                      | Each "else if" arm (ordered)         |
| `else_branch`| IfStatement → Branch                      | The "else" arm                       |
| `case_item`  | CaseStatement → Branch                    | Each case item; ordered              |
| `default_branch` | CaseStatement → Branch                | The `default:` arm                   |

### Expression decomposition

| Predicate    | Subject → Object                | Notes                                          |
| ------------ | ------------------------------- | ---------------------------------------------- |
| `operand`    | Operator → expression-node      | Generic; ordered. For binary ops, indices 0/1. |
| `lhs`        | Assignment → expression-node    | Left-hand side                                 |
| `rhs`        | Assignment → expression-node    | Right-hand side                                |
| `condition_of` | Condition → IfStatement/Branch/Loop | Links a Condition to what it gates       |
| `selector`   | CaseStatement → expression-node | The `case (selector)` expression               |
| `case_value` | Branch → Literal/Operator       | The match value(s) of a case item              |
| `slice_of`   | Index → Signal/Port             | Bit-slice's base signal                        |
| `slice_msb`  | Index → expression-node         | High bit (resolved Literal where possible)     |
| `slice_lsb`  | Index → expression-node         | Low bit                                        |

### Cross-references (semantic edges)

| Predicate    | Subject → Object                | Notes                                          |
| ------------ | ------------------------------- | ---------------------------------------------- |
| `references` | expression-node → Signal/Port/Literal | Generic name-resolution edge             |
| `reads`      | Process → Signal/Port           | Materialised summary edge (RHS reads)          |
| `writes`     | Process → Signal/Port           | Materialised summary edge (LHS writes)         |
| `triggered_by`| Process → Signal               | Sensitivity-list signal (clk, rst, level vars) |
| `clocked_by` | Process → Signal                | Specifically the clock                          |
| `reset_by`   | Process → Signal                | Specifically the reset (sync or async)         |

### Carried forward (semantically promoted from v1)

| Predicate     | Subject → Object              | Notes                                          |
| ------------- | ----------------------------- | ---------------------------------------------- |
| `data_flows`  | Signal/Port → Signal/Port     | The unified RHS→LHS hop. Replaces v1's split   |
|               |                               | between `drives_signal` (intra) and            |
|               |                               | `connects_to` (inter-module port). Both v1     |
|               |                               | predicates are deprecated; queries port to     |
|               |                               | `data_flows`.                                  |
| `assigned_in` | Signal/Port → Process          | Carried forward from v1                        |
| `instantiates`| Module → Module               | Unchanged                                      |

## Cross-module port unification

V1 has two predicates for the same logical hop:

```
parent.sig --connects_to--> child.in_port    (port-instance binding)
child.in_port --drives_signal--> child.internal  (intra-module dataflow)
```

V2 collapses both into `data_flows`. A BFS over `data_flows` walks
seamlessly across module boundaries. Internal mechanism:

- Port-instance bindings emit `data_flows` edges in both directions
  (parent_sig → child.in_port for inputs; child.out_port → parent_sig for
  outputs) at the same emit site as v1 `connects_to`.
- Intra-module dataflow emits `data_flows` instead of `drives_signal`.

`drives_signal` and `connects_to` are kept as **edge attributes** on the
`data_flows` triple (`flow_kind: "intra" | "port_in" | "port_out"`) so
queries can still partition.

## Bit-slice nodes

When v2 sees `signal[hi:lo]` or `signal[i]`:

- Materialise an `Index` node with a stable name:
  `<base_signal>.[<msb>:<lsb>]` — e.g. `aes_data.[31:24]`.
- Edge `Index --slice_of--> base Signal`.
- Edges `Index --slice_msb--> Literal(31)` and `--slice_lsb--> Literal(24)`.
- The `data_flows` source/target is the **Index** node, not the base
  signal. So `data_flows` queries are bit-accurate by default.

For aggregate "what touches any bit of x" queries, use `slice_of` to walk
back to the base.

## Sensitivity lists

`always_ff @(posedge clk or negedge rst_n)` decomposes to:

- `Process(always_ff_N) --triggered_by--> clk` (with edge attr `edge: posedge`)
- `Process(always_ff_N) --triggered_by--> rst_n` (with edge attr `edge: negedge`)
- `Process(always_ff_N) --clocked_by--> clk` (when exactly one posedge clk-shaped trigger)
- `Process(always_ff_N) --reset_by--> rst_n` (when an async reset pattern is detected)

`always_comb` / `always_latch` get `triggered_by` for level-sensitive signals,
no `clocked_by`/`reset_by`.

Clock and reset signals **do not** get `data_flows` or `reads` edges — they're
control, not data. This eliminates the v1 noise of clk/rst polluting the
dataflow neighborhood.

## Operator decomposition uniformity

The walker treats every operator the same: emit an `Operator` node with
`kind` attribute and ordered `operand` edges. Querying for "gating logic"
becomes a query-side concern:

```python
gating_kinds = {"LogicalAnd", "LogicalOr", "Not", "Eq", "Ne",
                "Lt", "Gt", "Le", "Ge", "Conditional"}
```

Arithmetic operators (`+`, `-`, `*`, `<<`, `&`, `|`, `^`, `~`) use the same
shape but won't typically be queried for control-flow analysis. Cost is
small — a typical RTL expression is 3–7 nodes deep.

## Per-branch flow attribution

The headline trace question — "what gates this assignment?" — is answered
by walking the `data_flows` source's containing Branch upward through
`then_branch`/`elif_branch`/`else_branch`/`case_item` predicates, collecting
the Conditions along the path.

To make this a one-hop query, every `data_flows` edge emitted from inside a
Branch carries an attribute `branch_path: [<branch_node_id>, ...]`. Then:

```cypher
MATCH (a:Assignment)-[f:data_flows]->(target)
RETURN f.branch_path  // ordered list of branch nodes that gate this flow
```

## What gets skipped

To keep the graph tractable:

- Parens (`(x + 1)`) — pyslang elaboration already nests; parens are noise.
- `begin`/`end` block delimiters as separate nodes — block contents become
  ordered children of the parent statement directly.
- Trivia / whitespace / comments.
- Generic empty statements (`;`).
- `$display`/`$write` calls in non-synthesizable contexts get a `Call` node
  but their argument expressions are kept as flat string attributes
  (display formatting isn't trace-relevant).

## Layering — RTL-engineer view vs everyone else

V2 AST decomposition is verbose and only the RTL-debug persona cares about
operator/literal/condition internals. To avoid polluting the audit / SW
test / spec-claim consumers' default view, all v2 internals are tagged with
`layer: "ast"` using the existing `Entity.layer` / `Triple.layer` attribute.

| Layer    | Contents                                                          | Default visibility |
| -------- | ----------------------------------------------------------------- | ------------------ |
| `slang`  | RTL_Module, Port, Signal, Process, `data_flows`, `clocked_by`,    | Visible to all     |
|          | `reset_by`, `triggered_by`, `assigned_in`, `instantiates`         | consumers          |
| `ast`    | Operator, Literal, Condition, Branch, IfStatement, CaseStatement, | Hidden by default; |
|          | Loop, Assignment, Index, Call; predicates `operand`, `lhs`, `rhs`,| RTL-debug views    |
|          | `condition_of`, `then_branch`, `elif_branch`, `else_branch`,      | opt in             |
|          | `case_item`, `default_branch`, `selector`, `case_value`,          |                    |
|          | `slice_of`, `slice_msb`, `slice_lsb`                              |                    |
| `slang`  | `reads` / `writes` summary edges (Process → Signal/Port)          | Visible to all —   |
|          |                                                                   | summarises ast     |
|          |                                                                   | layer for non-debug|
|          |                                                                   | consumers          |

Why one graph, not two:

- `data_flows` (slang layer) hops across module boundaries via Port nodes
  that the AST layer's Operator nodes also need to reference. Cross-graph
  joins would re-implement what NetworkX already does in one MultiDiGraph.
- `subgraph_by_layer({"slang", "ast"})` already exists on the backend.
- One extraction pass — the slang walker emits both layers, sharing
  cross-reference resolution.
- `diff_layers` works for free, so AST drift across runs is observable
  with existing tooling.

Consumer access patterns:

```python
# Audit / SW test / spec consumers (default — unchanged from v1):
backend.subgraph_by_layer({"slang"})

# RTL debug persona — full trace including expression internals:
backend.subgraph_by_layer({"slang", "ast"})

# Sigma export default: include_layers={"slang"}; opt in via include_layers=None.
```

## Schema migration

V2 is **additive** for existing predicates. Specifically:

- All v1 entity types remain.
- `drives_signal` / `connects_to` triples are **dual-emitted** for one
  release: both the legacy predicate and the new `data_flows` predicate.
  Queries should migrate to `data_flows`. After dogfooding, drop the legacy
  predicates in a follow-up.
- `Process` entities gain attributes `clock`, `async_reset`, `sync_reset`
  (canonical signal names) — pure additions.
- New node types are gated behind a config flag
  `KGConfig.enable_ast_decomposition` (default `True` for the AES demo,
  `False` for older callers that want v1 graph shape). Sigma export
  filters expression-tree nodes by default; opt in with
  `include_ast_internals=True`.

## Performance budget

AES dataset projection:

| Metric                    | V1     | V2 estimated | Cap (fail-loud above)|
| ------------------------- | ------ | ------------ | -------------------- |
| Nodes                     | 6,145  | ~30,000      | 100,000              |
| Edges                     | 15,115 | ~80,000      | 250,000              |
| Sigma render time         | <1 s   | <3 s (filtered) | <10 s             |
| AES extraction wall time  | ~12 s  | ~25 s        | <60 s                |

## Test plan (per wave)

**Wave 1 — Walker core:**
- One Operator node per binary/unary/ternary in fixture
- Stable IDs across re-runs of identical input
- Operand ordering preserved
- Cross-reference edges: NamedValue → declared Signal/Port

**Wave 1 — Statement decomposition:**
- if/elif/else → IfStatement + ordered Branches
- case/casex/casez/unique case → CaseStatement + Branches with case_value
- for/while/repeat/forever → Loop with body container
- Assignment node emitted with lhs/rhs edges
- Branch path attribution on contained data_flows edges

**Wave 1 — Cross-reference resolver:**
- NamedValue resolves to existing entity (not a new Signal node)
- Hierarchical references (`u_inst.sub.sig`) resolve through instance
- Unresolved references emit a low-tier sentinel (consistent with v1)

**Wave 2 — Integration:**
- Legacy `drives_signal` and `connects_to` queries still pass on v2 graph
- `data_flows` BFS hops cleanly across module boundaries
- Bit-slice queries return Index nodes, not base signals
- AES demo: 27 RTL_Modules still reachable from `aes`; counts within budget

**Wave 2 — Sigma:**
- Default render (no `include_ast_internals`) shows ≤ v1 node count
- With AST internals: graph renders within 3s for AES

**Wave 3 — Dogfood:**
- Real query: "what gates `data_in_prev_q[7:4]` in `aes_control_fsm`?"
  returns the Condition path purely on graph.
- Real query: "trace `key_init_i` from top-level port to where it
  influences `state_q`" — single BFS over `data_flows`.

## Open questions (decide during Wave 1)

1. **Literal sharing scope** — module-level (one `lit.32h0` per module) or
   global (one across the project)? Lean module-level for stability.
2. **Hierarchical name resolution depth** — fully resolve `u_top.u_sub.sig`
   to a single edge, or leave as multi-hop through Instance nodes?
   Lean: multi-hop, with a query helper that flattens.
3. **Generate-loop instance disambiguation** — pyslang exposes per-iteration
   instances with `[i]` suffix; should `Process` IDs include the index?
   Lean yes — distinct iterations have distinct trace paths.
