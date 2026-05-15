# Bucket 1 — SV-AST elaboration coverage checklist (per-SyntaxKind)
Total `pyslang.SyntaxKind` enum size: **536**.
Per-row checkboxes — no grouping. Each SyntaxKind has its own status.

## Column meanings
| Column | Meaning |
|--|--|
| **Class** | PROMOTE (queryable node + typed edges), CONTAINER (lifted, traversable, not promoted), BLOB (payload only — operator/literal/type detail), DIRECTIVE (preprocessor — invisible post-elab), OUT-OF-SCOPE (UDP, SDF, library, config, randsequence). |
| **Struct** | ✅ = seen in `ast_classes.json` (test-corpus exercised, round-trip green). ⬜ = NOT yet seen in any test source → structural lift is class-generic so it should work, but is **unverified**. |
| **Semantic** | ✅ = promoted by an active S-rule. ⏳ = in flight in the running expansion loop. ⬜ = PROMOTE candidate with no rule yet. — = not applicable (BLOB/CONTAINER/DIRECTIVE/OOS — no semantic promotion expected). |
| **Owner** | The S-rule that promotes this kind, or `structural lift only` for BLOB/CONTAINER, or the reason for —. |

## Roll-up
| Class | Count | Struct ✅ | Sem ✅ | Sem ⏳ | Sem ⬜ |
|--|--|--|--|--|--|
| PROMOTE | 135 | 49 | 85 | 0 | 50 |
| CONTAINER | 88 | 23 | 0 | 0 | 0 |
| BLOB | 213 | 25 | 0 | 0 | 0 |
| DIRECTIVE | 42 | 0 | 0 | 0 | 0 |
| OUT-OF-SCOPE | 58 | 1 | 0 | 0 | 0 |
| **Total** | **536** | **98** | | | |

