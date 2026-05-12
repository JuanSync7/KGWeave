# Bucket 1 — SV-AST elaboration coverage checklist (pyslang SyntaxKind universe)

Total `pyslang.SyntaxKind` enum size: **536** distinct values.

Each item below is classified:

| Mark | Meaning |
|------|---------|
| 🟢 **PROMOTE** | Becomes a queryable graph node and draws typed semantic edges (`drives`, `reads`, `has_port`, `instantiates`, …). The "bucket 1 edge contribution." |
| 🔵 **CONTAINER** | Lifted as a structural node (lossless), but not promoted into the queryable surface. Reachable via its parent's payload or structural slot. Useful only as an anchor for richer rules later. |
| ⚪ **BLOB** | Stays as opaque JSON payload on its owning node. Captures all bytes (operator, literal, bit-width, source range, etc.) so the agent can read the detail once it arrives, but never becomes a separate graph node. |
| 🟣 **DIRECTIVE** | Preprocessor / pragma — appears in raw syntax tree but typically vanishes post-elab. Lift trivially, do not promote. |
| ⚫ **OUT-OF-SCOPE** | UDP, library map, config rules, SDF — niche / not used in typical RAG-target RTL. Keep classifier honest by listing but don't plan a rule. |

Coverage status for promotable items:

| Symbol | Status |
|--------|--------|
| ✅ | Currently covered by an active rule (S1..S6) |
| ⏳ | In flight in the running expansion loop (S7..S12, Phases 1–7) |
| ⬜ | Not yet covered; future Ralph iteration |

---

## 1. Module-level declarations (the universe roots)

| SyntaxKind | Class | Status | Notes |
|---|---|---|---|
| `ModuleDeclaration` | 🟢 PROMOTE | ✅ S1 | Already covered |
| `ModuleHeader` | 🔵 CONTAINER | ✅ | Lifted by S1; payload carries port list / param list. |
| `InterfaceDeclaration` | 🟢 PROMOTE | ⏳ S11a | Phase 5 |
| `InterfaceHeader` | 🔵 CONTAINER | ⏳ | |
| `InterfacePortHeader` | 🔵 CONTAINER | ⏳ | |
| `PackageDeclaration` | 🟢 PROMOTE | ⏳ S9a | Phase 3 |
| `PackageHeader` | 🔵 CONTAINER | ⏳ | |
| `ProgramDeclaration` | 🟢 PROMOTE | ⬜ | Rare in DV; treat like Module when needed. |
| `ProgramHeader` | 🔵 CONTAINER | ⬜ | |
| `ClassDeclaration` | 🟢 PROMOTE | ⬜ | Future: UVM classes. Needs class-method, property, extends edges. |
| `CheckerDeclaration` | 🟢 PROMOTE | ⬜ | SVA checker block — promote into the assertion sub-graph. |
| `ConfigDeclaration` | ⚫ OUT-OF-SCOPE | ⬜ | Build config; skip. |
| `LibraryDeclaration`, `LibraryMap`, `LibraryIncludeStatement`, `LibraryIncDirClause` | ⚫ OUT-OF-SCOPE | ⬜ | Build-tool concerns. |
| `PrimitiveInstantiation`, `UdpDeclaration`, `UdpBody`, `UdpEntry`, `UdpInitialStmt`, `UdpInputPortDecl`, `UdpOutputPortDecl`, `UdpEdgeField`, `UdpSimpleField`, `AnsiUdpPortList`, `NonAnsiUdpPortList`, `WildcardUdpPortList` | ⚫ OUT-OF-SCOPE | ⬜ | UDPs; rare in modern designs. |
| `CompilationUnit`, `RootScope`, `UnitScope`, `LocalScope` | 🔵 CONTAINER | ✅ | Trivially walked. |
| `AnonymousProgram` | 🔵 CONTAINER | ⬜ | |
| `ExternModuleDecl`, `ExternUdpDecl`, `ExternInterfaceMethod` | 🔵 CONTAINER | ⬜ | Lift as node; no body. |

