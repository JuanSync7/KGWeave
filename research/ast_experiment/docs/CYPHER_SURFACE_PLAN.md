# Plan — ship the Cypher query surface

**Decision (settled):** adopt Cypher (embedded **kuzu**) as the primary surface for
non-trivial graph traversal, measured to win 5/6 across all model tiers vs the
pattern-dict's 3/2/2 (`evals/cypher_ab/CYPHER_VS_DICT_RESULTS.md`).

**Shape of the ship — Cypher is the default surface; the DSL is retired:**

- **Cypher (kuzu) is THE query surface.** `cypher_query` is the standard, documented
  entry point. The `graph_query` pattern-dict DSL is **fully retired** (deleted), not
  kept as a legacy path — two query surfaces drifting is worse than one migration.
- **kuzu is a CORE dependency**, not an optional extra. KGWeave ships to RagWeave, so
  every consumer pulls an embedded graph engine. This is the one accepted cost of
  making Cypher the standard: it burns the dict's "zero-engine" property. Embedded
  kuzu is a small library (not a server), so the cost is a dependency, not ops.
- **Two-tier retirement.** The *public surface* becomes Cypher-only. The *Python query
  functions* (`neighbors`, `find_by_name`, `find_drivers`, `cone_of_influence`, …) are
  **demoted to internal test oracles** — NOT deleted — because the Cypher eval computes
  its independent ground truth with them. Deleting them would make the tests circular
  (Cypher checking Cypher).
- The one curated transitive walk (`cone_of_influence`) is also re-homed as a **saved
  Cypher query / UDF** for runtime use — its Python twin survives only as the eval oracle.

**Out of scope here:** moving any of this into `src/knowledge_graph/` (that rides
the broader extraction in `docs/MIGRATION.md`); growing the saved-query library beyond
the one walk we already validated.

**Target location:** `research/ast_experiment/src/semantic/queries/` (where
`graph_query.py` and the named tools already live; the experiment's invariants
apply). Tests co-locate in `research/ast_experiment/tests/queries/`.

---

## The execution loop every slice runs (TDD inside Ralph)

Each slice is handed to one subagent as a **self-contained prompt** (the slice
section below IS that prompt — it names every file, command, and constraint). The
subagent runs a **Ralph loop**: the slice spec is fixed; the workspace state carries
forward across iterations; the loop converges when a deterministic **acceptance
command** exits 0.

```
RALPH LOOP (per slice):
  repeat until ACCEPTANCE exits 0, or iteration budget exhausted (then ESCALATE):
    1. TDD RED    — write/extend the slice's tests so they express the goal and FAIL.
    2. TDD GREEN  — write the minimum code to pass them.
    3. TDD REFACTOR — clean up; tests stay green.
    4. RUN ACCEPTANCE — the slice's own tests + the shared INVARIANT GATE.
    5. If green: STOP, report literal command output. If red: read failures, loop.
  Ralph invariants:
    - The spec/prompt does NOT change between iterations — only the code does.
    - Never weaken a test to pass. Never delete a failing assertion to go green.
    - Report the LITERAL final command output (the score-hallucination rule, CLAUDE.md §3).
    - If stuck for 3 iterations on the same failure, STOP and escalate with the diff + output.
```

### Shared INVARIANT GATE (every slice's acceptance includes this, unchanged)

These are the project's hard invariants — a slice is not done until ALL hold:

```bash
# 1. Full suite green
uv run pytest research/ast_experiment/ -q
# 2. Score must NOT regress vs parent commit (coverage metric ~33, NOT zero)
uv run python research/ast_experiment/scripts/score.py | head -2
# 3. Byte-equal round-trip (subset of the suite, but assert it explicitly)
uv run pytest research/ast_experiment/tests/test_roundtrip.py -q
# 4. NO regex in src/semantic/  (must print nothing)
! grep -rnE '^\s*(import re|from re )' research/ast_experiment/src/semantic/
# 5. No duplicate SyntaxKind / 6. bucket totals == 536
uv run python research/ast_experiment/scripts/inventory.py | tail -5
```

**S-rule constraint (unchanged):** rules may ONLY mutate `node["semantic"]` or append
to `graph["edges"]`. The Cypher surface is a **read/query** layer — it must not
mutate the graph at all. Loading into kuzu is a projection, not a write-back.

---

