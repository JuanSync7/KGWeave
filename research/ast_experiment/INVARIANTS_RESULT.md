# Multi-file build_kg + Structural Invariants — Result

## Context

The HTML renderer exposed a real bug: lifting two SV files as independent
`SyntaxTree`s and merging the resulting graph dicts dropped cross-tree
edges (`top.u_fifo --of_module--> fifo`) and collided on per-tree node ids
(`n0001.CompilationUnitSyntax` appears in every tree). The existing
multi-module tests masked this because their fixture concatenated SV
strings into a single `SyntaxTree`, bypassing the real multi-file path.

## Deliverable A — `build_kg`

`scripts/build.py` provides the new production entry point:

```python
graph, trees, compilation = build_kg([fifo_path, top_path])
```

- Each file becomes its own `pyslang.SyntaxTree` (parsed via `fromText` to
  preserve the byte-equal round-trip invariant — `fromFile` injects extra
  EOF trivia that diverges from the existing token-stream oracle).
- All trees are added to ONE `pyslang.Compilation` before any elaboration
  query runs (pyslang finalises the compilation on first
  `getRoot()`/`topInstances` access).
- `lift(tree, *, graph=None, id_prefix="")` is a backwards-compatible
  extension — when `graph` is supplied, nodes/edges are appended in
  place and `id_prefix` (the file stem) namespaces node ids
  (e.g. `top:n0017.ImplicitAnsiPortSyntax`).
- `promote(graph, tree, comp, *, node_offset=None, phase=None)` is
  backwards-compatible; `node_offset` maps a tree's DFS index range onto
  the right slice of `graph['nodes']`, and `phase` lets `build_kg` run
  S1 (`pass1`) across every tree before any S6 (`pass2`) lookup of
  `module:<name>` for a cross-file instance.

## Deliverable B — `tests/test_invariants.py`

Seven graph-shape invariants, each one of which would have caught the
cross-tree merge bug:

| # | Invariant | What it catches |
|---|-----------|-----------------|
| 1 | Containment connectivity (every port/param/net/instance reachable from a module via has_port/has_param/has_net/instantiates) | A whole module disappearing from the graph |
| 2 | Instance closure (exactly one of_module out, one instantiates in) | `top.u_fifo --of_module--> fifo` being dropped |
| 3 | Port containment (exactly one has_port in from a module) | A module's ports getting reassigned to another tree's module |
| 4 | Param containment (exactly one has_param in from a module) | Param leakage across trees |
| 5 | Connects endpoints (both queryable, cross-module by path) | Port-connection edges landing on wrong-namespace ids |
| 6 | Hierarchical-path consistency (path prefix == owner module name) | Per-tree id collisions silently aliasing nodes |
| 7 | No orphan semantic edges (every drives/reads/connects/instantiates/of_module/sensitive_to endpoint is queryable) | The literal lift-collision symptom |

All seven pass against `build_kg([FIFO, TOP])`.

## Migration

- `tests/test_queries_multi.py` fixture switched from string concatenation
  to `build_kg(...)`. All existing assertions still pass — empirical proof
  that the new path is at least equivalent.
- `scripts/render_kgweave.py` switched to `build_kg(...)`. Re-rendered
  output: **38 entities, 62 triples** with `of_module` + `connects` +
  `has_port` edges all present (verified by grepping the emitted HTML).

## Status

- **81 tests green** (74 from kg-01, +7 invariants from inv-01).
- **score = 0** (no AST classes regressed).
- **Round-trip** byte-equal at the token level on top.sv preserved.
- **No regex** anywhere — every match is structural (class name +
  TokenKind, or hierarchical-path string equality).

## Commits

- `kg-01` (233bc38): `build_kg` + `lift`/`promote` kwargs + 3 TDD anchors.
- `inv-01` (5990f8f): seven structural invariants.
- `mig-01` (203e27a): migrate multi-module fixture + render script; add
  `phase=` to `promote()` so cross-file S6 resolves.
