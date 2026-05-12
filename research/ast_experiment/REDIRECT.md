# Redirect — promote-on-demand semantic layer over the structural backbone

Date: 2026-05-12. Issued after iter-007.

## Decision

The universal structural lift/unlift (iter-001..006) is the **fidelity backbone** and stays as-is. It guarantees lossless round-trip by construction (every Syntax node → graph node, slot edges, tokens in payload).

We now add a **semantic layer** as a projection over the same graph:

- Default: every structural node is **internal** — present in the graph for round-trip, but hidden from the query surface.
- A semantic **rule** matches a structural subtree and **promotes** its anchor node to **queryable**, drawing typed semantic edges (`drives`, `reads`, `sensitive_to`, `instantiates`, …) to other (auto-promoted) nodes.
- Identifier resolution for edge endpoints uses the elaborated `pyslang.Compilation`, NOT name strings — every edge anchor is a stable symbol.

The two layers share one underlying graph. The structural layer is the storage; the semantic layer is a view.

## Two oracles, both must hold

1. **Fidelity oracle** (existing `tests/test_roundtrip.py`): structural class-stream + token-text-stream round-trip. Drives `score.py` (target 0).
2. **Query oracle** (NEW `tests/test_queries.py`): given the same `fifo.sv`, semantic-layer BFS answers concrete questions:
   - `who_drives(port='dout')` → assign node anchored at line 22
   - `cone_of_influence(port='full')` → backward BFS hits `count`, `DEPTH`, the always_ff, `push`, `pop`, `rst_n`
   - `drivers_of(net='wr_ptr')` → the always_ff, with the two assignments inside it
   - `reads_of(port='din')` → the inner if-block assignment to `mem`
   - `sensitivity_of(always_block)` → `posedge clk`, `negedge rst_n`

Both test files must stay green together for an iteration to count.

## Mandate for the resumed loop

### A. Finish structural coverage (mechanical)
Continue Ralph iterations until `score.py` reports 0. Remaining classes from iter-006 baseline (33 left). Order suggestion based on dependencies:
- ProceduralBlockSyntax + TimingControlStatementSyntax + EventControlWithExpressionSyntax
- BinaryEventExpressionSyntax + SignalEventExpressionSyntax + ParenthesizedEventExpressionSyntax
- BlockStatementSyntax + ConditionalStatementSyntax + ElseClauseSyntax + ConditionalPredicateSyntax + ConditionalPatternSyntax
- CaseStatementSyntax + StandardCaseItemSyntax + DefaultCaseItemSyntax
- BinaryExpressionSyntax + PrefixUnaryExpressionSyntax + ParenthesizedExpressionSyntax + ConcatenationExpressionSyntax
- IntegerVectorExpressionSyntax + LiteralExpressionSyntax + IdentifierNameSyntax + IdentifierSelectNameSyntax
- BitSelectSyntax + ElementSelectSyntax + RangeSelectSyntax
- SystemNameSyntax + InvocationExpressionSyntax + ArgumentListSyntax + OrderedArgumentSyntax
- SimplePropertyExprSyntax + SimpleSequenceExprSyntax + SyntaxNode + Token

### B. Build the semantic layer in parallel
New file: `scripts/semantic.py`. Exposes:

```python
def promote(graph, syntax_tree, compilation) -> None:
    """Mutate `graph` in place: mark nodes queryable + add typed semantic edges."""

def queryable_nodes(graph) -> Iterator[Node]: ...
def neighbors(graph, node_id, edge_type=None, direction="out") -> list[Node]: ...
```

Implement one rule per iteration, TDD'd via `tests/test_queries.py`:

| Iter | Rule | Promotes | Adds edges | Query test |
|------|------|----------|-----------|-----------|
| S1 | `ModuleDeclarationSyntax` | module, every port, every param, every net | `has_port`, `has_param`, `has_net` | "module fifo has 8 ports, 2 params, 4 nets" |
| S2 | `ContinuousAssignSyntax` | the assign | `drives`(LHS port/net), `reads`(every RHS identifier) | `who_drives('dout')` returns 1 assign |
| S3 | `ProceduralBlockSyntax` (always_ff) | the block | `sensitive_to`(clk posedge, rst_n negedge), `drives`(every LHS target inside), `reads`(every RHS identifier inside) | `cone_of_influence('full')` reaches `push`, `pop`, `rst_n` |
| S4 | `IdentifierSelectNameSyntax` | the base symbol only | `reads`(base) — proves the bit-select-inside-index case from iter-013 | `reads_of(net='rd_ptr')` returns the dout assign |
| S5 | `SystemNameSyntax($clog2)` | the call | `reads`(argument identifier) | $clog2(DEPTH) → reads(DEPTH) |

### C. Identifier resolution via Compilation
- `conftest.py` already builds the SyntaxTree. Extend it to also build `pyslang.Compilation` and pass both to lift/promote.
- In each semantic rule, resolve identifier tokens by looking up in the compilation's symbol table for the enclosing scope. The graph edge points to the **symbol-anchored node**, not the name.
- If pyslang's Python API can't expose the symbol for a given lookup, fall back to name-resolution scoped to the current module — note this in `RESULT.md` as a "leak: name-string lookup used here because Python binding doesn't expose Symbol.lookup."

### D. Snip-and-ref invariant (the proof point)
For each queryable node, when its rule fires:
- Its `payload` is its (now snipped) verbatim AST blob.
- In the parent's structural payload, the slot it occupied becomes `{"_node_ref": "<promoted-id>"}`.
- `unlift` must already handle this: when emitting a slot, if the slot is `_node_ref`, resolve it and emit that node's payload.

The round-trip test must stay green after every semantic iteration. If it breaks, the promotion is lossy and that iteration is reverted.

### E. Scoring
- Structural score (unchanged): `len(ast_classes) - len(covered_classes)`, target 0.
- Semantic score: count of failing query-test assertions, target 0.
- An iteration "counts" only if it drops one of the two scores without regressing the other.

### F. Logging
Continue appending to `iterations.tsv`. Add a `layer` column (or prefix iteration as `S1`, `S2`, … for semantic). Mark commits.

### G. Final deliverables
1. `score.py` reports 0.
2. All query tests pass.
3. `schema.md` documents both layers — structural slot tables + semantic rule table.
4. `docs/code_elab_graph_mapping.md` updated: per construct, show **structural fragment** + **semantic projection** + reverse rule.
5. `RESULT.md` summarising leaks, deferred items, and the round-trip proof.

### H. Out of scope (still)
- Generate blocks, interfaces, classes.
- Multi-module hierarchical instantiation.
- Compilation-symbol-based edges for anything outside the single `fifo` module.

## Why this redirect

The structural backbone you've built is correct and lossless — keep it. What we're adding is the *query convenience* layer: typed edges that let the agent answer "who drives X" with a one-hop lookup instead of grep. The two layers share one graph and are tested with two independent oracles, so we can't trade fidelity for query ergonomics by accident.
