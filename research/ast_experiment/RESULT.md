# Result — lossless SV round-trip + promote-on-demand semantic layer

Branch: `autoresearch/ast-roundtrip-2026-05-12`
Sources under test:
* `research/ast_experiment/fifo.sv` (45 lines, single module).
* `research/ast_experiment/top.sv` (23 lines, instantiates `fifo` once as `u_fifo`).

## Final scores

| Oracle                           | Score | Target | Status |
|----------------------------------|-------|--------|--------|
| Structural (`score.py`, combined)| 0     | 0      | met    |
| Semantic (S1..S5 fifo-only)      | 0 failing | 0  | met    |
| Multi-module S6 queries          | 0 failing | 0  | met    |
| Round-trip after promote (both)  | green | green  | met    |
| `semantic_leaks` (both files)    | 0     | 0      | met    |

Total pytest run: **34 passed, 0 failed, 0 skipped**
(`uv run -- python -m pytest research/ast_experiment/tests/ -x -q`).

## Round-trip proof statement (combined corpus)

For every pyslang `SyntaxNode` class touched by `fifo.sv` **or** `top.sv` (52
classes — see `ast_classes.json`, including the four hierarchy classes added
this loop), the assertion

```
"".join(token_text_stream(parse(emit(unlift(lift(parse(src))))))) ==
"".join(token_text_stream(parse(src)))
```

holds for `src ∈ {fifo.sv, top.sv}`, and `_assert_class_roundtrip` enforces it
**per class**, byte-equal at the token level (modulo trivia after the final
token, which pyslang drops upstream regardless). The same property holds for
the concatenated multi-module source used by `test_queries_multi.py`'s
`test_multi_roundtrip_after_promote`.

After the semantic layer fires (rules S1..S6), `test_roundtrip_after_promote`
and `test_multi_roundtrip_after_promote` re-emit from the mutated graph and
reassert the same byte-level equivalence — proving promotion is non-destructive
in both the single-module and multi-module cases.

## Structural iterations (iter-001..018)

* iter-001..014 (previous loop): universal class-agnostic lift/unlift covering
  every class in `fifo.sv` — score reached 0.
* iter-015: cover `HierarchyInstantiationSyntax` from `top.sv` (score 3).
* iter-016: cover `HierarchicalInstanceSyntax` (score 2).
* iter-017: cover `InstanceNameSyntax` (score 1).
* iter-018: cover `NamedPortConnectionSyntax` — **combined structural score
  = 0** over `fifo.sv + top.sv`.

Because lift/unlift is class-agnostic, no code change to the structural backbone
was required for any iter-015..018; each iter added a per-class round-trip
assertion in `tests/test_roundtrip.py` and the existing universal emit covered
it byte-for-byte.

## Semantic iterations (sem-01..07)

* sem-01..05 (previous loop): S1..S5 on `fifo.sv`.
* sem-06: replace bare-name keys in `semantic_name_index` with **hierarchical
  paths** sourced from `InstanceBodySymbol`. S1..S5 now fire per
  `ModuleDeclarationSyntax`, with `scope_path = module.name`. `find_by_name`
  accepts full paths and (unambiguous) bare leaf names.
* sem-07: S6 — `HierarchyInstantiationSyntax` promotion. Each hierarchical
  instance is promoted to a `instance`-role node at path
  `<parent>.<inst_name>`. Edges drawn:
  * `top --instantiates--> top.u_fifo`
  * `top.u_fifo --of_module--> fifo` (module definition)
  * `top.<net> --connects--> fifo.<port>` for each `NamedPortConnectionSyntax`
    (payload carries `{instance, port}` for queryability).
  * `cone_of_influence` extended to traverse incoming `connects` edges, so a
    cone rooted at the child module's `count` reaches the parent module's
    driver inputs through the hierarchy.

## Leaks

`graph["semantic_leaks"]` is **empty** for both `fifo.sv` alone and for the
combined `top.sv + fifo.sv` compilation. Every identifier the rules resolve
matches a promoted hierarchical-path key AND a live `Symbol` in the elaborated
`InstanceBodySymbol` for the enclosing module.

## Caveats — status

| Prior caveat                           | Status     | Notes                                                                              |
|----------------------------------------|------------|------------------------------------------------------------------------------------|
| #1 Name-anchored symbol identity       | resolved   | Identity is now `(<scope_path>.<leaf>)`. Collisions between scopes are impossible. |
| #2 Snip-and-ref placeholder unused     | unchanged  | S1..S6 still project in place; no rule needs to relocate a subtree.                |
| #3 Single-top-module scope             | resolved   | S1..S5 fire per `ModuleDeclarationSyntax`; S6 covers cross-module instantiation.   |

The remaining open item (snip-and-ref) is still latent — the mechanism is
reserved in `unlift.emit`'s contract but no rule currently requires it.
Documented in `schema.md` so the next rule that needs to relocate a subtree
knows to teach `emit` to deref `{"_node_ref": "<id>"}` slots first.

## Deferred items

* Generate blocks, interfaces, classes, packages (out of scope per REDIRECT.md).
* Parameter overrides on instantiation (`#(.DEPTH(16))`) — `top.sv` currently
  takes the child module's defaults. The connection logic does not yet attempt
  to track override-resolution.
* Symbol-pointer-anchored edges that survive renaming — superseded by
  hierarchical-path keying (the redirect explicitly rules these out).
* Snip-and-ref relocation: only needed if a future rule wants to move a subtree
  under a different parent.

## How to reproduce

```bash
cd ~/KGWeave
uv pip install pytest  # one-time
uv run -- python -m pytest research/ast_experiment/tests/ -x -q
uv run python research/ast_experiment/scripts/score.py
```

Both should report `34 passed` and `score = 0` over the combined corpus.

## Artefacts

* `scripts/lift.py`, `scripts/unlift.py` — universal structural backbone
  (class-agnostic; covered every new hierarchy class with no code change).
* `scripts/semantic.py` — promote-on-demand semantic layer with hierarchical-
  path keying. Rules: S1..S6, helpers `find_by_name`, `find_drivers`,
  `reads_of`, `cone_of_influence` (cross-hierarchy), `queryable_nodes`,
  `neighbors`, `_all_module_scopes`, `_scope_path_of`, `_rule_s6`.
* `tests/test_roundtrip.py` — structural fidelity oracle (per-class +
  full-token-stream) for both `fifo.sv` and `top.sv`.
* `tests/test_queries.py` — semantic query oracle (S1..S5) for fifo.sv plus
  `test_roundtrip_after_promote`.
* `tests/test_queries_multi.py` — multi-module S6 oracle:
  `instantiates_of('top')`, `module_of('top.u_fifo')`,
  `port_connections('top.u_fifo')`, `cone_of_influence('fifo.count')` reaches
  `top.push / top.pop / top.rst_n`, plus per-module S1 firing.
* `schema.md`, `docs/code_elab_graph_mapping.md` — graph schema and
  per-construct mapping including the multi-module semantic projection.
* `iterations.tsv` — full iteration log with a `layer` column distinguishing
  `struct` (iter-001..018) from `sem` (sem-01..07).
