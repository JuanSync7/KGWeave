# Eval queries — how we score the graph as queryable

Source under test: `fifo.sv` (single push/pop FIFO) + `top.sv` (instantiates `u_fifo`).
Graph API: `scripts/semantic.py` exposes `neighbors`, `find_by_name`,
`find_drivers`, `reads_of`, `cone_of_influence`, `queryable_nodes`.

Each eval is graded by (a) a programmatic assertion that the API returns the
expected set, and (b) a "why grep fails" note that justifies the cost of the
graph.

The queries are grouped by capability. **All 10 groups should pass on the
current state.** New rules / corpora extend this list, never shrink it.

---

## Group A — Identity & enumeration

### A1. List every module
- **NL:** "What modules are defined?"
- **Call:** `[n.name for n in queryable_nodes(g) if n.type == 'module']`
- **Expected:** `{'fifo', 'top'}`
- **Why grep fails:** `grep module` also matches `// module:` comments and string literals.

### A2. List ports of a module by direction
- **NL:** "What are the output ports of `fifo`?"
- **Call:** `[e.dst for e in neighbors(g, 'fifo', edge_type='has_port') if node(e.dst).direction == 'output']`
- **Expected:** `{'fifo.dout', 'fifo.full', 'fifo.empty'}`
- **Why grep fails:** input/output direction is on the port header several tokens away from the port name; regex over the port-list is exactly the brittleness we removed.

### A3. List all nets and their packed widths
- **NL:** "Which nets does `fifo` declare, and what is each net's width expression?"
- **Call:** for `e in neighbors(g, 'fifo', edge_type='has_net')`, read `node(e.dst).payload.packed_dim`.
- **Expected:** `mem → [WIDTH-1:0]`, `wr_ptr → [$clog2(DEPTH):0]`, `rd_ptr → [$clog2(DEPTH):0]`, `count → [$clog2(DEPTH):0]`
- **Why grep fails:** widths use `$clog2(DEPTH)` — same identifier appears in many other places; grep over the line of declaration doesn't disambiguate.

---

## Group B — Direct drives / reads

### B1. Who drives a port?
- **NL:** "What drives `fifo.dout`?"
- **Call:** `find_drivers(g, 'fifo.dout')`
- **Expected:** one `continuous_assign` node anchored at fifo.sv line 22.
- **Why grep fails:** `dout` appears in the port list, in the assign, and as a connection in `top.sv`; grep returns all three; the graph returns only the driver.

### B2. Who drives `fifo.full`?
- **Call:** `find_drivers(g, 'fifo.full')`
- **Expected:** one `continuous_assign` reading `count` and `DEPTH`.
- **Edge payload check:** `reads_of(g, 'fifo.full')` returns the same node — symmetric.

### B3. What reads `fifo.din`?
- **NL:** "Which logic reads `din`?"
- **Call:** `reads_of(g, 'fifo.din')`
- **Expected:** one `always_ff` block (the push branch writes `mem ← din`).
- **Why grep fails:** `din` is a port, appears in the port list, and as a `connects` peer in `top.sv`; grep returns all those false positives.

### B4. Does `wr_ptr` drive `rd_ptr`? (negative)
- **Call:** `'fifo.rd_ptr' not in [e.dst for e in neighbors(g, 'fifo.wr_ptr', edge_type='drives', direction='out')]`
- **Expected:** `True` (the two pointers are independent in this design).
- **Why grep fails:** "absence of evidence" is exactly the case grep can never answer reliably.

---

## Group C — Sensitivity / clocking

### C1. What clocks `fifo`'s sequential logic?
- **NL:** "What's the clock and reset for the always_ff?"
- **Call:** `[e.dst, e.payload['edge'] for e in neighbors(g, '<always_ff>', edge_type='sensitive_to')]`
- **Expected:** `[(fifo.clk, posedge), (fifo.rst_n, negedge)]`
- **Why grep fails:** `@(posedge clk or negedge rst_n)` parses as a tree of `BinaryEventExpression` + `SignalEventExpression`; regex would need to know about `or` and edge-event nesting.

### C2. Is the reset synchronous or asynchronous?
- **Call:** `node('<always_ff>').payload.reset_polarity`
- **Expected:** `active_low_async`
- **Why grep fails:** synchronous vs. async is determined by whether `rst_n` appears in the sensitivity list — a structural property, not a textual one.

---

## Group D — Cone of influence (BFS)

### D1. Backward cone of `fifo.full`
- **NL:** "Every signal that can affect `full`."
- **Call:** `cone_of_influence(g, 'fifo.full')`
- **Expected (superset):** `{count, DEPTH, always_ff, push, pop, rst_n, clk, full, empty}`
- **Why grep fails:** transitive closure across continuous-assign + always_ff + predicate guards is multi-hop; grep is one-hop at best.