## 2. Port lists & headers

| SyntaxKind | Class | Status |
|---|---|---|
| `AnsiPortList` | 🔵 CONTAINER | ✅ |
| `NonAnsiPortList` | 🔵 CONTAINER | ⬜ |
| `ImplicitAnsiPort` | 🟢 PROMOTE | ✅ S1 (as `port`) |
| `ExplicitAnsiPort` | 🟢 PROMOTE | ⬜ Same as ImplicitAnsi |
| `ImplicitNonAnsiPort` | 🟢 PROMOTE | ⬜ |
| `ExplicitNonAnsiPort` | 🟢 PROMOTE | ⬜ |
| `EmptyNonAnsiPort` | 🔵 CONTAINER | ⬜ |
| `VariablePortHeader` | 🔵 CONTAINER | ✅ |
| `NetPortHeader` | 🔵 CONTAINER | ⬜ |
| `PortDeclaration` | 🟢 PROMOTE | ⬜ Non-ANSI form |
| `PortReference`, `PortConcatenation`, `WildcardPortList` | 🔵 CONTAINER | ⬜ |

## 3. Parameters

| SyntaxKind | Class | Status |
|---|---|---|
| `ParameterPortList` | 🔵 CONTAINER | ✅ |
| `ParameterDeclaration` | 🟢 PROMOTE | ✅ S1 (as `param`) |
| `ParameterDeclarationStatement` | 🔵 CONTAINER | ⬜ |
| `TypeParameterDeclaration` | 🟢 PROMOTE | ⬜ Type params (rare but real) |
| `TypeAssignment` | ⚪ BLOB | ⬜ |
| `EqualsTypeClause` | ⚪ BLOB | ⬜ |
| `ParameterValueAssignment` | 🟢 PROMOTE | ⏳ S7 — `param_override` edge on instance |
| `NamedParamAssignment`, `OrderedParamAssignment` | 🔵 CONTAINER | ⏳ — children of ParameterValueAssignment |
| `DefParam`, `DefParamAssignment` | 🟢 PROMOTE | ⬜ Legacy override mechanism |

## 4. Variable / net declarations

| SyntaxKind | Class | Status |
|---|---|---|
| `DataDeclaration` | 🔵 CONTAINER | ✅ |
| `NetDeclaration` | 🔵 CONTAINER | ⬜ explicit `wire`/`tri` decls |
| `LocalVariableDeclaration` | 🔵 CONTAINER | ⬜ inside SVA properties |
| `GenvarDeclaration` | 🔵 CONTAINER | ⬜ |
| `SpecparamDeclaration`, `SpecparamDeclarator` | ⚫ OUT-OF-SCOPE | ⬜ Specify-block only |
| `Declarator` | 🟢 PROMOTE | ✅ becomes `net` |
| `UserDefinedNetDeclaration`, `NetAlias`, `NetTypeDeclaration` | ⬜ | rare |
| `VariableDimension`, `RangeDimensionSpecifier`, `QueueDimensionSpecifier`, `WildcardDimensionSpecifier` | ⚪ BLOB | ✅ in payload as `dim` |
| `EqualsValueClause` | ⚪ BLOB | ✅ default-value payload |

## 5. Types (all primitive + composite)

All scalar/integer/real/string types — **⚪ BLOB on the owning declarator's payload.** Type info IS captured (so `width_of` works) but not promoted to its own node. Listed exhaustively for closure:

| SyntaxKind | Class |
|---|---|
| `IntegerType`, `LogicType`, `BitType`, `ByteType`, `IntType`, `LongIntType`, `ShortIntType`, `RegType`, `RealType`, `ShortRealType`, `RealTimeType`, `TimeType`, `StringType`, `VoidType`, `CHandleType`, `EventType`, `Untyped` | ⚪ BLOB |
| `EnumType` | 🟢 PROMOTE | ⏳ S9c — enum values as `has_enum_value` edges |
| `StructType`, `UnionType`, `StructUnionMember` | 🟢 PROMOTE | ⬜ — `has_field` edges per member |
| `TypedefDeclaration` | 🟢 PROMOTE | ⏳ S9b |
| `ForwardTypedefDeclaration`, `ForwardTypeRestriction` | 🔵 CONTAINER | ⬜ |
| `NamedType`, `TypeReference` | ⚪ BLOB | ⬜ — type-ref payload pointing at the typedef's path |
| `VirtualInterfaceType` | 🟢 PROMOTE | ⬜ — `virtual_interface_of` edge |
| `ImplicitType` | ⚪ BLOB |

## 6. Procedural blocks

| SyntaxKind | Class | Status |
|---|---|---|
| `AlwaysBlock` | 🟢 PROMOTE | ⬜ Generic always (no edge-type assumed). |
| `AlwaysFFBlock` | 🟢 PROMOTE | ✅ S3 |
| `AlwaysCombBlock` | 🟢 PROMOTE | ⏳ S8 — like S3 but no `sensitive_to` |
| `AlwaysLatchBlock` | 🟢 PROMOTE | ⬜ |
| `InitialBlock` | 🟢 PROMOTE | ⬜ — `runs_at_time(0)` semantic edge optional |
| `FinalBlock` | 🟢 PROMOTE | ⬜ |
| `SequentialBlockStatement`, `ParallelBlockStatement`, `BlockStatement` | 🔵 CONTAINER | ✅ |
| `NamedBlockClause` | ⚪ BLOB | ✅ |

## 7. Continuous-assign & instantiation

| SyntaxKind | Class | Status |
|---|---|---|
| `ContinuousAssign` | 🟢 PROMOTE | ✅ S2 |
| `HierarchyInstantiation` | 🟢 PROMOTE | ✅ S6 |
| `HierarchicalInstance` | 🟢 PROMOTE | ✅ S6 (becomes `instance` node) |
| `InstanceName` | 🔵 CONTAINER | ✅ |
| `NamedPortConnection` | 🟢 PROMOTE | ✅ S6 — becomes `connects` edge |
| `OrderedPortConnection` | 🟢 PROMOTE | ⬜ — positional form |
| `WildcardPortConnection`, `EmptyPortConnection` | 🔵 CONTAINER | ⬜ |
| `CheckerInstantiation`, `CheckerInstanceStatement` | 🟢 PROMOTE | ⬜ Assertion checker |
| `BindDirective`, `BindTargetList` | 🟢 PROMOTE | ⬜ — `bind_target` edge |

## 8. Statements