## PROMOTE (135 items)
| SyntaxKind | Struct | Semantic | Owner |
|--|--|--|--|
| `AlwaysBlock` | ⬜ | ✅ | S34 |
| `AlwaysCombBlock` | ⬜ | ✅ | S8 |
| `AlwaysFFBlock` | ⬜ | ✅ | S3 |
| `AlwaysLatchBlock` | ⬜ | ✅ | S35 |
| `AnonymousProgram` | ⬜ | ⬜ | future |
| `AssertPropertyStatement` | ⬜ | ✅ | S16 |
| `AssertionItemPort` | ⬜ | ⬜ | future |
| `AssertionItemPortList` | ⬜ | ⬜ | future |
| `AssumePropertyStatement` | ⬜ | ✅ | S16 |
| `BindDirective` | ✅ | ✅ | S13 |
| `BindTargetList` | ⬜ | ⬜ | future |
| `BlockingEventTriggerStatement` | ⬜ | ✅ | S21 |
| `CaseGenerate` | ⬜ | ✅ | S12c |
| `CheckerDataDeclaration` | ⬜ | ⬜ | future |
| `CheckerDeclaration` | ⬜ | ✅ | S28 |
| `CheckerInstanceStatement` | ⬜ | ⬜ | future |
| `CheckerInstantiation` | ⬜ | ✅ | S28 |
| `ClassDeclaration` | ✅ | ✅ | S24 |
| `ClassMethodDeclaration` | ⬜ | ✅ | S26 |
| `ClassMethodPrototype` | ✅ | ✅ | S26 |
| `ClassPropertyDeclaration` | ✅ | ✅ | S26 |
| `ClassSpecifier` | ⬜ | ⬜ | future |
| `ClockingDeclaration` | ✅ | ✅ | S18 |
| `ClockingItem` | ✅ | ⬜ | future |
| `ConcurrentAssertionMember` | ✅ | ⬜ | future |
| `ConstraintBlock` | ⬜ | ⬜ | future |
| `ConstraintDeclaration` | ⬜ | ✅ | S27 |
| `ConstraintPrototype` | ⬜ | ✅ | S27 |
| `ConstructorName` | ⬜ | ⬜ | future |
| `ContinuousAssign` | ✅ | ✅ | S2 |
| `CoverCross` | ✅ | ✅ | S23 |
| `CoverPropertyStatement` | ⬜ | ✅ | S16 |
| `CoverSequenceStatement` | ⬜ | ✅ | S16 |
| `CoverageBins` | ⬜ | ⬜ | future |
| `CovergroupDeclaration` | ✅ | ✅ | S22 |
| `Coverpoint` | ✅ | ✅ | S23 |
| `DPIExport` | ⬜ | ⬜ | future |
| `DPIImport` | ⬜ | ⬜ | future |
| `Declarator` | ✅ | ✅ | S1 |
| `DefParam` | ⬜ | ⬜ | future |
| `DefParamAssignment` | ⬜ | ⬜ | future |
| `DefaultClockingReference` | ⬜ | ✅ | S40 |
| `DefaultDisableDeclaration` | ⬜ | ✅ | S39 |
| `DefaultFunctionPort` | ⬜ | ⬜ | future |
| `DeferredAssertion` | ✅ | ⬜ | future |
| `EnumType` | ✅ | ✅ | S9c |
| `ExpectPropertyStatement` | ⬜ | ✅ | S16 |
| `ExplicitAnsiPort` | ⬜ | ⬜ | future |
| `ExplicitNonAnsiPort` | ⬜ | ⬜ | future |
| `ExtendsClause` | ✅ | ✅ | S25 |
| `ExternInterfaceMethod` | ⬜ | ⬜ | future |
| `ExternModuleDecl` | ⬜ | ✅ | S29 |
| `ExternUdpDecl` | ⬜ | ⬜ | future |
| `FinalBlock` | ⬜ | ✅ | S37 |
| `ForwardTypeRestriction` | ⬜ | ⬜ | future |
| `ForwardTypedefDeclaration` | ⬜ | ✅ | S31 |
| `FunctionDeclaration` | ✅ | ✅ | S10 |
| `FunctionPort` | ✅ | ⬜ | future |
| `FunctionPortList` | ✅ | ⬜ | future |
| `FunctionPrototype` | ✅ | ⬜ | future |
| `GenerateBlock` | ✅ | ✅ | S12b |
| `GenerateRegion` | ✅ | ✅ | S12c |
| `GenvarDeclaration` | ⬜ | ✅ | S38 |
| `HierarchicalInstance` | ✅ | ✅ | S6 |
| `HierarchyInstantiation` | ✅ | ✅ | S6 |
| `IdentifierName` | ✅ | ✅ | S4 |
| `IdentifierSelectName` | ✅ | ✅ | S4 |
| `IfGenerate` | ⬜ | ✅ | S12c |
| `ImmediateAssertStatement` | ⬜ | ✅ | S17 |
| `ImmediateAssertionMember` | ⬜ | ⬜ | future |
| `ImmediateAssumeStatement` | ⬜ | ✅ | S17 |
| `ImmediateCoverStatement` | ⬜ | ✅ | S17 |
| `ImplementsClause` | ⬜ | ✅ | S25 |
| `ImplicitAnsiPort` | ✅ | ✅ | S1 |
| `ImplicitNonAnsiPort` | ⬜ | ⬜ | future |
| `InitialBlock` | ⬜ | ✅ | S36 |
| `InstanceName` | ✅ | ✅ | S6 |
| `InterfaceDeclaration` | ⬜ | ✅ | S11a |
| `InterfaceHeader` | ⬜ | ⬜ | future |
| `InterfacePortHeader` | ⬜ | ⬜ | future |
| `InvocationExpression` | ✅ | ✅ | S5 |
| `LetDeclaration` | ⬜ | ⬜ | future |
| `LocalVariableDeclaration` | ⬜ | ⬜ | future |
| `LoopGenerate` | ✅ | ✅ | S12a |
| `MemberAccessExpression` | ⬜ | ⬜ | future |
| `ModportClockingPort` | ⬜ | ✅ | S11b |
| `ModportDeclaration` | ✅ | ✅ | S11b |
| `ModportExplicitPort` | ⬜ | ✅ | S11b |
| `ModportItem` | ✅ | ✅ | S11b |
| `ModportNamedPort` | ✅ | ✅ | S11b |
| `ModportSimplePortList` | ✅ | ✅ | S11b |
| `ModportSubroutinePort` | ⬜ | ✅ | S11b |
| `ModportSubroutinePortList` | ⬜ | ✅ | S11b |
| `ModuleDeclaration` | ✅ | ✅ | S1 |
| `ModuleHeader` | ✅ | ⬜ | future |
| `NamedParamAssignment` | ✅ | ✅ | S7 |
| `NamedPortConnection` | ✅ | ✅ | S6 |
| `NetAlias` | ⬜ | ⬜ | future |
| `NetDeclaration` | ⬜ | ⬜ | future |
| `NetTypeDeclaration` | ⬜ | ⬜ | future |
| `NonblockingEventTriggerStatement` | ⬜ | ✅ | S21 |
| `OrderedParamAssignment` | ⬜ | ✅ | S7 |
| `OrderedPortConnection` | ⬜ | ⬜ | future |
| `PackageDeclaration` | ⬜ | ✅ | S9a |
| `PackageExportAllDeclaration` | ⬜ | ⬜ | future |
| `PackageExportDeclaration` | ⬜ | ✅ | S32 |
| `PackageHeader` | ⬜ | ⬜ | future |
| `PackageImportDeclaration` | ✅ | ✅ | S32 |
| `PackageImportItem` | ✅ | ⬜ | future |
| `ParameterDeclaration` | ✅ | ✅ | S1 |
| `ParameterValueAssignment` | ✅ | ✅ | S7 |
| `PortConcatenation` | ⬜ | ⬜ | future |
| `PortDeclaration` | ⬜ | ⬜ | future |
| `PortReference` | ⬜ | ⬜ | future |
| `PrimitiveInstantiation` | ⬜ | ✅ | S33 |
| `ProceduralAssignStatement` | ✅ | ✅ | S19 |
| `ProceduralDeassignStatement` | ✅ | ✅ | S19 |
| `ProceduralForceStatement` | ⬜ | ✅ | S20 |
| `ProceduralReleaseStatement` | ⬜ | ✅ | S20 |
| `ProgramDeclaration` | ⬜ | ✅ | S30 |
| `ProgramHeader` | ⬜ | ⬜ | future |
| `PropertyDeclaration` | ✅ | ✅ | S14 |
| `RestrictPropertyStatement` | ⬜ | ✅ | S16 |
| `SequenceDeclaration` | ✅ | ✅ | S15 |
| `StructType` | ⬜ | ✅ | S31 |
| `StructUnionMember` | ⬜ | ⬜ | future |
| `SystemName` | ✅ | ✅ | S5 |
| `TaskDeclaration` | ⬜ | ✅ | S10 |
| `TimeUnitsDeclaration` | ⬜ | ⬜ | future |
| `TypeParameterDeclaration` | ✅ | ⬜ | future |
| `TypedefDeclaration` | ✅ | ✅ | S9b |
| `UnionType` | ⬜ | ✅ | S31 |
| `UserDefinedNetDeclaration` | ⬜ | ⬜ | future |
| `VariablePortHeader` | ✅ | ✅ | S1 |
| `VirtualInterfaceType` | ⬜ | ⬜ | future |

