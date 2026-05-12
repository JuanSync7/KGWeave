# Experiment: lossless code ↔ pyslang elab ↔ graph round-trip

## Goal

Prove no information is lost when SystemVerilog source flows through:

    fifo.sv  →  pyslang SyntaxTree / Compilation  →  graph (nodes+edges+payload)

by building a **reverse engine** that performs:

    graph  →  pyslang-equivalent JSON  →  emitted SV text  →  re-parsed AST

and showing the re-parsed AST is **structurally equivalent** to the original (modulo trivia: whitespace, comments, formatting).

If round-trip is lossless on `fifo.sv`, the schema is honest for the constructs used. Any field in the pyslang elab that has no representation in graph+payload is a leak — we must capture it.

## Source under test

- `fifo.sv` — a small but structurally diverse push/pop FIFO. Single module, params, packed + unpacked dims, posedge/negedge sensitivity, async active-low reset, blocking + nonblocking assigns, continuous assigns, array bit-select inside array index, case statement, `$clog2` system call, integer literals, sized literals (`'0`, `1'b1`).

## Immutable artifacts (do not modify)

- `PROGRAM.md` (this file)
- `fifo.sv`
- `scripts/score.py` — counts pyslang AST node-classes encountered in `fifo.sv` that the round-trip test does NOT yet cover. Score 0 = all classes covered.
- `scripts/inventory.py` — dumps full pyslang AST for `fifo.sv` into `elab_dump.json` (ground truth)
- `tests/test_roundtrip.py` — golden round-trip test (failing at baseline)

## Mutable artifacts (the experiment writes these)

- `scripts/lift.py` — forward: pyslang AST → graph (nodes/edges/payload)
- `scripts/unlift.py` — reverse: graph → pyslang-equivalent JSON → SV text
- `schema.md` — per pyslang AST class: node-type, edge-type(s), payload key(s), reverse rule
- `docs/code_elab_graph_mapping.md` — per construct: code snippet → AST class → graph fragment → reverse
- `iterations.tsv` — Ralph log

## TDD / Ralph rules

1. **Round-trip test is written first** for any construct, and must fail before any forward/reverse code is added.
2. One construct per iteration. Each iteration = (failing test → forward+reverse → test passes → score drops → commit).
3. No regex inside `lift.py` / `unlift.py`. Pure AST traversal.
4. Payload may carry literal text only for trivia (comments, whitespace). Every semantic field must have a typed home (node, edge, or named payload key).
5. After each iteration: run `pytest research/ast_experiment/tests/`, run `scripts/score.py`, append to `iterations.tsv`, commit.

## Score function

```
score = | { ast_class touched by fifo.sv } \ { ast_class covered by passing round-trip cases } |
```

Coverage is "covered" only when the *reverse* rule for that class is exercised by a passing assertion in `test_roundtrip.py`.

## Stop conditions

- **Success:** score = 0 AND `parse(emit(unlift(lift(parse(fifo.sv))))) ≡ parse(fifo.sv)` modulo trivia.
- **Stuck:** 3 iterations in a row with no score drop. Stop and report.
- **Regress:** any passing test starts failing → revert that iteration.

## Out of scope

- Multi-module / hierarchical instantiation (kept for follow-up).
- Generate blocks, interfaces, classes (follow-up).
- Trivia preservation byte-for-byte — re-emit may differ in formatting, only AST equivalence required.

## Why this matters

Every byte of pyslang elab is information derived from source. The graph is a re-expression that makes information traversable via typed BFS. A round-trip proof guarantees the re-expression doesn't silently drop fields. Once `fifo.sv` round-trips, we extend to harder constructs with the same discipline.
