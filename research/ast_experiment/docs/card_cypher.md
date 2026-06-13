# SV Graph Schema Card — Cypher surface

The one-page contract for traversing the SystemVerilog knowledge graph **with
Cypher** and getting accurate answers without grep. The graph is loaded into an
embedded property-graph DB; you query it with standard Cypher. Everything here is
measured from the live graph over the corpus, not aspirational.

> The graph has **65 node roles** and **67 semantic relationship types**.

---

## Schema (what to MATCH on)

There is **one node label**, `N`, with these properties:

| property | meaning |
|---|---|
| `id` | opaque unique id (rarely needed) |
| `role` | the node's kind — see Roles section |
| `name` | bare identifier (`count`, `fifo`) |
| `path` | hierarchical identity (`fifo.count`, `top.u_fifo`) — **the key you usually match on** |
| `direction` | for ports/modport items: `"input"`/`"output"`/`"inout"` (else null) |

Relationships are **typed** — the relationship type IS the semantic edge name
(`-[:reads]->`, `-[:has_method]->`, `-[:of_module]->`). See Edges section.

Node-valued returns (e.g. `RETURN s`) are hydrated to
`SemanticNode{id, role, name, path, attributes}` — the full nested attributes dict
is restored from the graph by node id (not the flattened kuzu row).

Standard Cypher applies: `WHERE`, `IN`, `NOT`, `count()/collect()`, multiple
`RETURN` columns, variable-length `-[:reads*1..3]->`, `DISTINCT`, etc.

---

## Roles

There are **65 node roles**. Match with `{role:'…'}` or `WHERE n.role IN [...]`.

| Family | Roles |
|---|---|
| **Design units / scopes** | `checker`, `class`, `interface`, `module`, `package`, `primitive_instance`, `program` |
| **Ports & signals** | `genvar`, `local_var`, `net`, `net_decl`, `param`, `port`, `port_concat`, `port_reference`, `type_param`, `user_defined_net_decl` |
| **Behavioral logic** | `always`, `always_comb`, `always_ff`, `continuous_assign`, `event_trigger`, `function`, `function_port`, `function_prototype`, `identifier_select`, `method`, `method_prototype`, `procedural_assign`, `procedural_block`, `procedural_deassign`, `procedural_force`, `procedural_release`, `system_call` |
| **Hierarchy** | `generate_block`, `generate_loop`, `instance` |
| **Types** | `enum_value`, `struct_member`, `typedef`, `typedef_forward`, `union_member` |
| **Verification** | `assertion`, `assertion_item_port`, `constraint`, `coverage_bins`, `covergroup`, `coverpoint`, `cross`, `default_disable`, `inline_constraint_block`, `let_decl`, `property`, `sequence` |
| **Interface plumbing** | `clocking`, `clocking_item`, `interface_port`, `modport` |
| **Externs / DPI** | `dpi_import`, `extern_decl`, `extern_udp` |
| **Other** | `checker_data`, `checker_instance`, `class_property`, `time_units` |

---

## Edges

There are **67 semantic relationship types**.
Structural `child` edges are NOT loaded; unresolved-target edges are skipped.

### Containment — scope X owns member Y (`has_*`)

`has_assertion`, `has_assertion_item_port`, `has_bins`, `has_checker_data`, `has_checker_instance`, `has_class`, `has_class_property`, `has_clocking`, `has_clocking_item`, `has_constraint`, `has_covergroup`, `has_coverpoint`, `has_cross`, `has_default_disable`, `has_dpi_import`, `has_enum_value`, `has_event_trigger`, `has_function`, `has_function_port`, `has_generate`, `has_genvar`, `has_inline_constraint`, `has_let`, `has_local_var`, `has_member`, `has_method`, `has_modport`, `has_net`, `has_net_decl`, `has_param`, `has_port`, `has_primitive_instance`, `has_procedural_assign`, `has_procedural_force`, `has_property`, `has_sequence`, `has_timeunits`, `has_type_param`, `has_typedef`, `has_user_defined_net_decl`.

The child's `role` tells you what kind of member it is. To get several kinds at
once, union the types or filter on role:
`MATCH (i:N {name:'fifo_if'})-[:has_port|has_net]->(s:N) RETURN s.name`.

### Relationship edges

**Dataflow** — how values move:

`aliases`, `checks`, `connects`, `drives`, `groups_net`, `groups_port_ref`, `reads`, `sensitive_to`, `triggers`.

**Hierarchy & resolution** — how names bind:

`bound_into`, `calls`, `declares`, `exports_all`, `extends`, `implements`, `imports`, `imports_item`, `instantiates`, `of_checker`, `of_module`, `of_type`, `prototypes`, `references_interface`.

**Overrides & misc:**

`contains_block`, `default_clocking`, `dpi_exports`, `param_override`.

---

## Conventions

- `path` is identity: always prefer matching on `path` over bare `name`
  when you know the hierarchical location (`fifo.full`, not `full`).
- Name-vs-path projection: both `RETURN n.name` and `RETURN n.path` are valid;
  choose whichever granularity the question demands.
- Unresolved targets (forward/external refs) have no node row — a relationship
  to them simply matches nothing.
- For complex traversals like transitive fan-in (alternating `signal<-[:drives]-
  assign-[:reads]->signal` chains), use a `saved_query` (available in a later
  slice) rather than raw Cypher, which has no clean recursive form.

---

## Recipes

Runnable Cypher examples against the corpus. Each executes without error.

**Methods of class `cls_pkg.data_xact`?**

```cypher
MATCH (c:N)-[:has_method]->(m:N) WHERE c.path='cls_pkg.data_xact' RETURN m.name
```

**Ports OR nets of interface `fifo_if`?**

```cypher
MATCH (i:N)-[:has_port|has_net]->(s:N) WHERE i.name='fifo_if' RETURN s.name
```

**Each instance in `top` and its module?**

```cypher
MATCH (t:N)-[:instantiates]->(i:N)-[:of_module]->(m:N) WHERE t.name='top' RETURN i.path, m.name
```

**How many ports does `fifo` have?**

```cypher
MATCH (f:N)-[:has_port]->(p:N) WHERE f.name='fifo' RETURN count(p)
```

**Signals that feed what drives `fifo.full`?**

```cypher
MATCH (f:N)<-[:drives]-(d:N)-[:reads]->(s:N) WHERE f.path='fifo.full' RETURN DISTINCT s.name
```

---