### D2. Forward cone of `fifo.push`
- **NL:** "What does `push` affect inside `fifo`?"
- **Call:** forward BFS via `drives` from things `push` is `read_by`.
- **Expected (superset):** `{wr_ptr, count, mem, full}` (push gates the wr_ptr increment, the mem write, the count increment, and full is `count == DEPTH`)
- **Why grep fails:** has to understand `push && !full` as a predicate, the mem write inside the predicate, and the case-head expression for count.

### D3. Cone of `fifo.din`
- **Call:** forward cone of `fifo.din`.
- **Expected:** reaches `mem`, then `dout` via the `assign dout = mem[...]`.
- **Why grep fails:** the chain goes through array indexing, which grep can't follow as a typed edge.

---

## Group E — Bit-select / array-index identifier resolution

### E1. Identifiers used as array indices
- **NL:** "Which net is used as the index into `mem` in the dout assign?"
- **Call:** `[e.dst for e in neighbors(g, '<assign dout>', edge_type='reads') if e.payload.get('role') == 'index']`
- **Expected:** `fifo.rd_ptr`
- **Why grep fails:** `mem[rd_ptr[$clog2(DEPTH)-1:0]]` — `rd_ptr` is *inside* a bit-select inside an array index. The S4 rule lifts the base identifier so it's a real edge endpoint. The pre-pyslang regex era missed this (iter-013 fix).

### E2. Identifiers buried inside `$clog2` calls
- **NL:** "Which parameters does the width of `mem` depend on?"
- **Call:** forward BFS from `DEPTH` via `read_by` then filter to `width_of` payload.
- **Expected:** `DEPTH` appears in the width of `wr_ptr`, `rd_ptr`, `count`, and in `mem`'s unpacked dim. `WIDTH` appears in `mem`'s packed dim and in `din`/`dout`.
- **Why grep fails:** width expressions use `$clog2(DEPTH)`; grepping for `DEPTH` returns the parameter declaration AND every width AND the assign-`full` comparison.

---

## Group F — Constants and parameters

### F1. Default value of a parameter
- **Call:** `node('fifo.DEPTH').payload.default_value`
- **Expected:** `8`
- **Why grep fails:** would work textually here but breaks when defaults are expressions (`DEFAULT = 1 << LOG_DEPTH`).

### F2. Compare two literals
- **NL:** "What constant does the empty assign compare against?"
- **Call:** read the expression payload on the `assign empty` node.
- **Expected:** literal `0`.
- **Why grep fails:** the constant is buried inside the expression tree; grep can't tell `count == 0` from `count == DEPTH` without context.

---

## Group G — Hierarchy / instantiation

### G1. Modules instantiated in `top`
- **NL:** "What does `top` contain?"
- **Call:** `[e.dst for e in neighbors(g, 'top', edge_type='instantiates')]`
- **Expected:** `[top.u_fifo]`
- **Why grep fails:** would work for a single instance but breaks the moment there's an `\`include` or macro-generated instantiation; the graph uses the elaborated hierarchy.

### G2. What module is `top.u_fifo` an instance of?
- **Call:** `neighbors(g, 'top.u_fifo', edge_type='of_module')`
- **Expected:** `[fifo]`
- **Why grep fails:** the module name is a single token on the same line; OK for grep, but the moment overrides or `bind` are used, grep loses.

### G3. Full port-connection map of `top.u_fifo`
- **Call:** `[(e.payload['port'], e.src) for e in neighbors(g, 'top.u_fifo', edge_type='connects', direction='in')]`
- **Expected:** 8-entry mapping (`clk → top.clk`, `rst_n → top.rst_n`, `push → top.push`, `pop → top.pop`, `din → top.din`, `dout → top.dout`, `full → top.full`, `empty → top.empty`).
- **Why grep fails:** named connections (`.push(stim_push)`) require parsing the `.name(expr)` syntax; positional and wildcard connections require elaboration.

---

## Group H — Cross-hierarchy reasoning (the headline)

### H1. Cross-module forward cone
- **NL:** "If `top.push` toggles, which `fifo`-internal signals can be affected?"
- **Call:** forward cone of `top.push` traversing `connects` then `drives`/`reads`.
- **Expected:** `{top.u_fifo.push, fifo.wr_ptr, fifo.count, fifo.mem, fifo.full}` at minimum.
- **Why grep fails:** crosses the module boundary through the instantiation's `.push()` connection. Grep over `top.sv` and `fifo.sv` independently never makes that join.

### H2. Cross-module backward cone
- **NL:** "What in `top.sv` ultimately affects `fifo.count`?"
- **Call:** `cone_of_influence('fifo.count')`
- **Expected:** reaches `top.push`, `top.pop`, `top.rst_n`.
- **Why grep fails:** the chain is `fifo.count ← fifo.always_ff ← fifo.push ← (connects) ← top.u_fifo.push ← top.push`. Five hops, three of them across the instantiation boundary.

### H3. Which top-level nets are observed via output ports
- **NL:** "What downstream of `top.u_fifo.dout` exists in `top`?"
- **Call:** forward from `top.u_fifo.dout` over `connects`.
- **Expected:** `top.dout` (in this minimal example), and nothing else (no consumer logic inside `top`).
- **Why grep fails:** "and nothing else" is the negative answer grep cannot give reliably.