## Vertical slices

Each slice cuts top-to-bottom (graph → load → query → typed result → public API) and
delivers something demonstrable on its own. A subagent picking up slice N can assume
slices < N are merged and green.

---

### Slice 0 — Walking skeleton (the pipe end-to-end)

**Validable end goal:** one trivial Cypher query runs through the *public* surface and
returns a *typed* result, with kuzu lazy-loaded. Proves the whole pipe before any
capability is added.

**Build:**
- `src/semantic/queries/cypher_query.py` — `cypher_query(graph, query: str) -> CypherResult`.
  Lazy-imports kuzu; loads the graph via a promoted `kuzu_load` (port the proven
  `evals/cypher_ab/kuzu_load.py` into `src/semantic/queries/_kuzu_load.py`, no regex).
- `CypherResult` Pydantic model: `columns: list[str]`, `rows: list[dict]`, plus a
  `.scalars()` / `.values()` convenience matching the A/B's frozenset semantics.
- Expose `cypher_query` + `CypherResult` from `src/semantic/__init__.py` (facade only).

**Tests (`tests/queries/test_cypher_skeleton.py`):**
- unit: `_kuzu_load(graph)` builds a connection; node table `N` has the promoted
  node count; structural `child` edges are NOT loaded; `_unresolved` targets skipped.
- integration: `cypher_query(graph, "MATCH (n:N) RETURN n.name LIMIT 1")` returns a
  `CypherResult` with one column, one row.
- e2e: import `cypher_query` *through the facade* (`from research.ast_experiment.src.semantic import cypher_query`) and run the same query.

**ACCEPTANCE:** `uv run pytest research/ast_experiment/tests/queries/test_cypher_skeleton.py -q` green **+ INVARIANT GATE**.

---

### Slice 1 — Core read capability (the shapes that won the A/B)

**Validable end goal:** the surface correctly answers all five differentiating query
shapes — single-hop containment, **edge-union**, **multi-column return**,
**aggregation**, and 2-hop dataflow — returning results equal to independent truth.

**Build:** flesh out result projection in `cypher_query.py` — multi-column rows,
`count()` scalars, `DISTINCT`, edge-union `-[:a|b]->`. (Most is kuzu-native; this slice
proves it through our types, no new query DSL.)

**Result contract — faithful projection + conditional hydration (settle here, RagWeave
imports it):** `CypherResult{columns: list[str], rows: list[dict[str, Any]]}` where each
cell is **whatever the query projected**, dispatched on kuzu's column type:
- scalar projection (`s.name`, `count(p)`, `i.path`) → a scalar (`str|int|float|bool|None`).
- node-valued projection (`RETURN s`) → a `SemanticNode` Pydantic model
  (`id, role, name, path, attributes`) **hydrated by id from `graph["nodes"]`** — NOT the
  flattened kuzu row (which loses nested `attributes`).
- `.scalars()` convenience returns a flat list for the common single-column scalar case
  (matches the frozenset semantics the eval truth functions already use).

The card (Slice 3) keeps teaching **scalar projection** as the default — it is what all
three model tiers wrote correctly in the A/B; node-return is available for structured
consumers, not something models are steered toward (protects the accuracy driver).

**Tests (`tests/queries/test_cypher_core.py`)** — reuse the A/B truth functions as the
oracle (import from `evals/cypher_ab/questions.py` or copy the `truth_fn`s):
- Q1 methods of `cls_pkg.data_xact` (single hop)
- Q2 ports-OR-nets of `fifo_if` (`-[:has_port|has_net]->`) — **edge-union**
- Q4 `(instance path, module name)` pairs under `top` (`RETURN i.path, m.name`) — **multi-column**
- Q5 count ports of `fifo` (`count(p)`) — **aggregation**
- Q6 signals feeding the driver of `fifo.full` (2-hop `<-[:drives]-()-[:reads]->`)
- Each asserts the result set equals the question's `truth_fn(graph)` (name OR path projection accepted, per the A/B's `accept_fns`).

**ACCEPTANCE:** `uv run pytest research/ast_experiment/tests/queries/test_cypher_core.py -q` green **+ INVARIANT GATE**.

---

### Slice 2 — Fail loud (the engine's honesty surface)