## CONTAINER (88 items)
| SyntaxKind | Struct | Semantic | Owner |
|--|--|--|--|
| `ActionBlock` | ✅ | — | structural lift only |
| `AnsiPortList` | ✅ | — | structural lift only |
| `ArgumentList` | ✅ | — | structural lift only |
| `ArrayAndMethod` | ⬜ | — | structural lift only |
| `ArrayOrMethod` | ⬜ | — | structural lift only |
| `ArrayUniqueMethod` | ⬜ | — | structural lift only |
| `ArrayXorMethod` | ⬜ | — | structural lift only |
| `AscendingRangeSelect` | ⬜ | — | structural lift only |
| `AssignmentPatternItem` | ⬜ | — | structural lift only |
| `AttributeInstance` | ⬜ | — | structural lift only |
| `AttributeSpec` | ✅ | — | structural lift only |
| `BitSelect` | ✅ | — | structural lift only |
| `CaseStatement` | ✅ | — | structural lift only |
| `CompilationUnit` | ✅ | — | structural lift only |
| `ConditionalPredicate` | ✅ | — | structural lift only |
| `ConditionalStatement` | ✅ | — | structural lift only |
| `CoverageBinsArraySize` | ⬜ | — | structural lift only |
| `CycleDelay` | ⬜ | — | structural lift only |
| `DataDeclaration` | ✅ | — | structural lift only |
| `DefaultCaseItem` | ✅ | — | structural lift only |
| `DefaultPropertyCaseItem` | ⬜ | — | structural lift only |
| `DefaultRsCaseItem` | ⬜ | — | structural lift only |
| `DefaultSkewItem` | ✅ | — | structural lift only |
| `DelayControl` | ⬜ | — | structural lift only |
| `DelayedSequenceElement` | ✅ | — | structural lift only |
| `DescendingRangeSelect` | ⬜ | — | structural lift only |
| `DisableForkStatement` | ⬜ | — | structural lift only |
| `DisableIff` | ⬜ | — | structural lift only |
| `DisableStatement` | ⬜ | — | structural lift only |
| `DoWhileStatement` | ⬜ | — | structural lift only |
| `ElementSelect` | ✅ | — | structural lift only |
| `EmptyArgument` | ⬜ | — | structural lift only |
| `EmptyMember` | ⬜ | — | structural lift only |
| `EmptyNonAnsiPort` | ⬜ | — | structural lift only |
| `EmptyPortConnection` | ⬜ | — | structural lift only |
| `EmptyStatement` | ✅ | — | structural lift only |
| `EmptyTimingCheckArg` | ⬜ | — | structural lift only |
| `EventControl` | ⬜ | — | structural lift only |
| `ExpressionStatement` | ✅ | — | structural lift only |
| `ExpressionTimingCheckArg` | ⬜ | — | structural lift only |
| `ForLoopStatement` | ⬜ | — | structural lift only |
| `ForVariableDeclaration` | ⬜ | — | structural lift only |
| `ForeachLoopList` | ⬜ | — | structural lift only |
| `ForeachLoopStatement` | ⬜ | — | structural lift only |
| `ForeverStatement` | ✅ | — | structural lift only |
| `ImplicitEventControl` | ⬜ | — | structural lift only |
| `JumpStatement` | ⬜ | — | structural lift only |
| `LocalScope` | ⬜ | — | structural lift only |
| `LoopStatement` | ⬜ | — | structural lift only |
| `MacroActualArgumentList` | ⬜ | — | structural lift only |
| `MacroFormalArgumentList` | ⬜ | — | structural lift only |
| `NamedArgument` | ⬜ | — | structural lift only |
| `NamedLabel` | ✅ | — | structural lift only |
| `NamedStructurePatternMember` | ⬜ | — | structural lift only |
| `NetPortHeader` | ⬜ | — | structural lift only |
| `NonAnsiPortList` | ⬜ | — | structural lift only |
| `OrderedArgument` | ✅ | — | structural lift only |
| `OrderedStructurePatternMember` | ⬜ | — | structural lift only |
| `ParallelBlockStatement` | ⬜ | — | structural lift only |
| `ParameterDeclarationStatement` | ✅ | — | structural lift only |
| `ParameterPortList` | ✅ | — | structural lift only |
| `ParenExpressionList` | ⬜ | — | structural lift only |
| `PatternCaseItem` | ⬜ | — | structural lift only |
| `RangeList` | ⬜ | — | structural lift only |
| `RepeatedEventControl` | ⬜ | — | structural lift only |
| `ReturnStatement` | ⬜ | — | structural lift only |
| `RootScope` | ⬜ | — | structural lift only |
| `SeparatedList` | ⬜ | — | structural lift only |
| `SequentialBlockStatement` | ⬜ | — | structural lift only |
| `SimpleRangeSelect` | ⬜ | — | structural lift only |
| `StandardCaseItem` | ✅ | — | structural lift only |
| `StandardPropertyCaseItem` | ⬜ | — | structural lift only |
| `StandardRsCaseItem` | ⬜ | — | structural lift only |
| `StreamExpressionWithRange` | ⬜ | — | structural lift only |
| `SuperHandle` | ⬜ | — | structural lift only |
| `SyntaxList` | ⬜ | — | structural lift only |
| `ThisHandle` | ⬜ | — | structural lift only |
| `TimingControlStatement` | ✅ | — | structural lift only |
| `TokenList` | ⬜ | — | structural lift only |
| `UnitScope` | ⬜ | — | structural lift only |
| `Unknown` | ⬜ | — | structural lift only |
| `Untyped` | ⬜ | — | structural lift only |
| `VoidCastedCallStatement` | ⬜ | — | structural lift only |
| `WaitForkStatement` | ⬜ | — | structural lift only |
| `WaitOrderStatement` | ⬜ | — | structural lift only |
| `WaitStatement` | ⬜ | — | structural lift only |
| `WildcardPortConnection` | ⬜ | — | structural lift only |
| `WildcardPortList` | ⬜ | — | structural lift only |

