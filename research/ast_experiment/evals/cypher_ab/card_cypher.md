# SV Graph Schema Card — Cypher surface

The one-page contract for traversing the SystemVerilog knowledge graph **with
Cypher** and getting accurate answers without grep. The graph is loaded into an
embedded property-graph DB; you query it with standard Cypher. Everything here is
measured from the live graph over the 11-file corpus, not aspirational.

> The graph has **65 node roles** and **~30 semantic relationship types**. §3
> groups the roles; §4 groups the relationships. Identity is the hierarchical
> `path` (`fifo.count`, `top.u_fifo`), never a bare name.

---

## 1. Schema (what to MATCH on)

There is **one node label**, `N`, with these properties:

| property | meaning |
|---|---|
| `id` | opaque unique id (rarely needed) |
| `role` | the node's kind — see §3 (`module`, `port`, `net`, `class`, `method`, …) |
| `name` | bare identifier (`count`, `fifo`) |
| `path` | hierarchical identity (`fifo.count`, `top.u_fifo`) — **the key you usually match on** |
| `direction` | for ports/modport items: `"input"`/`"output"`/`"inout"` (else null) |

Relationships are **typed** — the relationship type IS the semantic edge name
(`-[:reads]->`, `-[:has_method]->`, `-[:of_module]->`). §4 lists them.

```cypher
MATCH (n:N {role:'module'}) RETURN n.name
MATCH (p:N {path:'fifo.full'})<-[:drives]-(d:N) RETURN d.path
```

Standard Cypher applies: `WHERE`, `IN`, `NOT`, `count()/collect()`, multiple
`RETURN` columns, variable-length `-[:reads*1..3]->`, `DISTINCT`, etc.

---

## 2. Node roles (65), by family

Match with `{role:'…'}` or `WHERE n.role IN [...]`.

| Family | Roles |
|---|---|
| **Design units / scopes** | `module`, `interface`, `program`, `package`, `class`, `checker`, `primitive_instance` |
| **Ports & signals** | `port`, `net`, `param`, `net_decl`, `nettype`, `user_defined_net_decl`, `port_reference`, `port_concat`, `genvar`, `local_var`, `type_param` |
| **Behavioral logic** | `procedural_block`, `continuous_assign`, `function`, `function_prototype`, `function_port`, `method`, `method_prototype`, `system_call`, `identifier_select`, `event_trigger`, `procedural_assign`, `procedural_force`, `procedural_deassign`, `procedural_release` |
| **Hierarchy** | `instance`, `generate_loop`, `generate_block` |
| **Types** | `typedef`, `typedef_forward`, `enum_value`, `struct_member`, `union_member` |
| **Verification** | `assertion`, `assertion_item_port`, `property`, `sequence`, `let_decl`, `default_disable`, `covergroup`, `coverpoint`, `cross`, `coverage_bins`, `constraint`, `inline_constraint_block` |
| **Interface plumbing** | `modport`, `interface_port`, `clocking`, `clocking_item` |
| **Externs / DPI** | `extern_decl`, `extern_udp`, `dpi_import` |
| **Other** | `time_units`, `checker_data`, `checker_instance`, `class_property` |

---

## 3. Relationship types, by purpose

### 3a. Containment — "scope X owns member Y" (`has_*`)

`has_port`, `has_param`, `has_net`, `has_net_decl`, `has_nettype`,
`has_user_defined_net_decl`, `has_typedef`, `has_enum_value`, `has_member`,
`has_function`, `has_function_port`, `has_method`, `has_class`,
`has_class_property`, `has_modport`, `has_clocking`, `has_clocking_item`,
`has_covergroup`, `has_coverpoint`, `has_bins`, `has_cross`, `has_property`,
`has_sequence`, `has_assertion`, `has_assertion_item_port`, `has_let`,
`has_constraint`, `has_inline_constraint`, `has_local_var`, `has_genvar`,
`has_generate`, `has_type_param`, `has_dpi_import`, `has_primitive_instance`,
`has_checker`, `has_checker_data`, `has_checker_instance`, `has_event_trigger`,
`has_default_disable`, `has_timeunits`, `has_procedural_assign`,
`has_procedural_force`.

