# SV Graph Expansion — Phases 1..7 Result

Branch: `autoresearch/ast-roundtrip-2026-05-12`

Baseline: 81 tests passing, structural score=0, semantic rules S1..S6,
`build_kg` multi-file path, 7 structural invariants.

Final state: **105 tests passing, score=0, semantic rules S1..S12, 8
structural invariants**, four-file corpus + a testbench, 75 distinct AST
classes all round-trip byte-equal.

## Per-phase summary

### Phase 1 — Parameter overrides

* **Corpus:** widened `top.sv` to instantiate three fifos —
  `u_fifo` (no override), `u_fifo_a #(.DEPTH(16), .WIDTH(32))` and
  `u_fifo_b #(.DEPTH(8), .WIDTH(8))` — each wired to its own top-level signal
  group.
* **New rule:** **S7 ParameterValueAssignmentSyntax → `param_override`**.
  Each named override becomes an edge from the instance to the child
  module's `param` node, with the resolved value text in the edge payload.
* **Public query:** `param_overrides(instance_path) → {name: value}`.
* **New invariant (#8):** every `param_override` target is a `param` node
  belonging to the instance's `of_module` side.
* **New round-trip iters:** 019 ParameterValueAssignmentSyntax,
  020 NamedParamAssignmentSyntax.
* **Tests:** 85 green (+4).

### Phase 2 — `always_comb`

* **Corpus:** added `output logic [1:0] status` to `fifo.sv` plus an
  `always_comb` decoder.
* **New rule:** **S8 ProceduralBlock(always_comb)** — role `always_comb`,
  emits `drives`/`reads` exactly like S3 minus `sensitive_to`. No new AST
  class (pyslang's `kind` is `AlwaysCombBlock`).
* **Tests:** 86 green (+1 cone-of-influence test reaching DEPTH/count
  through the new always_comb).

### Phase 3 — Package + typedef enum

* **Corpus:** new file `fifo_pkg.sv` containing
  `typedef enum logic [1:0] { EMPTY, NORMAL, FULL } fifo_status_e;` plus
  a `parameter int DEFAULT_DEPTH`. `fifo.sv` re-typed `status` to
  `fifo_status_e` and `import fifo_pkg::*`.
* **build_kg path:** all three fixtures (`test_invariants`,
  `test_queries_multi`, `test_eval_queries`) migrated to
  `build_kg([PKG, IFACE, FIFO, TOP])`. The eval-queries fixture also
  dropped its legacy string-concat construction.
* **New rules:** **S9** distinguishes PackageDeclaration (role `package`),
  promotes TypedefDeclaration (role `typedef`, `has_typedef` edge) and the
  enum value declarators (role `enum_value`, `has_enum_value` edge).
* **Public query:** `package_of(typedef_path) → package_name`.
* **New round-trip iters:** 021..025 covering TypedefDeclaration, EnumType,
  ParameterDeclarationStatement, PackageImportDeclaration,
  PackageImportItem, NamedType.
* **Invariant changes:** `_OWNER_ROLES = {module, package, interface}`;
  containment edges extended to include `has_typedef`/`has_enum_value`.
* **Tests:** 94 green (+8).

### Phase 4 — Function

* **Corpus:** added `function automatic logic [$clog2(DEPTH):0] next_ptr(...)`
  to `fifo.sv`; `wr_ptr`/`rd_ptr` increments now call `next_ptr(...)`.
* **New rule:** **S10 FunctionDeclaration → role `function` + `has_function`
  edge** + `calls` edge from any always block invoking the function. The
  pass-2 walker is gated to skip rule application inside a
  FunctionDeclarationSyntax subtree (so the function's local symbols don't
  leak as orphan reads/drives).
* **New round-trip iter:** 026 (FunctionDeclaration, FunctionPrototype,
  FunctionPortList, FunctionPort).
* **Tests:** 96 green (+2).

### Phase 5 — Interface + modport

* **Corpus:** new file `fifo_if.sv` with three modports
  (`producer`/`consumer`/`dut`) and a 4-port modport-named-port shape;
  `top.sv` now instantiates `fifo_if #(.WIDTH(32)) u_if(...)`.
* **New rules:** **S11** routes InterfaceDeclaration to role `interface`
  (with `interface:` name-index prefix) and promotes every ModportItem to
  role `modport` with a `has_modport` edge and a per-signal
  `directions` payload. `_rule_s6`'s type lookup now also accepts
  `interface:` and bare-name name-index keys.
* **Public query:** `modports_of(interface_name) → sorted list of names`.
* **New round-trip iter:** 027 (ModportDeclaration, ModportItem,
  ModportSimplePortList, ModportNamedPort).
* **Tests:** 100 green (+4).

### Phase 6 — Generate-for

* **Corpus:** `top.sv` gains `parameter int NUM_FIFOS = 2;` and
  `generate for (genvar i = 0; i < NUM_FIFOS; i++) begin: gen_fifos
  fifo u_fifo_gen(...); end endgenerate`.
* **New rule:** **S12 LoopGenerateSyntax → role `generate_loop`**, with
  `iter_count` payload sourced from the elaborated GenerateBlockArraySymbol.
  Each `entries[i]` becomes a synthetic `generate_block` node with the
  elaborated hierarchical path (`top.gen_fifos[0]`, `top.gen_fifos[1]`),
  and every `InstanceSymbol` under it becomes a synthetic `instance` node
  carrying its full elaborated path. Synthetic nodes use `gen:` id prefix
  so they cannot collide with lift-produced ids. The syntactic
  HierarchyInstantiation under the loop is **suppressed** by an
  `in_generate` counter in pass2 to avoid double-counting.
* **New invariant edges:** `has_generate` (module → loop) and
  `contains_block` (loop → block). Owner propagation extended to chain
  through these edges.
* **Public query:** `instances_of('fifo')` now returns the union of named
  and elaborated paths.
* **New round-trip iter:** 028 (GenerateRegion, LoopGenerate, GenerateBlock,
  NamedBlockClause, PostfixUnaryExpression).
* **Tests:** 102 green (+2).

### Phase 7 — Testbench (corpus stress)

* **Corpus:** new file `tb_fifo.sv` instantiating `top u_dut(...)` with a
  free-running clock (`forever #5 clk = ~clk;`), reset sequence, a
  push/pop pulse, and `$display`. Added to the build_kg invariants fixture
  so all 8 invariants run against the testbench too.
* **No new rules** — every construct (InitialBlock, DelayControl,
  ForeverStatement, SystemCall) is handled by the class-generic
  structural lift. Only DelaySyntax + ForeverStatementSyntax appeared as
  new pyslang classes; both round-trip byte-equal under the universal
  emitter.
* **New round-trip iter:** 029 (DelaySyntax + ForeverStatementSyntax).
* **Inv-6 refinement:** synthetic `gen:` ids carry full elaborated
  hierarchical paths (e.g. `tb_fifo.u_dut.gen_fifos[0]`) whose first
  dotted component is the top instance, not the declaring module — they
  are excluded from the path-prefix check (their ids are namespace-safe
  by construction).
* **Tests:** 105 green (+3).

## Aggregate counts

| Metric | Baseline | Final |
|--------|----------|-------|
| Tests passing | 81 | **105** |
| Structural score | 0 | **0** |
| AST classes covered | 52 / 52 | **75 / 75** |
| Semantic rules | S1..S6 | **S1..S12** |
| Structural invariants | 7 | **8** |
| Corpus files | 2 (fifo, top) | **5** (fifo_pkg, fifo_if, fifo, top, tb_fifo) |
| Edge types | 7 | **13** (added `param_override`, `has_typedef`, `has_enum_value`, `has_modport`, `has_function`, `calls`, `has_generate`, `contains_block`) |
| Roles | module/port/param/net/instance + continuous_assign/always_ff/identifier_select/system_call | + always_comb, package, typedef, enum_value, modport, function, interface, generate_loop, generate_block |

## Operational invariants preserved

* Byte-equal token-stream round-trip on every file in the corpus,
  every iteration.
* `score.py` stays at 0 over the combined corpus.
* No regex anywhere — every match is structural (class name + TokenKind
  + hierarchical-path string equality).
* No semantic leaks (`g['semantic_leaks'] == []`) on the full
  multi-file graph.