## BLOB (213 items)
| SyntaxKind | Struct | Semantic | Owner |
|--|--|--|--|
| `AcceptOnPropertyExpr` | ⬜ | — | structural lift only |
| `AddAssignmentExpression` | ⬜ | — | structural lift only |
| `AddExpression` | ⬜ | — | structural lift only |
| `AndAssignmentExpression` | ⬜ | — | structural lift only |
| `AndPropertyExpr` | ⬜ | — | structural lift only |
| `AndSequenceExpr` | ⬜ | — | structural lift only |
| `ArithmeticLeftShiftAssignmentExpression` | ⬜ | — | structural lift only |
| `ArithmeticRightShiftAssignmentExpression` | ⬜ | — | structural lift only |
| `ArithmeticShiftLeftExpression` | ⬜ | — | structural lift only |
| `ArithmeticShiftRightExpression` | ⬜ | — | structural lift only |
| `ArrayOrRandomizeMethodExpression` | ⬜ | — | structural lift only |
| `AssignmentExpression` | ⬜ | — | structural lift only |
| `AssignmentPatternExpression` | ⬜ | — | structural lift only |
| `BadExpression` | ⬜ | — | structural lift only |
| `BinSelectWithFilterExpr` | ⬜ | — | structural lift only |
| `BinaryAndExpression` | ⬜ | — | structural lift only |
| `BinaryBinsSelectExpr` | ⬜ | — | structural lift only |
| `BinaryBlockEventExpression` | ⬜ | — | structural lift only |
| `BinaryEventExpression` | ✅ | — | structural lift only |
| `BinaryOrExpression` | ⬜ | — | structural lift only |
| `BinaryXnorExpression` | ⬜ | — | structural lift only |
| `BinaryXorExpression` | ⬜ | — | structural lift only |
| `BinsSelectConditionExpr` | ⬜ | — | structural lift only |
| `BinsSelection` | ⬜ | — | structural lift only |
| `BitType` | ⬜ | — | structural lift only |
| `BlockCoverageEvent` | ⬜ | — | structural lift only |
| `ByteType` | ⬜ | — | structural lift only |
| `CHandleType` | ⬜ | — | structural lift only |
| `CaseEqualityExpression` | ⬜ | — | structural lift only |
| `CaseInequalityExpression` | ⬜ | — | structural lift only |
| `CasePropertyExpr` | ⬜ | — | structural lift only |
| `CastExpression` | ⬜ | — | structural lift only |
| `ClassName` | ⬜ | — | structural lift only |
| `ClockingDirection` | ✅ | — | structural lift only |
| `ClockingPropertyExpr` | ⬜ | — | structural lift only |
| `ClockingSequenceExpr` | ✅ | — | structural lift only |
| `ClockingSkew` | ✅ | — | structural lift only |
| `ConcatenationExpression` | ✅ | — | structural lift only |
| `ConditionalConstraint` | ⬜ | — | structural lift only |
| `ConditionalExpression` | ⬜ | — | structural lift only |
| `ConditionalPattern` | ✅ | — | structural lift only |
| `ConditionalPropertyExpr` | ⬜ | — | structural lift only |
| `CopyClassExpression` | ⬜ | — | structural lift only |
| `CoverageIffClause` | ⬜ | — | structural lift only |
| `CoverageOption` | ⬜ | — | structural lift only |
| `DefaultCoverageBinInitializer` | ⬜ | — | structural lift only |
| `DefaultDistItem` | ⬜ | — | structural lift only |
| `DefaultExtendsClauseArg` | ⬜ | — | structural lift only |
| `DefaultPatternKeyExpression` | ⬜ | — | structural lift only |
| `DelayedSequenceExpr` | ✅ | — | structural lift only |
| `DisableConstraint` | ⬜ | — | structural lift only |
| `DistConstraintList` | ⬜ | — | structural lift only |
| `DistItem` | ⬜ | — | structural lift only |
| `DistWeight` | ⬜ | — | structural lift only |
| `DivideAssignmentExpression` | ⬜ | — | structural lift only |
| `DivideExpression` | ⬜ | — | structural lift only |
| `DotMemberClause` | ⬜ | — | structural lift only |
| `ElementSelectExpression` | ⬜ | — | structural lift only |
| `ElseClause` | ✅ | — | structural lift only |
| `ElseConstraintClause` | ⬜ | — | structural lift only |
| `ElsePropertyClause` | ⬜ | — | structural lift only |
| `EmptyIdentifierName` | ⬜ | — | structural lift only |
| `EmptyQueueExpression` | ⬜ | — | structural lift only |
| `EqualityExpression` | ⬜ | — | structural lift only |
| `EqualsAssertionArgClause` | ⬜ | — | structural lift only |
| `EqualsTypeClause` | ✅ | — | structural lift only |
| `EqualsValueClause` | ✅ | — | structural lift only |
| `EventControlWithExpression` | ✅ | — | structural lift only |
| `EventType` | ⬜ | — | structural lift only |
| `ExpressionConstraint` | ⬜ | — | structural lift only |
| `ExpressionCoverageBinInitializer` | ⬜ | — | structural lift only |
| `ExpressionOrDist` | ⬜ | — | structural lift only |
| `ExpressionPattern` | ⬜ | — | structural lift only |
| `FilePathSpec` | ⬜ | — | structural lift only |
| `FirstMatchSequenceExpr` | ⬜ | — | structural lift only |
| `FollowedByPropertyExpr` | ⬜ | — | structural lift only |
| `GreaterThanEqualExpression` | ⬜ | — | structural lift only |
| `GreaterThanExpression` | ⬜ | — | structural lift only |
| `IdWithExprCoverageBinInitializer` | ⬜ | — | structural lift only |
| `IffEventClause` | ⬜ | — | structural lift only |
| `IffPropertyExpr` | ⬜ | — | structural lift only |
| `ImplicationConstraint` | ⬜ | — | structural lift only |
| `ImplicationPropertyExpr` | ⬜ | — | structural lift only |
| `ImplicitType` | ✅ | — | structural lift only |
| `ImpliesPropertyExpr` | ⬜ | — | structural lift only |
| `InequalityExpression` | ⬜ | — | structural lift only |
| `InsideExpression` | ⬜ | — | structural lift only |
| `IntType` | ⬜ | — | structural lift only |
| `IntegerLiteralExpression` | ⬜ | — | structural lift only |
| `IntegerType` | ✅ | — | structural lift only |
| `IntegerVectorExpression` | ✅ | — | structural lift only |
| `IntersectClause` | ⬜ | — | structural lift only |
| `IntersectSequenceExpr` | ⬜ | — | structural lift only |
| `LessThanEqualExpression` | ⬜ | — | structural lift only |
| `LessThanExpression` | ⬜ | — | structural lift only |
| `LogicType` | ⬜ | — | structural lift only |
| `LogicalAndExpression` | ⬜ | — | structural lift only |
| `LogicalEquivalenceExpression` | ⬜ | — | structural lift only |
| `LogicalImplicationExpression` | ⬜ | — | structural lift only |
| `LogicalLeftShiftAssignmentExpression` | ⬜ | — | structural lift only |
| `LogicalOrExpression` | ⬜ | — | structural lift only |
| `LogicalRightShiftAssignmentExpression` | ⬜ | — | structural lift only |
| `LogicalShiftLeftExpression` | ⬜ | — | structural lift only |
| `LogicalShiftRightExpression` | ⬜ | — | structural lift only |
| `LongIntType` | ⬜ | — | structural lift only |
| `LoopConstraint` | ⬜ | — | structural lift only |
| `MatchesClause` | ⬜ | — | structural lift only |
| `MinTypMaxExpression` | ⬜ | — | structural lift only |
| `ModAssignmentExpression` | ⬜ | — | structural lift only |
| `ModExpression` | ⬜ | — | structural lift only |
| `MultipleConcatenationExpression` | ⬜ | — | structural lift only |
| `MultiplyAssignmentExpression` | ⬜ | — | structural lift only |
| `MultiplyExpression` | ⬜ | — | structural lift only |
| `NamedBlockClause` | ✅ | — | structural lift only |
| `NamedType` | ✅ | — | structural lift only |
| `NewArrayExpression` | ⬜ | — | structural lift only |
| `NewClassExpression` | ⬜ | — | structural lift only |
| `NonblockingAssignmentExpression` | ⬜ | — | structural lift only |
| `NullLiteralExpression` | ⬜ | — | structural lift only |
| `OrAssignmentExpression` | ⬜ | — | structural lift only |
| `OrPropertyExpr` | ⬜ | — | structural lift only |
| `OrSequenceExpr` | ⬜ | — | structural lift only |
| `ParenthesizedBinsSelectExpr` | ⬜ | — | structural lift only |
| `ParenthesizedEventExpression` | ✅ | — | structural lift only |
| `ParenthesizedExpression` | ✅ | — | structural lift only |
| `ParenthesizedPattern` | ⬜ | — | structural lift only |
| `ParenthesizedPropertyExpr` | ⬜ | — | structural lift only |
| `ParenthesizedSequenceExpr` | ⬜ | — | structural lift only |
| `PostdecrementExpression` | ⬜ | — | structural lift only |
| `PostincrementExpression` | ⬜ | — | structural lift only |
| `PowerExpression` | ⬜ | — | structural lift only |
| `PrimaryBlockEventExpression` | ⬜ | — | structural lift only |
| `PropertySpec` | ✅ | — | structural lift only |
| `PropertyType` | ⬜ | — | structural lift only |
| `QueueDimensionSpecifier` | ⬜ | — | structural lift only |
| `RandJoinClause` | ⬜ | — | structural lift only |
| `RangeCoverageBinInitializer` | ⬜ | — | structural lift only |
| `RangeDimensionSpecifier` | ✅ | — | structural lift only |
| `RealLiteralExpression` | ⬜ | — | structural lift only |
| `RealTimeType` | ⬜ | — | structural lift only |
| `RealType` | ⬜ | — | structural lift only |
| `RegType` | ⬜ | — | structural lift only |
| `ReplicatedAssignmentPattern` | ⬜ | — | structural lift only |
| `SUntilPropertyExpr` | ⬜ | — | structural lift only |
| `SUntilWithPropertyExpr` | ⬜ | — | structural lift only |
| `ScopedName` | ⬜ | — | structural lift only |
| `SequenceMatchList` | ⬜ | — | structural lift only |
| `SequenceRepetition` | ⬜ | — | structural lift only |
| `SequenceType` | ⬜ | — | structural lift only |
| `ShortIntType` | ⬜ | — | structural lift only |
| `ShortRealType` | ⬜ | — | structural lift only |
| `SignalEventExpression` | ✅ | — | structural lift only |
| `SignedCastExpression` | ⬜ | — | structural lift only |
| `SimpleAssignmentPattern` | ⬜ | — | structural lift only |
| `SimpleBinsSelectExpr` | ⬜ | — | structural lift only |
| `SimplePropertyExpr` | ✅ | — | structural lift only |
| `SimpleSequenceExpr` | ✅ | — | structural lift only |
| `SolveBeforeConstraint` | ⬜ | — | structural lift only |
| `StreamExpression` | ⬜ | — | structural lift only |
| `StreamingConcatenationExpression` | ⬜ | — | structural lift only |
| `StringLiteralExpression` | ⬜ | — | structural lift only |
| `StringType` | ⬜ | — | structural lift only |
| `StrongWeakPropertyExpr` | ⬜ | — | structural lift only |
| `StructurePattern` | ⬜ | — | structural lift only |
| `StructuredAssignmentPattern` | ⬜ | — | structural lift only |
| `SubtractAssignmentExpression` | ⬜ | — | structural lift only |
| `SubtractExpression` | ⬜ | — | structural lift only |
| `SuperNewDefaultedArgsExpression` | ⬜ | — | structural lift only |
| `TaggedPattern` | ⬜ | — | structural lift only |
| `TaggedUnionExpression` | ⬜ | — | structural lift only |
| `ThroughoutSequenceExpr` | ⬜ | — | structural lift only |
| `TimeLiteralExpression` | ⬜ | — | structural lift only |
| `TimeType` | ⬜ | — | structural lift only |
| `TimingControlExpression` | ⬜ | — | structural lift only |
| `TransListCoverageBinInitializer` | ⬜ | — | structural lift only |
| `TransRange` | ⬜ | — | structural lift only |
| `TransRepeatRange` | ⬜ | — | structural lift only |
| `TransSet` | ⬜ | — | structural lift only |
| `TypeAssignment` | ✅ | — | structural lift only |
| `TypeReference` | ⬜ | — | structural lift only |
| `UnaryBinsSelectExpr` | ⬜ | — | structural lift only |
| `UnaryBitwiseAndExpression` | ⬜ | — | structural lift only |
| `UnaryBitwiseNandExpression` | ⬜ | — | structural lift only |
| `UnaryBitwiseNorExpression` | ⬜ | — | structural lift only |
| `UnaryBitwiseNotExpression` | ⬜ | — | structural lift only |
| `UnaryBitwiseOrExpression` | ⬜ | — | structural lift only |
| `UnaryBitwiseXnorExpression` | ⬜ | — | structural lift only |
| `UnaryBitwiseXorExpression` | ⬜ | — | structural lift only |
| `UnaryLogicalNotExpression` | ⬜ | — | structural lift only |
| `UnaryMinusExpression` | ⬜ | — | structural lift only |
| `UnaryPlusExpression` | ⬜ | — | structural lift only |
| `UnaryPredecrementExpression` | ⬜ | — | structural lift only |
| `UnaryPreincrementExpression` | ⬜ | — | structural lift only |
| `UnaryPropertyExpr` | ⬜ | — | structural lift only |
| `UnarySelectPropertyExpr` | ⬜ | — | structural lift only |
| `UnbasedUnsizedLiteralExpression` | ⬜ | — | structural lift only |
| `UniquenessConstraint` | ⬜ | — | structural lift only |
| `UntilPropertyExpr` | ⬜ | — | structural lift only |
| `UntilWithPropertyExpr` | ⬜ | — | structural lift only |
| `ValueRangeExpression` | ⬜ | — | structural lift only |
| `VariableDimension` | ✅ | — | structural lift only |
| `VariablePattern` | ⬜ | — | structural lift only |
| `VoidType` | ⬜ | — | structural lift only |
| `WildcardDimensionSpecifier` | ⬜ | — | structural lift only |
| `WildcardEqualityExpression` | ⬜ | — | structural lift only |
| `WildcardInequalityExpression` | ⬜ | — | structural lift only |
| `WildcardLiteralExpression` | ⬜ | — | structural lift only |
| `WildcardPattern` | ⬜ | — | structural lift only |
| `WithClause` | ⬜ | — | structural lift only |
| `WithFunctionClause` | ⬜ | — | structural lift only |
| `WithFunctionSample` | ⬜ | — | structural lift only |
| `WithinSequenceExpr` | ⬜ | — | structural lift only |
| `XorAssignmentExpression` | ⬜ | — | structural lift only |

