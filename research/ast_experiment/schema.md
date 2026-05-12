# Graph schema for pyslang AST round-trip

The lift produces a **structural** graph: every pyslang syntax node maps 1:1 to
a graph node, every pyslang `iter(node)` child maps 1:1 to an ordered `child`
edge. Token leaves carry their lexical state (rawText, valueText, leading
trivia, isMissing). The reverse engine emits SV text by depth-first walk over
the rebuilt tree, concatenating leading trivia + rawText for each Token leaf.

This design intentionally has *one* node-type schema (the pyslang class name)
and *one* edge-type schema (`child` with an integer `index`). All AST classes
listed in `ast_classes.json` therefore share the same graph treatment; per-class
columns below document the specific shape each class takes (typed fields the
graph preserves, and the reverse rule).

## Common rules

| Concern                | Where it lives                                                       |
|------------------------|----------------------------------------------------------------------|
| Class identity         | `node.type` (Python class name)                                      |
| SyntaxKind / TokenKind | `node.kind`                                                          |
| Token raw text         | `node.payload.rawText` (Token only)                                  |
| Token value (lexed)    | `node.payload.valueText` (Token only)                                |
| Token leading trivia   | `node.payload.trivia` = ordered list of `{kind, text}` records       |
| isMissing flag         | `node.payload.isMissing` (Token only)                                |
| Child ordering         | `edge.type == "child"`, `edge.payload.index = int`                    |
| Reverse rule (Token)   | emit `"".join(trivia.text) + rawText`                                |
| Reverse rule (Node)    | emit children in order; Token leaves stop recursion                  |

Only **trivia** carries literal text on non-Token nodes (none are emitted there
since container nodes have no own text — all source bytes belong to Tokens).

## Per-class table