| SyntaxKind | Class | Status |
|---|---|---|
| `ConditionalStatement` | 🔵 CONTAINER | ✅ |
| `ElseClause`, `ConditionalPredicate`, `ConditionalPattern` | 🔵 CONTAINER | ✅ |
| `CaseStatement`, `StandardCaseItem`, `DefaultCaseItem` | 🔵 CONTAINER | ✅ |
| `RandCaseStatement`, `RandCaseItem`, `StandardPropertyCaseItem`, `DefaultPropertyCaseItem`, `StandardRsCaseItem`, `DefaultRsCaseItem`, `PatternCaseItem` | 🔵 CONTAINER | ⬜ |
| `ForLoopStatement`, `ForVariableDeclaration`, `ForeachLoopStatement`, `ForeachLoopList`, `ForeverStatement`, `DoWhileStatement`, `LoopStatement` | 🔵 CONTAINER | ⬜ |
| `WhileStatement` (via LoopStatement), `RepeatedEventControl` | 🔵 CONTAINER | ⬜ |
| `ExpressionStatement` | 🔵 CONTAINER | ✅ |
| `EmptyStatement`, `JumpStatement`, `ReturnStatement` | 🔵 CONTAINER | ✅/⬜ |
| `DisableStatement`, `DisableForkStatement`, `WaitForkStatement`, `WaitOrderStatement`, `WaitStatement` | 🔵 CONTAINER | ⬜ |
| `ProceduralAssignStatement`, `ProceduralDeassignStatement`, `ProceduralForceStatement`, `ProceduralReleaseStatement` | 🟢 PROMOTE | ⬜ — same as continuous_assign but procedural |
| `BlockingEventTriggerStatement`, `NonblockingEventTriggerStatement` | 🟢 PROMOTE | ⬜ |
| `ImmediateAssertStatement`, `ImmediateAssumeStatement`, `ImmediateCoverStatement`, `ImmediateAssertionMember`, `DeferredAssertion` | 🟢 PROMOTE | ⬜ Inline SVA |
| `AssertPropertyStatement`, `AssumePropertyStatement`, `CoverPropertyStatement`, `CoverSequenceStatement`, `RestrictPropertyStatement`, `ExpectPropertyStatement`, `ConcurrentAssertionMember` | 🟢 PROMOTE | ⬜ Concurrent SVA — important for OpenTitan |
| `VoidCastedCallStatement` | ⚪ BLOB | ⬜ |
| `TimingControlStatement`, `TimingControlExpression`, `EventControl`, `EventControlWithExpression`, `ImplicitEventControl`, `DelayControl`, `OneStepDelay`, `CycleDelay`, `SignalEventExpression`, `BinaryEventExpression`, `ParenthesizedEventExpression`, `IffEventClause` | 🔵 CONTAINER + ⚪ BLOB | ✅ partial (S3) |
| `ElabSystemTask`, `SystemTimingCheck`, `TimingCheckEventArg`, `TimingCheckEventCondition`, `ExpressionTimingCheckArg`, `EmptyTimingCheckArg` | ⚫ OUT-OF-SCOPE | ⬜ Specify-block timing |

## 9. Expressions — *most* live in payload (⚪ BLOB)

Expressions are the **canonical "in-blob" case.** They're lifted into the structural backbone (lossless), but the queryable layer only attaches **`reads` edges to identifier leaves**. The operator tree, operator type, intermediate subexpressions, parenthesization — all opaque payload.

### Identifier / select / member
| SyntaxKind | Class | Status |
|---|---|---|
| `IdentifierName` | 🟢 PROMOTE | ✅ (leaf becomes `reads` edge) |
| `IdentifierSelectName` | 🟢 PROMOTE | ✅ S4 |
| `ScopedName`, `ClassName`, `ConstructorName`, `SuperHandle`, `ThisHandle`, `EmptyIdentifierName` | 🔵 CONTAINER | ⬜ |
| `MemberAccessExpression`, `DotMemberClause` | 🟢 PROMOTE | ⬜ — `reads(member_of_obj)` |
| `ElementSelect`, `ElementSelectExpression`, `BitSelect`, `SimpleRangeSelect`, `AscendingRangeSelect`, `DescendingRangeSelect`, `RangeList` | 🔵 CONTAINER + ⚪ BLOB | ✅ partial |

### Literals
| SyntaxKind | Class |
|---|---|
| `IntegerLiteralExpression`, `IntegerVectorExpression`, `RealLiteralExpression`, `TimeLiteralExpression`, `StringLiteralExpression`, `NullLiteralExpression`, `UnbasedUnsizedLiteralExpression`, `WildcardLiteralExpression` | ⚪ BLOB |

### Arithmetic / logical / bitwise / relational / shift (all operator variants)
All ⚪ BLOB. The operator class (`AddExpression`, `MultiplyExpression`, `LogicalAndExpression`, etc. — ~80 variants) becomes a payload field `operator: "+"`, `"&&"`, etc. Identifier leaves still become `reads` edges via the structural walk.