The child's `role` tells you what kind of member it is. To get several kinds at
once, union the types or filter on role:
`MATCH (i:N {name:'fifo_if'})-[:has_port|has_net]->(s:N) RETURN s.name`.

> Note `has_typedef` covers BOTH `typedef` and `typedef_forward` children;
> `has_bins` children have role `coverage_bins`; class fields are
> `has_class_property` (role `class_property`).

### 3b. Dataflow — how values move

| Rel | Meaning |
|---|---|
| `drives` | `(assign/always)-[:drives]->(signal it writes)` — drivers of X: `(X)<-[:drives]-(d)` |
| `reads` | `(assign/always/select/syscall)-[:reads]->(signal it reads)` |
| `checks` | `(assertion)-[:checks]->(data signal it constrains)` (sampling clock excluded) |
| `connects` | `(parent net/port)-[:connects]->(child instance port)` |
| `sensitive_to` | `(always_ff)-[:sensitive_to]->(clock/reset)` |
| `triggers` | `(event-trigger)-[:triggers]->(named event)` |
| `aliases`, `groups_net`, `groups_port_ref` | net/port aliasing & grouping |

### 3c. Hierarchy & resolution — how names bind

| Rel | Meaning |
|---|---|
| `instantiates` | `(parent module)-[:instantiates]->(instance)` |
| `of_module` | `(instance)-[:of_module]->(module definition)` |
| `of_checker` | `(checker-instance)-[:of_checker]->(checker def)` |
| `of_type` | `(signal/port/net/param)-[:of_type]->(typedef/struct/enum)` |
| `calls` | `(always/function)-[:calls]->(function)` |
| `extends`, `implements` | class → parent / interface-class |
| `imports`, `imports_item`, `exports_all` | scope → package |
| `references_interface` | port → interface it's typed by |
| `prototypes`, `declares` | extern/prototype → definition |

### 3d. Overrides & misc

`param_override`, `defparam_override`, `default_clocking`, `dpi_exports`,
`contains_block` (generate_loop → per-iteration block), `bind_target`,
`bound_into`.

---

## 4. Cypher recipes (NL question → query)

| Question | Cypher |
|---|---|
| "What modules exist?" | `MATCH (n:N {role:'module'}) RETURN n.name` |
| "Output ports of `fifo`?" | `MATCH (m:N {name:'fifo'})-[:has_port]->(p:N) WHERE p.direction='output' RETURN p.name` |
| "What type is port `fifo.status`?" | `MATCH (p:N {path:'fifo.status'})-[:of_type]->(t:N) RETURN t.path` |
| "What drives `fifo.full`?" | `MATCH (p:N {path:'fifo.full'})<-[:drives]-(d:N) RETURN d.path` |
| "Methods of class X?" | `MATCH (c:N {path:'cls_pkg.data_xact'})-[:has_method]->(m:N) RETURN m.name` |
| "Ports OR nets of `fifo_if`?" | `MATCH (i:N {name:'fifo_if'})-[:has_port\|has_net]->(s:N) RETURN s.name` |
| "How many ports does `fifo` have?" | `MATCH (f:N {name:'fifo'})-[:has_port]->(p:N) RETURN count(p)` |
| "Each instance in `top` and its module?" | `MATCH (t:N {name:'top'})-[:instantiates]->(i:N)-[:of_module]->(m:N) RETURN i.path, m.name` |
| "Signals feeding what drives `fifo.full`?" | `MATCH (f:N {path:'fifo.full'})<-[:drives]-(d:N)-[:reads]->(s:N) RETURN DISTINCT s.name` |
| "Transitive fan-in cone of `fifo.count`?" | hard to express directly — fan-in alternates `signal<-[:drives]-assign-[:reads]->signal` plus `<-[:connects]-`; see notes |

**Unresolved targets** (forward/external refs) have no node row — a relationship
to them simply matches nothing.