| pyslang class                       | Graph form (`type` + relevant payload)   | Reverse rule                                  |
|-------------------------------------|------------------------------------------|-----------------------------------------------|
| ModuleDeclarationSyntax             | type=`ModuleDeclarationSyntax`           | emit children in order                         |
| ModuleHeaderSyntax                  | type=`ModuleHeaderSyntax`                | emit children in order                         |
| ParameterPortListSyntax             | type=`ParameterPortListSyntax`           | emit children in order                         |
| ParameterDeclarationSyntax          | type=`ParameterDeclarationSyntax`        | emit children in order                         |
| IntegerTypeSyntax                   | type=`IntegerTypeSyntax`                 | emit children in order                         |
| DeclaratorSyntax                    | type=`DeclaratorSyntax`                  | emit children in order                         |
| EqualsValueClauseSyntax             | type=`EqualsValueClauseSyntax`           | emit children in order                         |
| AnsiPortListSyntax                  | type=`AnsiPortListSyntax`                | emit children in order                         |
| ImplicitAnsiPortSyntax              | type=`ImplicitAnsiPortSyntax`            | emit children in order                         |
| VariablePortHeaderSyntax            | type=`VariablePortHeaderSyntax`          | emit children in order                         |
| DataDeclarationSyntax               | type=`DataDeclarationSyntax`             | emit children in order                         |
| VariableDimensionSyntax             | type=`VariableDimensionSyntax`           | emit children in order                         |
| RangeDimensionSpecifierSyntax       | type=`RangeDimensionSpecifierSyntax`     | emit children in order                         |
| ContinuousAssignSyntax              | type=`ContinuousAssignSyntax`            | emit children in order                         |
| ExpressionStatementSyntax           | type=`ExpressionStatementSyntax`         | emit children in order                         |
| ProceduralBlockSyntax               | type=`ProceduralBlockSyntax`             | emit children in order                         |
| TimingControlStatementSyntax        | type=`TimingControlStatementSyntax`      | emit children in order                         |
| EventControlWithExpressionSyntax    | type=`EventControlWithExpressionSyntax`  | emit children in order                         |
| BinaryEventExpressionSyntax         | type=`BinaryEventExpressionSyntax`       | emit children in order                         |
| SignalEventExpressionSyntax         | type=`SignalEventExpressionSyntax`       | emit children in order                         |
| ParenthesizedEventExpressionSyntax  | type=`ParenthesizedEventExpressionSyntax`| emit children in order                         |
| BlockStatementSyntax                | type=`BlockStatementSyntax`              | emit children in order                         |
| ConditionalStatementSyntax          | type=`ConditionalStatementSyntax`        | emit children in order                         |
| ConditionalPredicateSyntax          | type=`ConditionalPredicateSyntax`        | emit children in order                         |
| ConditionalPatternSyntax            | type=`ConditionalPatternSyntax`          | emit children in order                         |
| ElseClauseSyntax                    | type=`ElseClauseSyntax`                  | emit children in order                         |
| CaseStatementSyntax                 | type=`CaseStatementSyntax`               | emit children in order                         |
| StandardCaseItemSyntax              | type=`StandardCaseItemSyntax`            | emit children in order                         |
| DefaultCaseItemSyntax               | type=`DefaultCaseItemSyntax`             | emit children in order                         |
| BinaryExpressionSyntax              | type=`BinaryExpressionSyntax`            | emit children in order                         |
| PrefixUnaryExpressionSyntax         | type=`PrefixUnaryExpressionSyntax`       | emit children in order                         |
| ParenthesizedExpressionSyntax       | type=`ParenthesizedExpressionSyntax`     | emit children in order                         |
| ConcatenationExpressionSyntax       | type=`ConcatenationExpressionSyntax`     | emit children in order                         |
| IntegerVectorExpressionSyntax       | type=`IntegerVectorExpressionSyntax`     | emit children in order                         |
| LiteralExpressionSyntax             | type=`LiteralExpressionSyntax`           | emit children in order                         |
| BitSelectSyntax                     | type=`BitSelectSyntax`                   | emit children in order                         |
| ElementSelectSyntax                 | type=`ElementSelectSyntax`               | emit children in order                         |
| RangeSelectSyntax                   | type=`RangeSelectSyntax`                 | emit children in order                         |
| IdentifierSelectNameSyntax          | type=`IdentifierSelectNameSyntax`        | emit children in order                         |
| IdentifierNameSyntax                | type=`IdentifierNameSyntax`              | emit children in order                         |
| SystemNameSyntax                    | type=`SystemNameSyntax`                  | emit children in order                         |
| InvocationExpressionSyntax          | type=`InvocationExpressionSyntax`        | emit children in order                         |
| ArgumentListSyntax                  | type=`ArgumentListSyntax`                | emit children in order                         |
| OrderedArgumentSyntax               | type=`OrderedArgumentSyntax`             | emit children in order                         |
| SimplePropertyExprSyntax            | type=`SimplePropertyExprSyntax`          | emit children in order                         |
| SimpleSequenceExprSyntax            | type=`SimpleSequenceExprSyntax`          | emit children in order                         |
| SyntaxNode                          | type=`SyntaxNode` (list/null wrappers)   | emit children in order                         |
| Token                               | type=`Token`, payload={rawText, trivia}  | emit join(trivia.text) + rawText                |
| HierarchyInstantiationSyntax        | type=`HierarchyInstantiationSyntax`      | emit children in order                         |
| HierarchicalInstanceSyntax          | type=`HierarchicalInstanceSyntax`        | emit children in order                         |
| InstanceNameSyntax                  | type=`InstanceNameSyntax`                | emit children in order                         |
| NamedPortConnectionSyntax           | type=`NamedPortConnectionSyntax`         | emit children in order                         |

## Semantic layer (projection)

`scripts/semantic.py` adds a **queryable view** on top of the structural graph
without mutating the existing payloads, so the round-trip oracle stays green.

Promotion marks a structural node with:

| Field              | Meaning                                                           |
|--------------------|-------------------------------------------------------------------|
| `node["queryable"]`| `True` — node is part of the semantic surface                     |
| `node["semantic"]` | `{"role": <role>, "name"?: str, "lhs"?: str, "base"?: str, ...}`  |

Typed semantic edges live in the same `graph["edges"]` list, distinguished by
the `type` field. Both layers share the same underlying node id space.

### Semantic edge types