## DIRECTIVE (42 items)
| SyntaxKind | Struct | Semantic | Owner |
|--|--|--|--|
| `BeginKeywordsDirective` | ⬜ | — | preprocessor (no elab) |
| `BinaryConditionalDirectiveExpression` | ⬜ | — | preprocessor (no elab) |
| `CellDefineDirective` | ⬜ | — | preprocessor (no elab) |
| `DefaultDecayTimeDirective` | ⬜ | — | preprocessor (no elab) |
| `DefaultNetTypeDirective` | ⬜ | — | preprocessor (no elab) |
| `DefaultTriregStrengthDirective` | ⬜ | — | preprocessor (no elab) |
| `DefineDirective` | ⬜ | — | preprocessor (no elab) |
| `DelayModeDistributedDirective` | ⬜ | — | preprocessor (no elab) |
| `DelayModePathDirective` | ⬜ | — | preprocessor (no elab) |
| `DelayModeUnitDirective` | ⬜ | — | preprocessor (no elab) |
| `DelayModeZeroDirective` | ⬜ | — | preprocessor (no elab) |
| `ElsIfDirective` | ⬜ | — | preprocessor (no elab) |
| `ElseDirective` | ⬜ | — | preprocessor (no elab) |
| `EndCellDefineDirective` | ⬜ | — | preprocessor (no elab) |
| `EndIfDirective` | ⬜ | — | preprocessor (no elab) |
| `EndKeywordsDirective` | ⬜ | — | preprocessor (no elab) |
| `EndProtectDirective` | ⬜ | — | preprocessor (no elab) |
| `EndProtectedDirective` | ⬜ | — | preprocessor (no elab) |
| `IfDefDirective` | ⬜ | — | preprocessor (no elab) |
| `IfNDefDirective` | ⬜ | — | preprocessor (no elab) |
| `IncludeDirective` | ⬜ | — | preprocessor (no elab) |
| `LineDirective` | ⬜ | — | preprocessor (no elab) |
| `MacroActualArgument` | ⬜ | — | preprocessor (no elab) |
| `MacroArgumentDefault` | ⬜ | — | preprocessor (no elab) |
| `MacroFormalArgument` | ⬜ | — | preprocessor (no elab) |
| `MacroUsage` | ⬜ | — | preprocessor (no elab) |
| `NameValuePragmaExpression` | ⬜ | — | preprocessor (no elab) |
| `NamedConditionalDirectiveExpression` | ⬜ | — | preprocessor (no elab) |
| `NoUnconnectedDriveDirective` | ⬜ | — | preprocessor (no elab) |
| `NumberPragmaExpression` | ⬜ | — | preprocessor (no elab) |
| `ParenPragmaExpression` | ⬜ | — | preprocessor (no elab) |
| `ParenthesizedConditionalDirectiveExpression` | ⬜ | — | preprocessor (no elab) |
| `PragmaDirective` | ⬜ | — | preprocessor (no elab) |
| `ProtectDirective` | ⬜ | — | preprocessor (no elab) |
| `ProtectedDirective` | ⬜ | — | preprocessor (no elab) |
| `ResetAllDirective` | ⬜ | — | preprocessor (no elab) |
| `SimplePragmaExpression` | ⬜ | — | preprocessor (no elab) |
| `TimeScaleDirective` | ⬜ | — | preprocessor (no elab) |
| `UnaryConditionalDirectiveExpression` | ⬜ | — | preprocessor (no elab) |
| `UnconnectedDriveDirective` | ⬜ | — | preprocessor (no elab) |
| `UndefDirective` | ⬜ | — | preprocessor (no elab) |
| `UndefineAllDirective` | ⬜ | — | preprocessor (no elab) |

