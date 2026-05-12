# Result — lossless SV round-trip + promote-on-demand semantic layer

Branch: `autoresearch/ast-roundtrip-2026-05-12`
Source under test: `research/ast_experiment/fifo.sv` (45 lines, single module).

## Final scores

| Oracle                  | Score | Target | Status |
|-------------------------|-------|--------|--------|
| Structural (`score.py`) | 0     | 0      | met    |
| Semantic (S1..S5 tests) | 0 failing | 0  | met    |
| Round-trip after promote| green | green  | met    |

Total pytest run: **22 passed, 0 failed, 0 skipped** (`uv run python -m pytest research/ast_experiment/tests/ -x -q`).

## Round-trip proof statement

For every pyslang `SyntaxNode` class touched by `fifo.sv` (48 classes — see
`ast_classes.json`), the assertion

```
"".join(token_text_stream(parse(emit(unlift(lift(parse(fifo.sv))))))) ==
"".join(token_text_stream(parse(fifo.sv)))
```

holds, and `_assert_class_roundtrip` enforces it **per class**, byte-equal at
the token level (modulo trivia after the final token, which pyslang drops
upstream regardless). Token leading trivia is preserved on the originating
Token payload, so whitespace, comments, and macro-style markers also round-trip.

After the semantic layer fires (rules S1..S5), `test_roundtrip_after_promote`
re-emits from the mutated graph and reasserts the same byte-level equivalence —
proving promotion is non-destructive.

## Structural iterations (iter-001..014)

* iter-001..006 (predecessor): built universal class-agnostic lift/unlift and
  covered ModuleDeclaration, header, port lists, port headers, parameter and
  data declarations, continuous assigns, dimensions — score reached 33.
* iter-007: ProceduralBlock + TimingControlStatement + event-expression family
  (score 27).
* iter-008: BlockStatement / Conditional / ElseClause / ConditionalPredicate /
  ConditionalPattern (score 22).
* iter-009: CaseStatement / StandardCaseItem / DefaultCaseItem (score 19).
* iter-010: BinaryExpression / PrefixUnaryExpression / ParenthesizedExpression
  / ConcatenationExpression (score 15).
* iter-011: IntegerVectorExpression / LiteralExpression / IdentifierName /
  IdentifierSelectName (score 11).
* iter-012: BitSelect / ElementSelect / RangeSelect (score 8).
* iter-013: SystemName / Invocation / ArgumentList / OrderedArgument (score 4).
* iter-014: SimplePropertyExpr / SimpleSequenceExpr / SyntaxNode / Token —
  **structural score = 0**.

## Semantic iterations (sem-01..05)

* sem-01 (S1) — `ModuleDeclarationSyntax` → `has_port` × 8, `has_param` × 2,
  `has_net` × 4. Module + every port/param/net is promoted to queryable.
* sem-02 (S2) — `ContinuousAssignSyntax` → `drives` (LHS port/net) + `reads`
  (RHS identifiers). `who_drives('dout')` returns one continuous-assign node;
  `who_drives('full')` reaches `count`.
* sem-03 (S3) — `ProceduralBlockSyntax(always_ff)` → `sensitive_to`
  (clk posedge, rst_n negedge) + `drives` (wr_ptr, rd_ptr, count) + `reads`
  (push, pop, rst_n, plus everything appearing inside predicates and case
  heads).
* sem-04 (S4) — `IdentifierSelectNameSyntax` → `reads`(base symbol). Resolves
  the bit-select-inside-index case from iter-013 by surfacing the base
  identifier as a queryable read target.
* sem-05 (S5) — `InvocationExpressionSyntax` over `SystemNameSyntax` → callee
  is `$clog2`; `reads`(argument identifier). Every `$clog2(DEPTH)` invocation
  has an outbound `reads` edge to `DEPTH`.

## Leaks recorded

`graph["semantic_leaks"]` is **empty** for `fifo.sv` — every identifier the
semantic rules resolve also appears in the module's promoted `name_index`. The
fallback path (name-string anchor with leak record) is in place but did not
fire on this input.

Latent caveats worth noting, even though they did not produce leaks here:

1. **Symbol anchor identity.** `_resolve` calls `Compilation.find(name)` and
   `lookupName(name)` to confirm the symbol exists, but the graph edge is
   anchored at the **promoted `DeclaratorSyntax` / `ImplicitAnsiPortSyntax`
   node**, located via a name-keyed index. The Python binding for pyslang
   exposes `Symbol.syntax`, but mapping that wrapper to a graph-node id is
   not stable across iterations (Python wrappers are short-lived and `id()`
   is unreliable), so name-keyed lookup is used as the final step. If two
   constructs share a name in distinct scopes this will collide — but
   `fifo.sv` is a single module with disjoint identifiers.

2. **Snip-and-ref placeholder.** REDIRECT.md called for an `_node_ref`
   placeholder when a rule snips a subtree out of its parent's payload. The
   structural lift stores empty payloads on container nodes (token text lives
   on Token leaves), so no snipping was required for S1..S5. The mechanism is
   reserved in `unlift.emit`'s contract but currently unused; documented in
   `schema.md` so the next rule that needs to relocate a subtree knows to
   teach `emit` to deref `_node_ref` slots first.

3. **Scope.** The rules assume a single top-level module and resolve
   identifiers within `topInstances[0].body`. Generate blocks, nested
   interfaces, classes, packages, and multi-module hierarchical instantiation
   are explicitly out of scope per REDIRECT.md §H and are not exercised by
   `fifo.sv`.

## Deferred items

* Multi-module / hierarchical instantiation (out of scope per REDIRECT.md).
* Generate blocks, interfaces, classes (out of scope).
* Symbol-anchored edges that survive renaming — currently edges are
  name-anchored (via the graph's `semantic_name_index`), not pointer-anchored
  to a `Symbol*`. Achievable once pyslang Python bindings expose a stable
  symbol-id / syntax-node-id we can store alongside graph nodes.
* Snip-and-ref relocation: only needed if a future rule wants to move a
  subtree under a different parent (e.g. lifting a port's range expression up
  to its declarator). Today every rule projects in place.

## How to reproduce

```bash
cd ~/KGWeave
uv pip install pytest  # one-time
uv run -- python -m pytest research/ast_experiment/tests/ -x -q
uv run python research/ast_experiment/scripts/score.py
```

Both should report `22 passed` and `score = 0`.

## Artefacts

* `scripts/lift.py`, `scripts/unlift.py` — universal structural backbone.
* `scripts/semantic.py` — promote-on-demand semantic layer (S1..S5,
  `queryable_nodes`, `neighbors`, `find_drivers`, `reads_of`,
  `cone_of_influence`).
* `tests/test_roundtrip.py` — structural fidelity oracle (per-class +
  full-token-stream).
* `tests/test_queries.py` — semantic query oracle (S1..S5) plus
  `test_roundtrip_after_promote` which keeps both oracles tied together.
* `schema.md`, `docs/code_elab_graph_mapping.md` — graph schema and
  per-construct mapping including the semantic projection.
* `iterations.tsv` — full iteration log with a `layer` column distinguishing
  `struct` (iter-001..014) from `sem` (sem-01..05).