Variants (full list, all ⚪ BLOB unless noted):
`AddExpression`, `SubtractExpression`, `MultiplyExpression`, `DivideExpression`, `ModExpression`, `PowerExpression`, `ArithmeticShiftLeftExpression`, `ArithmeticShiftRightExpression`, `LogicalShiftLeftExpression`, `LogicalShiftRightExpression`, `BinaryAndExpression`, `BinaryOrExpression`, `BinaryXorExpression`, `BinaryXnorExpression`, `LogicalAndExpression`, `LogicalOrExpression`, `LogicalImplicationExpression`, `LogicalEquivalenceExpression`, `EqualityExpression`, `InequalityExpression`, `CaseEqualityExpression`, `CaseInequalityExpression`, `WildcardEqualityExpression`, `WildcardInequalityExpression`, `GreaterThanExpression`, `LessThanExpression`, `GreaterThanEqualExpression`, `LessThanEqualExpression`, `UnaryBitwiseAndExpression`, `UnaryBitwiseOrExpression`, `UnaryBitwiseXorExpression`, `UnaryBitwiseNotExpression`, `UnaryBitwiseNandExpression`, `UnaryBitwiseNorExpression`, `UnaryBitwiseXnorExpression`, `UnaryLogicalNotExpression`, `UnaryPlusExpression`, `UnaryMinusExpression`, `UnaryPredecrementExpression`, `UnaryPreincrementExpression`, `PostdecrementExpression`, `PostincrementExpression`, `ConditionalExpression`, `ParenthesizedExpression`, `CastExpression`, `SignedCastExpression`, `ConcatenationExpression`, `MultipleConcatenationExpression`, `ReplicatedAssignmentPattern`, `StreamingConcatenationExpression`, `StreamExpression`, `StreamExpressionWithRange`, `InsideExpression`, `MinTypMaxExpression`, `ValueRangeExpression`, `EmptyQueueExpression`, `TaggedUnionExpression`, `CopyClassExpression`, `NewArrayExpression`, `NewClassExpression`, `SuperNewDefaultedArgsExpression` → all ⚪ BLOB.

### Assignment expressions (binary form with target)
| SyntaxKind | Class | Notes |
|---|---|---|
| `AssignmentExpression`, `AddAssignmentExpression`, `SubtractAssignmentExpression`, `MultiplyAssignmentExpression`, `DivideAssignmentExpression`, `ModAssignmentExpression`, `AndAssignmentExpression`, `OrAssignmentExpression`, `XorAssignmentExpression`, `LogicalLeftShiftAssignmentExpression`, `LogicalRightShiftAssignmentExpression`, `ArithmeticLeftShiftAssignmentExpression`, `ArithmeticRightShiftAssignmentExpression`, `NonblockingAssignmentExpression` | 🟢 PROMOTE | ⬜ — like ContinuousAssign but in procedural context. S3 already handles via parent always_ff. |

### Invocation / arguments
| SyntaxKind | Class | Status |
|---|---|---|
| `InvocationExpression`, `ArgumentList`, `OrderedArgument`, `NamedArgument`, `EmptyArgument`, `ArrayOrRandomizeMethodExpression`, `ArrayAndMethod`, `ArrayOrMethod`, `ArrayUniqueMethod`, `ArrayXorMethod` | 🔵 CONTAINER + 🟢 PROMOTE | ✅ partial (S5 covers `$clog2`) |
| `SystemName` | 🟢 PROMOTE | ✅ S5 |
| `WithClause`, `WithFunctionClause`, `WithFunctionSample` | 🔵 CONTAINER | ⬜ |

### Patterns (case/match)
`ExpressionPattern`, `VariablePattern`, `WildcardPattern`, `StructurePattern`, `TaggedPattern`, `ParenthesizedPattern`, `MatchesClause`, `OrderedStructurePatternMember`, `NamedStructurePatternMember`, `SimpleAssignmentPattern`, `StructuredAssignmentPattern`, `AssignmentPatternExpression`, `AssignmentPatternItem`, `DefaultPatternKeyExpression` → all 🔵 CONTAINER. Promote on demand for advanced pattern queries.