| Edge type      | Meaning                                                        | Added by   |
|----------------|----------------------------------------------------------------|------------|
| `has_port`     | module → port declarator                                       | S1         |
| `has_param`    | module → parameter declarator                                  | S1         |
| `has_net`      | module → net/variable declarator (non-port)                    | S1         |
| `drives`       | (continuous assign \| always_ff) → LHS symbol anchor           | S2, S3     |
| `reads`        | (assign \| always_ff \| id-select \| sys call) → RHS anchor    | S2, S3, S4, S5 |
| `sensitive_to` | always_ff → clock/reset symbol; payload `{"edge": "posedge"…}` | S3         |
| `instantiates` | parent module → child instance node                            | S6         |
| `of_module`    | instance node → module-definition node it elaborates           | S6         |
| `connects`     | parent net/port → child instance's port; payload `{"instance", "port"}` | S6 |

### Semantic rule table (S1..S6)

| Rule | Syntax trigger                              | Promoted node role    | Edges drawn                              |
|------|----------------------------------------------|------------------------|-------------------------------------------|
| S1   | `ModuleDeclarationSyntax`                    | `module`               | `has_port` × ports, `has_param` × params, `has_net` × variables. Fires once **per module declaration** in the syntax tree, not just on the top-level instance. |
| S1   | `ImplicitAnsiPortSyntax`                     | `port`                 | inbound `has_port` from module            |
| S1   | `DeclaratorSyntax` ∈ ParameterDeclaration    | `param`                | inbound `has_param` from module           |
| S1   | `DeclaratorSyntax` ∈ DataDeclaration         | `net`                  | inbound `has_net` from module             |
| S2   | `ContinuousAssignSyntax`                     | `continuous_assign`    | `drives`(LHS), `reads`(RHS identifiers)   |
| S3   | `ProceduralBlockSyntax` (kw=`always_ff`)     | `always_ff`            | `sensitive_to`, `drives`, `reads` (incl. predicate + case head) |
| S4   | `IdentifierSelectNameSyntax`                 | `identifier_select`    | `reads`(base symbol)                       |
| S5   | `InvocationExpressionSyntax` over SystemName | `system_call`          | `reads`(argument identifiers)              |
| S6   | `HierarchyInstantiationSyntax`               | `instance` (anchored at the `HierarchicalInstanceSyntax`) | parent `instantiates` instance; instance `of_module` definition; parent-net `connects` child-port for each `NamedPortConnectionSyntax` |

### Identifier resolution — hierarchical-path keys

`semantic_name_index` keys are **hierarchical paths**, never bare names:

* `fifo.count`, `fifo.DEPTH`, `top.u_fifo`, `top.u_fifo.count`.
* The leaf path component is the local symbol name (port, net, param, instance).
* The path prefix is the chain of enclosing scopes, sourced from pyslang's
  elaborated `InstanceBodySymbol.name` chain.
* `type` (`module` / `port` / `param` / `net` / `instance` / `continuous_assign`
  / `always_ff` / `identifier_select` / `system_call`) lives on
  `node["semantic"]["role"]` as **metadata** — it never participates in the
  lookup key. Filter on it at query time.

Resolution algorithm for a name appearing inside module `M`:

1. Try `name_index[f"{M}.{name}"]` (the hierarchical-path key).
2. If absent, fall back to a bare-name scan: `[v for k,v in idx.items() if k == name or k.endswith("." + name)]`.
   Accept only if exactly **one** match exists. Ambiguous bare names fail closed.
3. Confirm the symbol exists in pyslang's elaborated scope via
   `InstanceBodySymbol.find(name)` / `lookupName`. The pyslang scope is keyed
   by module **definition name** (so a `top.u_fifo` body resolves under `fifo`).
4. If pyslang returns `None`, append `graph["semantic_leaks"]` with the
   context, name, and reason.

For both `fifo.sv` and `top.sv` no leaks fire.

`find_by_name(graph, name)` accepts either a full path or a bare leaf name and
applies rules 1–2 in that order.

### Snip-and-ref invariant

Because S1..S5 do not move any token payloads, the structural emit walk still
reproduces the input byte-for-byte (`test_roundtrip_after_promote` enforces
this). The `_node_ref` snip-and-ref placeholder is **reserved but unused** —
the structural layer already stores each promoted subtree in place, so the
projection only needs to add flags and edges. If a future rule needs to physically
relocate a subtree, `unlift.emit` must learn to deref `{"_node_ref": "<id>"}`
slots before that rule lands.

