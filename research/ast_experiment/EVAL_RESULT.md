# EVAL_RESULT — runnable eval scorecard

Branch: `autoresearch/ast-roundtrip-2026-05-12`
Source under test: `research/ast_experiment/fifo.sv` + `research/ast_experiment/top.sv`
Suite: `research/ast_experiment/tests/test_eval_queries.py`
Command: `uv run -- python -m pytest research/ast_experiment/tests/ -q`

## Scorecard (one row per EVAL_QUERIES.md group)

| Group | Question class                                | Tests | Passed | Status |
|-------|-----------------------------------------------|-------|--------|--------|
| A     | Identity & enumeration                        | 3     | 3      | green  |
| B     | Direct drives / reads                         | 4     | 4      | green  |
| C     | Sensitivity / clocking                        | 2     | 2      | green  |
| D     | Cone of influence (forward + backward)        | 3     | 3      | green  |
| E     | Bit-select / array-index identifier resolution| 2     | 2      | green  |
| F     | Constants and parameters                      | 2     | 2      | green  |
| G     | Hierarchy / instantiation                     | 3     | 3      | green  |
| H     | Cross-hierarchy reasoning                     | 3     | 3      | green  |
| I     | Blob-required (payload-only)                  | 3     | 3      | green  |
| J     | Schema invariants                             | 3     | 3      | green  |
| **Total** |                                           | **28**| **28** | **green** |

Plus 6 Phase-1 named-tool tests + 3 Phase-2 graph_query tests in
`tests/test_queries_multi.py`, and the 34 pre-existing tests.

**Full suite: 71 passed, 0 failed.** Structural `score.py` stays at 0.
`semantic_leaks == []`. Round-trip token stream still byte-equal.

## API surface (after this loop)

`scripts/semantic.py` now exposes (in addition to the previous surface):

### Phase 1 — six named tools
* `port_connections(graph, instance_path) -> list[{port, src_path}]`
* `sensitivity_of(graph, always_id) -> list[{signal, edge}]`
* `width_of(graph, net_or_port_path) -> {packed_dim, unpacked_dim, data_type}`
* `default_value_of(graph, param_path) -> str | None`
* `instances_of(graph, module_name) -> list[str]`
* `forward_cone(graph, name) -> set[str]` (symmetric to `cone_of_influence`)

### Phase 2 — `graph_query` escape hatch

```python
graph_query(graph, {
    "match":  {"role": "param", "name": "DEPTH"},
    "follow": [
        {"edge": "reads", "direction": "in",
         "filter": {"role": "continuous_assign"}},
        {"edge": "drives", "direction": "out",
         "filter": {"role": "port"}},
    ],
    "return": "path",
})
# -> ['fifo.dout', 'fifo.full']
```

`filter` may carry a `payload_edge` sub-dict to match on edge-payload fields
(e.g. `{"instance": "top.u_fifo", "port": "clk"}`). All matching is
exact-equality on typed attributes — no regex, no substring scans.

## graph_query examples used in the eval suite

The eval suite itself uses the named tools for clarity; the multi-module test
file (`tests/test_queries_multi.py`) demonstrates `graph_query` on three
patterns that no named tool covers:

1. **always_ff sensitive to a port named `clk`** — 1-hop pattern via
   `sensitive_to`, filtered by role+name on the destination node.
2. **Output ports driven by a continuous_assign that reads a parameter** —
   2-hop pattern: param → (reads in) → continuous_assign → (drives out) → port.
3. **Parent net of a specific `(instance, port)` connection** — 1-hop pattern
   using `payload_edge` to filter on the `connects` edge payload.

## Hard invariants — still green

* Round-trip token stream byte-equal after every promote step.
* `score.py == 0` over the combined corpus.
* No regex in `semantic.py` or in any test.
* `semantic_leaks == []`.

## Stop reason

All EVAL_QUERIES.md assertions pass on the first complete pass; the existing
34 pre-extraction tests remain green; the 9 phase-1/phase-2 tests pass; the 28
new eval tests pass. Iteration loop terminates per the spec's first stop
condition.