---

## Group I — Blob-required (payload-only)

These queries can only be answered by **opening the JSON payload** on a node
the graph has navigated to. They prove the structural-blob lives up to its
"no information lost" claim.

### I1. Operator of `assign empty`
- **Call:** read `node('<assign empty>').payload.expr.operator`
- **Expected:** `==`
- **Why graph alone can't:** operator structure is not an edge — it lives in the syntax-blob.

### I2. Bit-select range of `wr_ptr` index into `mem`
- **Call:** read the slice expression payload on the always_ff write to `mem`.
- **Expected:** `[$clog2(DEPTH)-1:0]` (or its AST equivalent).
- **Why graph alone can't:** the slice tree is purely syntactic, no semantic edge represents it.

### I3. Source line of any node
- **Call:** read `node(X).payload.source.line`
- **Expected:** matches the original `.sv` line (e.g. `fifo.full` declaration line ~11).
- **Why graph alone can't:** source range is metadata payload, not a graph property.

---

## Group J — Schema invariants

### J1. Every promoted node has a hierarchical path id
- **Call:** `all('.' in n.id or n.type == 'module' for n in queryable_nodes(g) if n.type != 'module_definition_root')`
- **Expected:** `True`
- **Purpose:** guards against regression of the sem-06 keying fix.

### J2. Round-trip is non-destructive after every promotion
- **Call:** re-emit and re-parse after `promote()`; class-stream + token-stream must equal the original.
- **Expected:** byte-equal.
- **Purpose:** guards against any future rule that accidentally mutates payloads.

### J3. No name-string lookup leaks
- **Call:** `assert graph['semantic_leaks'] == []`
- **Expected:** empty.
- **Purpose:** every identifier resolved through `Compilation`; nothing fell back to bare-name fuzzy matching.

---

## Scoring

A query passes if (a) the API call returns the expected set (or superset where
noted), AND (b) the call uses **typed edges / typed payload** — never a regex
or substring scan over node names.

Target on current corpus: **all 10 groups green** (~30 assertions). New rules
or new `.sv` files can only *grow* this list.

---

# Do we need Cypher?

Short answer: **not yet, and probably not for the LLM agent.**

## Three options on the table

### Option 1 — Typed Python tools (what we have)
Functions like `find_drivers`, `cone_of_influence`, `neighbors(node, edge_type, direction)`.

- **Pros:** discoverable via tool schema; LLM is constrained to valid shapes; returns typed objects; cheap; composable in Python.
- **Cons:** every new query pattern needs a function (or composition by the agent).
- **Verdict:** **best for the agent.** LLMs are much better at picking the right tool from a small typed menu than at writing valid Cypher.

### Option 2 — Cypher (Neo4j-style declarative)
`MATCH (a:port {name:'dout'})<-[:drives]-(x) RETURN x`

- **Pros:** human-readable for ad-hoc analysis; well-known by some engineers; expressive for arbitrary subgraph patterns.
- **Cons:** requires a parser/executor (Neo4j or `pycypher` or hand-rolled); error messages from malformed queries are noisy; LLM-generated Cypher frequently subtly wrong; runtime errors instead of compile-time tool-schema rejection.
- **Verdict:** **overkill at this scale.** Useful eventually for *human* exploration of large graphs, not as the agent's primary interface.

### Option 3 — Pattern-dict escape hatch
A single `graph_query(pattern)` tool where `pattern` is a small typed dict (think GraphQL-on-graphs but minimal):
```python
{
  "match": {"type": "port", "name": "fifo.dout"},
  "follow": [{"edge": "drives", "direction": "in"}, {"edge": "reads"}],
  "return": "name"
}
```
- **Pros:** the LLM stays inside a typed schema (no string parsing) but gets arbitrary multi-hop patterns the tool author didn't pre-bake.
- **Cons:** another mini-DSL; needs its own docs.
- **Verdict:** **good as a 20% escape hatch** behind the named-function 80%.

## Recommendation

Two-tier query surface:

1. **80% — named, typed Python tools.** Keep adding them per common question: `find_drivers`, `cone_of_influence`, `port_connections`, `instances_of`, `sensitivity_of`, `width_of`, `default_value_of`. The eval suite above is the source of truth for "common."
2. **20% — `graph_query(pattern_dict)` escape hatch.** Implemented as a tiny pattern walker over the existing nodes/edges (50 lines). Used when the LLM has a multi-hop question no named tool covers.

**Defer Cypher** until two things happen:
- A *human* needs to do ad-hoc exploration at the REPL (then a notebook + `nx_query` shim is usually enough).
- The graph gets large enough (100k+ nodes) that a real query optimiser matters. At today's scale (~hundreds of nodes per module) any traversal is microseconds.

The current `neighbors` + named convenience functions already cover ~90% of the eval suite. Add `graph_query` once we hit the first eval that *can't* be expressed in those.