**Validable end goal:** every malformed or schema-violating query yields a **structured,
helpful** error — never a raw kuzu stack trace, never a silent empty result that reads
as "no matches." This is the property we trade the dict's can't-malform guarantee for;
make it earn its keep.

**Build:**
- `CypherError` Pydantic model: `kind` (`syntax | unknown_label | unknown_edge | unknown_property | engine`), `message`, `suggestion: str | None`.
- A pre-flight validator that checks label/edge/property names in the query against the
  **live vocabulary** (65 roles, 70 edges) and returns a suggestion on a near-miss
  (e.g. unknown `has_field` → "did you mean `has_class_property`?"). Cheap string
  distance only — **no regex** (CLAUDE.md §4 / invariant gate item 4).
- `cypher_query` raises `CypherError` (or returns it in a typed envelope — decide and
  document) for bad input; genuine engine errors are wrapped, not leaked.

**Tests (`tests/queries/test_cypher_fail_loud.py`):**
- unit: unknown edge `has_field` → `CypherError(kind=unknown_edge, suggestion="has_class_property")`.
- unit: unknown label `:Node` → `unknown_label`.
- unit: syntax error `MATCH (n:N RETURN` → `syntax`, no traceback leaks.
- property/system: a list of ~10 hand-written bad queries — **none** crashes the process,
  **none** returns a silent empty success; each returns a typed error.
- regression: a *valid* query with zero matches returns an empty-but-successful
  `CypherResult` (empty ≠ error — don't over-trigger fail-loud).

**ACCEPTANCE:** `uv run pytest research/ast_experiment/tests/queries/test_cypher_fail_loud.py -q` green **+ INVARIANT GATE**.

---

### Slice 3 — Generated, drift-proof schema card

**Validable end goal:** the Cypher schema card is **generated from the live vocabulary**
and a test proves it cannot drift — every edge/role in the card exists in the graph,
and every live edge/role appears in the card. The card is the one teaching artifact an
LLM is handed; a stale card silently produces fluent-but-wrong queries.

**Build:**
- `scripts/gen_cypher_card.py` — emits `docs/card_cypher.md` from the live vocabulary:
  node table `N{role,name,path,attributes}`, full edge list grouped by purpose
  (containment / relationship), the `path`-is-identity + name-vs-path convention, and
  a recipes section (the Slice-1 shapes as worked examples + the saved-query names).
- Regenerate `docs/card_cypher.md` as a committed artifact.

**Tests (`tests/queries/test_cypher_card.py`):**
- bidirectional no-drift: parse `card_cypher.md`; assert `card_edges == live_edges` and
  `card_roles == live_roles` (set equality, both directions — a missing OR extra name fails).
- the card's recipe queries each parse and execute without `CypherError` (the recipes
  are real, runnable Cypher, not illustrative pseudo-code).
- generator is deterministic: running it twice produces byte-identical output.

**ACCEPTANCE:** `uv run pytest research/ast_experiment/tests/queries/test_cypher_card.py -q` green **+ INVARIANT GATE**.

---

### Slice 4 — Saved-query library (port the cone, keep the menu tiny)