### Bad / unknown
`BadExpression`, `Unknown` → 🔵 CONTAINER; treat as parse-error fingerprints.

## 10. Generate

| SyntaxKind | Class | Status |
|---|---|---|
| `IfGenerate` | 🟢 PROMOTE | ⏳ — extend S12 |
| `CaseGenerate` | 🟢 PROMOTE | ⏳ — extend S12 |
| `LoopGenerate` | 🟢 PROMOTE | ⏳ S12a |
| `GenerateBlock` | 🟢 PROMOTE | ⏳ S12b |
| `GenerateRegion` | 🔵 CONTAINER | ⏳ |

## 11. Functions / Tasks / Subroutines

| SyntaxKind | Class | Status |
|---|---|---|
| `FunctionDeclaration` | 🟢 PROMOTE | ⏳ S10 |
| `TaskDeclaration` | 🟢 PROMOTE | ⏳ S10 |
| `FunctionPort`, `FunctionPortList`, `DefaultFunctionPort` | 🔵 CONTAINER | ⏳ |
| `FunctionPrototype`, `ClassMethodDeclaration`, `ClassMethodPrototype` | 🟢 PROMOTE | ⬜ for class methods |
| `LetDeclaration` | 🟢 PROMOTE | ⬜ |

## 12. Modports (interfaces)

| SyntaxKind | Class | Status |
|---|---|---|
| `ModportDeclaration` | 🟢 PROMOTE | ⏳ S11b |
| `ModportItem` | 🟢 PROMOTE | ⏳ — modport sub-node |
| `ModportSimplePortList`, `ModportSubroutinePortList` | 🔵 CONTAINER | ⏳ |
| `ModportNamedPort`, `ModportExplicitPort`, `ModportClockingPort`, `ModportSubroutinePort` | 🟢 PROMOTE | ⏳ — direction info per signal |

## 13. Clocking blocks / SVA

| SyntaxKind | Class | Status |
|---|---|---|
| `ClockingDeclaration`, `ClockingItem`, `ClockingDirection`, `ClockingSkew`, `DefaultClockingReference`, `DefaultSkewItem`, `DefaultDisableDeclaration` | 🟢 PROMOTE | ⬜ — `clocking_block` node, `clocked_by` edges |
| `PropertyDeclaration`, `SequenceDeclaration`, `PropertyType`, `SequenceType`, `PropertySpec` | 🟢 PROMOTE | ⬜ — SVA queryable surface |
| `SimplePropertyExpr`, `SimpleSequenceExpr`, `ParenthesizedPropertyExpr`, `ParenthesizedSequenceExpr` | 🔵 CONTAINER | ✅ partial |
| `AndPropertyExpr`, `OrPropertyExpr`, `IffPropertyExpr`, `ImpliesPropertyExpr`, `ImplicationPropertyExpr`, `FollowedByPropertyExpr`, `AcceptOnPropertyExpr`, `ConditionalPropertyExpr`, `CasePropertyExpr`, `StrongWeakPropertyExpr`, `UnaryPropertyExpr`, `UnarySelectPropertyExpr`, `UntilPropertyExpr`, `UntilWithPropertyExpr`, `SUntilPropertyExpr`, `SUntilWithPropertyExpr`, `ClockingPropertyExpr`, `DisableIff` | ⚪ BLOB | ⬜ — SVA operator tree, like arithmetic operators |
| `AndSequenceExpr`, `OrSequenceExpr`, `IntersectSequenceExpr`, `WithinSequenceExpr`, `ThroughoutSequenceExpr`, `DelayedSequenceExpr`, `DelayedSequenceElement`, `FirstMatchSequenceExpr`, `ClockingSequenceExpr`, `SequenceRepetition`, `SequenceMatchList`, `IntersectClause` | ⚪ BLOB | ⬜ |

## 14. Coverage (covergroups)

