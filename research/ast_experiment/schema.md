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