**Validable end goal:** the bespoke transitive walk Cypher can't express inline
(`cone_of_influence` — the dict's sole A/B win) ships as a **named, parameterized
saved query** and returns the **same set** as the Python `cone_of_influence`.

**Build:**
- `src/semantic/queries/saved.py` — a registry: `saved_query(graph, name, **params) -> CypherResult`.
- First (and only, for now) entry: `cone_of_influence(target=...)` implemented as a
  parameterized Cypher query or a kuzu UDF that reproduces the alternating
  `sig <-drives- assign -reads-> sig` + `connects` fan-in walk.
- **Promotion bar (document it in the module docstring):** a walk earns a saved query
  ONLY if it is *recurring AND not cleanly expressible inline*. Anything expressible
  inline becomes a **recipe in the card** (Slice 3), never a tool. This is the guard
  against rebuilding the dict's tool-selection burden.

**Tests (`tests/queries/test_cypher_saved.py`):**
- equivalence: `saved_query(g, "cone_of_influence", target="fifo.count")` set ==
  `cone_of_influence(g, "fifo.count")` projected to paths (the A/B truth for Q3).
- the saved query is registered, discoverable by name, and rejects unknown names with
  a typed error (not a KeyError).

**ACCEPTANCE:** `uv run pytest research/ast_experiment/tests/queries/test_cypher_saved.py -q` green **+ INVARIANT GATE**.

---

### Slice 5 — Typed facade + core dependency (the RagWeave contract)

**Validable end goal:** the surface is consumable by RagWeave exactly like the rest of
KGWeave — **through the package facade only**, Pydantic-typed, with kuzu as a **core
dependency** (Cypher is the default surface, so the engine is always present).

**Build:**
- `pyproject.toml`: add `kuzu>=0.11` as a **core** dependency (not an extra). Cypher is
  the standard surface; the engine ships with the package.
- Facade in `src/semantic/__init__.py` (and the package `__init__.py` contract): export
  `cypher_query`, `saved_query`, `CypherResult`, `CypherError`. No internal-module imports
  required by a consumer.
- The facade no longer exports `graph_query` / `queryable_nodes` / the tool menu — those
  are removed in Slice 7 (retirement). This slice establishes the *new* public surface.

**Tests (`tests/queries/test_cypher_facade.py`):**
- contract: every public Cypher name imports from the facade; assert no test reaches into
  `queries._kuzu_load` etc. (import-surface test).
- typing: `CypherResult` / `CypherError` round-trip through Pydantic `model_validate` /
  `model_dump` (RagWeave consumes typed clients).

**ACCEPTANCE:** `uv run pytest research/ast_experiment/tests/queries/test_cypher_facade.py -q` green **+ INVARIANT GATE**.

---

### Slice 6 — Living accuracy regression gate (optional; seeds the self-improving loop)

**Validable end goal:** the A/B becomes a **repeatable system test** with an
**auto-generated** question set, so the N=6 result is continuously re-validated at scale
and any future card/schema change that hurts LLM accuracy is caught. This is the
foundation the self-improving loop later sits on — but it is itself just a test gate.

**Build:**
- `evals/cypher_ab/generate_questions.py` — sample subgraphs → emit `(question, truth)`
  pairs across the differentiating axes (containment, edge-union, multi-column,
  aggregation, dataflow). Grows N=6 → N=hundreds.
- **train/test split**: a held-out set the gate scores against (defends against future
  card-overfitting).
- Wire `run_ab.py` to consume the generated set; record a baseline accuracy.

**Tests / system gate (`tests/queries/test_cypher_system.py`):**
- system e2e: load corpus → generate N questions → execute every `cypher_oracle`
  through the *public* `cypher_query` → assert ceiling accuracy == 100% on the
  generated set (the surface can express what we claim it can).
- the blind-panel replay files still grade (oracle path unchanged).
- baseline-accuracy assertion with a floor (no-regression, mirroring the score gate).

**ACCEPTANCE:** `uv run pytest research/ast_experiment/tests/queries/test_cypher_system.py -q` green **+ INVARIANT GATE**.

---

### Slice 7 — Retire the `graph_query` DSL (cutover to Cypher-only)

**Validable end goal:** the `graph_query` pattern-dict DSL no longer exists in the public
surface or the codebase; every former caller is migrated; the full suite is green with
the DSL gone. The repo has exactly **one** query surface.

**Two-tier rule (the crux — get this right or tests go circular):**
- **DELETE (public DSL):** `src/semantic/queries/graph_query.py` (the `graph_query` /
  `queryable_nodes` walker AND the synthetic `contains` edge / `_edge_type_matches` —
  this also closes the rejected containment experiment); facade exports of these.
- **KEEP, demote to internal test oracle (do NOT delete):** `neighbors`, `find_by_name`,
  and the walks used as independent truth in `evals/cypher_ab/questions.py`
  (`find_drivers`, `cone_of_influence`, `forward_cone`). They stay importable for tests
  but leave the public/recommended surface (removed from the card, not advertised).

**Migration checklist (every former `graph_query` caller — the slice is not done until
this list is empty):**
- `src/semantic/queries/__init__.py`, `src/semantic/__init__.py` — remove `graph_query`/
  `queryable_nodes` exports.
- `tests/queries/test_contains_edge.py` — **delete** (tested the now-gone `contains` edge).
- `tests/queries/test_multi.py` (3 `graph_query` tests) — **migrate to `cypher_query`**.
- `tests/rules/test_port_direction.py`, `test_of_type.py`, `test_assertion_checks.py`,
  `test_dataflow.py` — these used `graph_query` only as an assertion convenience; migrate
  to direct `neighbors()` / `find_by_name()` (no engine needed in a unit rule test).
- `tests/test_structure.py` — drop `graph_query` from the expected-exports list; add the
  Cypher names.
- `tests/queries/test_eval.py`, `tests/evals/test_llm_traversal.py`,
  `evals/llm_traversal/` (whole dir: `harness.py`, `cases.py`, `run_eval.py`) —
  **retire** (the DSL-ceiling eval is superseded by `evals/cypher_ab`). Remove or archive;
  if archived, ensure pytest does not collect it.
- `docs/SCHEMA_CARD.md` — retire the dict card (it documented the DSL + tool menu);
  `card_cypher.md` (Slice 3) is the sole card.

**Tests:**
- a guard test asserting `graph_query` is **not importable** from the facade (the surface
  is gone, not just hidden).
- grep-style structural test (or extend `test_structure.py`): no `from ...graph_query import`
  remains anywhere under `tests/` or `src/` except the deleted module.
- the migrated rule tests still assert the same rule behavior (behavior unchanged; only
  the assertion mechanism changed).

**ACCEPTANCE:** `uv run pytest research/ast_experiment/ -q` green with `graph_query.py`
deleted **+ INVARIANT GATE** + the not-importable guard passes.

---

## Whole-feature system test (the cross-slice acceptance)

Done = a fresh checkout can, **through the facade only**:

```python
from research.ast_experiment.src.semantic import cypher_query, saved_query, CypherResult, CypherError
from research.ast_experiment.src.build import build_kg
g, _, _ = build_kg(CORPUS)

cypher_query(g, "MATCH (i:N {name:'fifo_if'})-[:has_port|has_net]->(s:N) RETURN s.name")  # edge-union
cypher_query(g, "MATCH (f:N {name:'fifo'})-[:has_port]->(p:N) RETURN count(p)")            # aggregation
saved_query(g, "cone_of_influence", target="fifo.count")                                   # curated walk
cypher_query(g, "MATCH (n:N {name:'nope'})-[:has_field]->(x) RETURN x")                     # → CypherError(suggestion=...)
```

…and: kuzu absent → `CypherUnavailable` with install hint (package still imports);
the pattern-dict surface and all named tools still pass their existing tests; the full
INVARIANT GATE is green; nothing in `src/` mutates the graph; score has not regressed.

---

## Sequencing & dependencies

- **0 → 1 → 2** are strictly ordered (skeleton, then capability, then error surface).
- **3 (card)** depends only on the live vocabulary + Slice-1 recipes — can run in
  parallel with 2 once 1 is merged.
- **4 (saved query)** depends on 1 (needs working Cypher execution).
- **5 (facade + core dep)** depends on 1–4 existing as the surface to expose.
- **7 (retire DSL)** depends on 1 (callers in `test_multi.py` migrate to Cypher) and 3
  (the dict card is retired in favor of `card_cypher.md`). Comes AFTER the Cypher surface
  is proven so any migration that wants Cypher has it. Do this BEFORE 6 so the system gate
  runs against the final single-surface world.
- **6 (system gate)** is last and optional; depends on 1–5 and 7.

Critical path: 0 → 1 → 2 → 5 → 7. Slices 3 and 4 branch off after 1 and rejoin at 5/7.

## Risks & the guards already baked into the slices

| risk | guard | where |
|---|---|---|
| kuzu is now a core dep on RagWeave | accepted cost of Cypher-as-default; embedded lib not a server; documented in Slice 5 | Slice 5 |
| retiring the DSL breaks the eval's independent truth | two-tier retirement: delete public DSL, KEEP Python walks as internal test oracles | Slice 7 |
| a former `graph_query` caller is missed → silent gap | explicit migration checklist + not-importable guard + grep structural test | Slice 7 |
| we accidentally rebuild the losing DSL | saved-query promotion bar (recurring AND inexpressible); prefer recipe | Slice 4 |
| card drifts → fluent-but-wrong queries | bidirectional no-drift test; generated, not hand-authored | Slice 3 |
| fail-loud over-triggers (empty≠error) | explicit "valid-but-empty stays success" test | Slice 2 |
| N=6 doesn't hold at scale | auto-generated eval + held-out floor | Slice 6 |
| Cypher mutates / breaks invariants | read-only projection; full INVARIANT GATE every slice | all |