| SyntaxKind | Class | Status |
|---|---|---|
| `CovergroupDeclaration` | 🟢 PROMOTE | ⬜ |
| `Coverpoint`, `CoverCross`, `CoverageBins`, `CoverageBinsArraySize`, `CoverageIffClause`, `CoverageOption`, `BlockCoverageEvent`, `WithFunctionSample` | 🟢 PROMOTE | ⬜ |
| `IdWithExprCoverageBinInitializer`, `ExpressionCoverageBinInitializer`, `RangeCoverageBinInitializer`, `TransListCoverageBinInitializer`, `DefaultCoverageBinInitializer`, `TransRange`, `TransRepeatRange`, `TransSet` | 🔵 CONTAINER | ⬜ |
| `BinSelectWithFilterExpr`, `BinaryBinsSelectExpr`, `BinsSelectConditionExpr`, `UnaryBinsSelectExpr`, `SimpleBinsSelectExpr`, `ParenthesizedBinsSelectExpr`, `BinsSelection` | ⚪ BLOB | ⬜ |

## 15. Constraints (UVM / class randomization)

| SyntaxKind | Class | Status |
|---|---|---|
| `ConstraintBlock`, `ConstraintDeclaration`, `ConstraintPrototype` | 🟢 PROMOTE | ⬜ |
| `ConditionalConstraint`, `LoopConstraint`, `DisableConstraint`, `SolveBeforeConstraint`, `ImplicationConstraint`, `UniquenessConstraint`, `ElseConstraintClause`, `ExpressionConstraint`, `DistConstraintList`, `DistItem`, `DistWeight`, `DefaultDistItem`, `ExpressionOrDist`, `RandJoinClause` | 🔵 CONTAINER + ⚪ BLOB | ⬜ |

## 16. Hierarchy / cross-module

| SyntaxKind | Class | Status |
|---|---|---|
| `PackageImportDeclaration`, `PackageImportItem`, `PackageExportDeclaration`, `PackageExportAllDeclaration` | 🟢 PROMOTE | ⬜ — `imports_package` edges |
| `TimeUnitsDeclaration` | ⚪ BLOB | ⬜ |
| `ExtendsClause`, `ImplementsClause`, `DefaultExtendsClauseArg`, `ClassPropertyDeclaration`, `ClassSpecifier`, `LocalVariableDeclaration` | 🟢 PROMOTE | ⬜ — class inheritance edges |
| `CheckerDataDeclaration` | 🔵 CONTAINER | ⬜ |
| `AssertionItemPort`, `AssertionItemPortList` | 🔵 CONTAINER | ⬜ |

## 17. SDF / Specify / Path delays (specify blocks)

All ⚫ OUT-OF-SCOPE for graph queries (timing back-annotation domain):
`SpecifyBlock`, `PathDeclaration`, `PathDescription`, `SimplePathSuffix`, `EdgeSensitivePathSuffix`, `ConditionalPathDeclaration`, `IfNonePathDeclaration`, `EdgeControlSpecifier`, `EdgeDescriptor`, `DriveStrength`, `PullStrength`, `ChargeStrength`, `PulseStyleDeclaration`, `Delay3`, `DividerClause`, `ColonExpressionClause`, `NoUnconnectedDriveDirective`, `UnconnectedDriveDirective`.

## 18. Random sequences (`randsequence`)

⚫ OUT-OF-SCOPE for typical RTL/DV graph use:
`RandSequenceStatement`, `Production`, `RsCase`, `RsIfElse`, `RsElseClause`, `RsCodeBlock`, `RsRule`, `RsProdItem`, `RsRepeat`, `RsWeightClause`.

## 19. Preprocessor directives & macros — 🟣 DIRECTIVE

Live in raw syntax tree, mostly invisible post-elab. Lift trivially (they appear as `SyntaxKind` items), but DO NOT promote to queryable nodes — they're not part of the elaborated graph:

