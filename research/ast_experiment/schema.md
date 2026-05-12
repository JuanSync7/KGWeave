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

### Semantic rule table (S1..S5)

| Rule | Syntax trigger                              | Promoted node role    | Edges drawn                              |
|------|----------------------------------------------|------------------------|-------------------------------------------|
| S1   | `ModuleDeclarationSyntax`                    | `module`               | `has_port` × ports, `has_param` × params, `has_net` × variables |
| S1   | `ImplicitAnsiPortSyntax`                     | `port`                 | inbound `has_port` from module            |
| S1   | `DeclaratorSyntax` ∈ ParameterDeclaration    | `param`                | inbound `has_param` from module           |
| S1   | `DeclaratorSyntax` ∈ DataDeclaration         | `net`                  | inbound `has_net` from module             |
| S2   | `ContinuousAssignSyntax`                     | `continuous_assign`    | `drives`(LHS), `reads`(RHS identifiers)   |
| S3   | `ProceduralBlockSyntax` (kw=`always_ff`)     | `always_ff`            | `sensitive_to`, `drives`, `reads` (incl. predicate + case head) |
| S4   | `IdentifierSelectNameSyntax`                 | `identifier_select`    | `reads`(base symbol)                       |
| S5   | `InvocationExpressionSyntax` over SystemName | `system_call`          | `reads`(argument identifiers)              |

### Identifier resolution

The semantic layer resolves a name by:

1. `pyslang.Compilation.find(name)` on the enclosing module's `InstanceBodySymbol`
   (handles single-module scoping; we also try `lookupName` for upward search).
2. Mapping the symbol's declaration syntax to the graph-id of the corresponding
   promoted `DeclaratorSyntax` / `ImplicitAnsiPortSyntax`, via the `semantic_name_index`
   built during S1.

If step 1 returns nothing we fall back to pure name-string matching in the
module's name index and append a record to `graph["semantic_leaks"]` so
`RESULT.md` can surface the slippage. For `fifo.sv` no leaks fire.

### Snip-and-ref invariant

Because S1..S5 do not move any token payloads, the structural emit walk still
reproduces the input byte-for-byte (`test_roundtrip_after_promote` enforces
this). The `_node_ref` snip-and-ref placeholder is **reserved but unused** —
the structural layer already stores each promoted subtree in place, so the
projection only needs to add flags and edges. If a future rule needs to physically
relocate a subtree, `unlift.emit` must learn to deref `{"_node_ref": "<id>"}`
slots before that rule lands.