## OUT-OF-SCOPE (58 items)
| SyntaxKind | Struct | Semantic | Owner |
|--|--|--|--|
| `AnsiUdpPortList` | ⬜ | — | out-of-scope |
| `CellConfigRule` | ⬜ | — | out-of-scope |
| `ChargeStrength` | ⬜ | — | out-of-scope |
| `ColonExpressionClause` | ⬜ | — | out-of-scope |
| `ConditionalPathDeclaration` | ⬜ | — | out-of-scope |
| `ConfigCellIdentifier` | ⬜ | — | out-of-scope |
| `ConfigDeclaration` | ⬜ | — | out-of-scope |
| `ConfigInstanceIdentifier` | ⬜ | — | out-of-scope |
| `ConfigLiblist` | ⬜ | — | out-of-scope |
| `ConfigUseClause` | ⬜ | — | out-of-scope |
| `DefaultConfigRule` | ⬜ | — | out-of-scope |
| `Delay3` | ⬜ | — | out-of-scope |
| `DividerClause` | ⬜ | — | out-of-scope |
| `DriveStrength` | ⬜ | — | out-of-scope |
| `EdgeControlSpecifier` | ⬜ | — | out-of-scope |
| `EdgeDescriptor` | ⬜ | — | out-of-scope |
| `EdgeSensitivePathSuffix` | ⬜ | — | out-of-scope |
| `ElabSystemTask` | ⬜ | — | out-of-scope |
| `IfNonePathDeclaration` | ⬜ | — | out-of-scope |
| `InstanceConfigRule` | ⬜ | — | out-of-scope |
| `LibraryDeclaration` | ⬜ | — | out-of-scope |
| `LibraryIncDirClause` | ⬜ | — | out-of-scope |
| `LibraryIncludeStatement` | ⬜ | — | out-of-scope |
| `LibraryMap` | ⬜ | — | out-of-scope |
| `NonAnsiUdpPortList` | ⬜ | — | out-of-scope |
| `OneStepDelay` | ✅ | — | out-of-scope |
| `PathDeclaration` | ⬜ | — | out-of-scope |
| `PathDescription` | ⬜ | — | out-of-scope |
| `Production` | ⬜ | — | out-of-scope |
| `PullStrength` | ⬜ | — | out-of-scope |
| `PulseStyleDeclaration` | ⬜ | — | out-of-scope |
| `RandCaseItem` | ⬜ | — | out-of-scope |
| `RandCaseStatement` | ⬜ | — | out-of-scope |
| `RandSequenceStatement` | ⬜ | — | out-of-scope |
| `RsCase` | ⬜ | — | out-of-scope |
| `RsCodeBlock` | ⬜ | — | out-of-scope |
| `RsElseClause` | ⬜ | — | out-of-scope |
| `RsIfElse` | ⬜ | — | out-of-scope |
| `RsProdItem` | ⬜ | — | out-of-scope |
| `RsRepeat` | ⬜ | — | out-of-scope |
| `RsRule` | ⬜ | — | out-of-scope |
| `RsWeightClause` | ⬜ | — | out-of-scope |
| `SimplePathSuffix` | ⬜ | — | out-of-scope |
| `SpecifyBlock` | ⬜ | — | out-of-scope |
| `SpecparamDeclaration` | ⬜ | — | out-of-scope |
| `SpecparamDeclarator` | ⬜ | — | out-of-scope |
| `SystemTimingCheck` | ⬜ | — | out-of-scope |
| `TimingCheckEventArg` | ⬜ | — | out-of-scope |
| `TimingCheckEventCondition` | ⬜ | — | out-of-scope |
| `UdpBody` | ⬜ | — | out-of-scope |
| `UdpDeclaration` | ⬜ | — | out-of-scope |
| `UdpEdgeField` | ⬜ | — | out-of-scope |
| `UdpEntry` | ⬜ | — | out-of-scope |
| `UdpInitialStmt` | ⬜ | — | out-of-scope |
| `UdpInputPortDecl` | ⬜ | — | out-of-scope |
| `UdpOutputPortDecl` | ⬜ | — | out-of-scope |
| `UdpSimpleField` | ⬜ | — | out-of-scope |
| `WildcardUdpPortList` | ⬜ | — | out-of-scope |

## How to drive this to 100%
1. Every `PROMOTE` row's Semantic column must be `✅`.
2. Every `Struct` column should be `✅` after expanding the test corpus until every relevant SyntaxKind has been parsed at least once and round-tripped — UDP/SDF/library kinds may legitimately stay `⬜` if we never write source that uses them.
3. `DIRECTIVE` and `OUT-OF-SCOPE` rows are decisions, not gaps.
4. The checklist is correct iff: the union of ✅ + ⏳ + ⬜ in the PROMOTE block accounts for every queryable concept; nothing in CONTAINER/BLOB/DIRECTIVE/OOS deserves a rule.