`DefineDirective`, `UndefDirective`, `UndefineAllDirective`, `IncludeDirective`, `IfDefDirective`, `IfNDefDirective`, `ElsIfDirective`, `ElseDirective`, `EndIfDirective`, `LineDirective`, `PragmaDirective`, `BeginKeywordsDirective`, `EndKeywordsDirective`, `ResetAllDirective`, `TimeScaleDirective`, `DefaultNetTypeDirective`, `DefaultDecayTimeDirective`, `DefaultTriregStrengthDirective`, `DelayModeDistributedDirective`, `DelayModePathDirective`, `DelayModeUnitDirective`, `DelayModeZeroDirective`, `CellDefineDirective`, `EndCellDefineDirective`, `ProtectDirective`, `EndProtectDirective`, `ProtectedDirective`, `EndProtectedDirective`, `MacroUsage`, `MacroFormalArgument`, `MacroFormalArgumentList`, `MacroActualArgument`, `MacroActualArgumentList`, `MacroArgumentDefault`, `BinaryConditionalDirectiveExpression`, `UnaryConditionalDirectiveExpression`, `NamedConditionalDirectiveExpression`, `ParenthesizedConditionalDirectiveExpression`, `NamePragmaExpression`, `NumberPragmaExpression`, `SimplePragmaExpression`, `ParenPragmaExpression`, `NameValuePragmaExpression`.

## 20. Misc lists / atoms (always 🔵 CONTAINER)

`SyntaxList`, `SeparatedList`, `TokenList`, `AttributeInstance`, `AttributeSpec`, `EmptyMember`, `NamedLabel`, `Untyped`, `Unknown`.

---

# Summary table — coverage by class

| Class | # SyntaxKinds (approx) | Currently covered | In flight | Future |
|-------|------------------------|-------------------|-----------|--------|
| 🟢 PROMOTE | ~95 | 18 (S1..S6) | 18 (S7..S12 Phases 1–7) | ~59 (SVA, class, covergroup, constraint, package-import, etc.) |
| 🔵 CONTAINER | ~140 | ~all (class-generic lift handles them) | — | — |
| ⚪ BLOB | ~250 | ~all (round-trip preserves payload) | — | — |
| 🟣 DIRECTIVE | ~45 | n/a (don't reach elab) | — | — |
| ⚫ OUT-OF-SCOPE | ~30 (UDP, SDF, library, config, randsequence) | n/a | — | — |
| **TOTAL** | **536** | | | |

**Bucket-1 progress (queryable layer):**
- Currently queryable: **18 of ~95 PROMOTE candidates ≈ 19%**
- After Phases 1–7 ship: **36 of ~95 ≈ 38%**
- Long-tail to 100%: SVA (concurrent assertions, properties, sequences), classes + UVM, covergroups, constraints, package imports, clocking blocks, bind directives, immediate assertions, defparam, virtual interfaces.

---

# How to drive this checklist to completion

1. **Run the corpus expansion loop** (S7–S12 already in flight) to close Phases 1–7.
2. After Phase 7 ships, pick the next 5 highest-value PROMOTE items by **OpenTitan AES occurrence frequency** — measured by inventorying AES `.sv` and counting per-SyntaxKind hits. Likely: `AssertPropertyStatement`, `PropertyDeclaration`, `SequenceDeclaration`, `PackageImportDeclaration`, `CovergroupDeclaration`.
3. For each one: one Ralph iteration (failing query test → rule → invariant) until the OpenTitan demo can be re-rendered with no remaining unpromoted constructs.
4. Stop conditions for "bucket 1 complete":
   - Every 🟢 PROMOTE item in this checklist is ✅.
   - `build_kg(opentitan/hw/ip/aes/rtl/*.sv)` reports `semantic_leaks == []`.
   - Round-trip byte-equal on every `.sv` in the corpus.
   - Structural-invariant suite green.

**Out-of-scope items (⚫) and directives (🟣) never get rules** — that's the point of the classification. Closing the checklist means closing all 🟢 PROMOTE items, not all 536 SyntaxKinds.
