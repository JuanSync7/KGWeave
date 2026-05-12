"""Emit BUCKET_1_CHECKLIST.md — one row per pyslang.SyntaxKind.

For each of pyslang's 536 SyntaxKinds, mark:
  - Class:    PROMOTE | CONTAINER | BLOB | DIRECTIVE | OUT-OF-SCOPE
  - Struct:   ✅ structurally seen in ast_classes.json (round-trip green) / ⬜ untested
  - Semantic: ✅ promoted by an S-rule / ⏳ in flight / — not applicable / ⬜ future
  - Owner:    which S-rule promotes it, or "structural lift only" for BLOB/CONTAINER

Reads `research/ast_experiment/ast_classes.json` (test-corpus coverage) and the
hardcoded promotion map below (kept in sync with semantic.py rules).

Run:  uv run python research/ast_experiment/scripts/build_bucket1_checklist.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pyslang

HERE = Path(__file__).resolve().parent.parent
OUT = HERE / "BUCKET_1_CHECKLIST.md"
COVERED = HERE / "ast_classes.json"

# --- Active S-rule promotion map (keep in sync with semantic.py) ---------------------
PROMOTE_NOW = {
    # S1 — ModuleDeclaration → module + has_port/has_param/has_net
    "ModuleDeclaration": "S1",
    "ImplicitAnsiPort": "S1",
    "VariablePortHeader": "S1",
    "ParameterDeclaration": "S1",
    "Declarator": "S1",
    # S2 — ContinuousAssign → drives/reads
    "ContinuousAssign": "S2",
    # S3 — AlwaysFF → sensitive_to/drives/reads
    "AlwaysFFBlock": "S3",
    # S4 — IdentifierSelectName → reads(base)
    "IdentifierSelectName": "S4",
    "IdentifierName": "S4",  # leaf identifier becomes reads-source
    # S5 — SystemName ($clog2 etc.) → reads(arg)
    "SystemName": "S5",
    "InvocationExpression": "S5",
    # S6 — HierarchyInstantiation → instantiates/of_module/connects
    "HierarchyInstantiation": "S6",
    "HierarchicalInstance": "S6",
    "InstanceName": "S6",
    "NamedPortConnection": "S6",
}

PROMOTE_IN_FLIGHT = {
    # Phase 1
    "ParameterValueAssignment": "S7",
    "NamedParamAssignment": "S7",
    "OrderedParamAssignment": "S7",
    # Phase 2
    "AlwaysCombBlock": "S8",
    # Phase 3
    "PackageDeclaration": "S9a",
    "TypedefDeclaration": "S9b",
    "EnumType": "S9c",
    # Phase 4
    "FunctionDeclaration": "S10",
    "TaskDeclaration": "S10",
    # Phase 5
    "InterfaceDeclaration": "S11a",
    "ModportDeclaration": "S11b",
    "ModportItem": "S11b",
    "ModportNamedPort": "S11b",
    "ModportExplicitPort": "S11b",
    "ModportClockingPort": "S11b",
    "ModportSubroutinePort": "S11b",
    "ModportSimplePortList": "S11b",
    "ModportSubroutinePortList": "S11b",
    # Phase 6
    "LoopGenerate": "S12a",
    "GenerateBlock": "S12b",
    "IfGenerate": "S12c",
    "CaseGenerate": "S12c",
    "GenerateRegion": "S12c",
    # Phase 7 = corpus only, no new rule
}

# --- Classification heuristics --------------------------------------------------------
# Anything explicitly promoted → PROMOTE.
# Anything matching these regexes that ISN'T explicitly promoted → suggested class.
DIRECTIVE_RE = re.compile(
    r"(Directive|MacroUsage|MacroFormalArgument|MacroActualArgument|"
    r"MacroArgumentDefault|PragmaExpression|ConditionalDirectiveExpression)$"
)

OOS_RE = re.compile(
    r"^(Udp|Cell|Config|Library|Specify|Path|Edge|TimingCheck|SystemTiming|"
    r"DelayMode|Specparam|Rs|RandSequence|RandCase|Strength|Charge|Drive|Pull|Pulse|"
    r"ElabSystemTask|SimplePathSuffix|ConditionalPath|IfNonePath|EdgeSensitivePath|"
    r"EdgeControl|EdgeDescriptor|UnconnectedDriveDirective|NoUnconnectedDriveDirective|"
    r"AnsiUdp|NonAnsiUdp|WildcardUdpPortList)"
)

OOS_EXTRA = {
    "ProtectDirective", "EndProtectDirective", "ProtectedDirective",
    "EndProtectedDirective", "DefaultTriregStrengthDirective",
    "DefaultDecayTimeDirective", "Delay3", "DividerClause",
    "ColonExpressionClause", "OneStepDelay",
}

# Expressions, types, literals, operators → BLOB (payload-only by default).
BLOB_RE = re.compile(
    r"(Expression|Literal|Type|Pattern|Clause|Stmt|Suffix|Strength|"
    r"BinsSelectExpr|CoverageBinInitializer|TransRange|TransRepeatRange|TransSet|"
    r"Dimension|Specifier|PropertyExpr|SequenceExpr|SequenceRepetition|"
    r"SequenceMatchList|IntersectClause|DistItem|DistWeight|DistConstraintList|"
    r"ExpressionOrDist|RandJoinClause|SolveBeforeConstraint|ImplicationConstraint|"
    r"UniquenessConstraint|LoopConstraint|DisableConstraint|ConditionalConstraint|"
    r"ExpressionConstraint|ElseConstraintClause|MatchesClause|WithClause|"
    r"WithFunctionClause|EqualsValueClause|EqualsAssertionArgClause|EqualsTypeClause|"
    r"IffEventClause|ColonExpressionClause|DefaultExtendsClauseArg|TypeAssignment|"
    r"PropertySpec|PropertyType|SequenceType|Skew|ClockingSkew|ClockingDirection|"
    r"BlockCoverageEvent|CoverageOption|CoverageIffClause)$"
)

# Containers: lists, blocks, headers, groupings that aren't payload by themselves.
CONTAINER_RE = re.compile(
    r"(List|Block|Header|Item|Region|Scope|CompilationUnit|Member|Argument|"
    r"Connection|Constraint(?!Block|Declaration|Prototype)|TokenList|"
    r"AttributeInstance|AttributeSpec|EmptyMember|NamedLabel|Unknown|"
    r"Untyped|SeparatedList|SyntaxList)$"
)

# Additional explicit PROMOTE candidates not yet wired into an S-rule.
PROMOTE_FUTURE = {
    # Module-level
    "ProgramDeclaration", "ClassDeclaration", "CheckerDeclaration",
    # Ports (non-ANSI / explicit forms)
    "ExplicitAnsiPort", "ImplicitNonAnsiPort", "ExplicitNonAnsiPort",
    "PortDeclaration", "PortReference", "PortConcatenation",
    # Parameter
    "TypeParameterDeclaration", "DefParam", "DefParamAssignment",
    # Net / variable
    "NetDeclaration", "LocalVariableDeclaration", "GenvarDeclaration",
    "UserDefinedNetDeclaration", "NetAlias", "NetTypeDeclaration",
    # Procedural
    "AlwaysBlock", "AlwaysLatchBlock", "InitialBlock", "FinalBlock",
    "ProceduralAssignStatement", "ProceduralDeassignStatement",
    "ProceduralForceStatement", "ProceduralReleaseStatement",
    "BlockingEventTriggerStatement", "NonblockingEventTriggerStatement",
    # SVA
    "PropertyDeclaration", "SequenceDeclaration", "ClockingDeclaration",
    "ClockingItem", "DefaultClockingReference", "DefaultDisableDeclaration",
    "AssertPropertyStatement", "AssumePropertyStatement",
    "CoverPropertyStatement", "CoverSequenceStatement",
    "RestrictPropertyStatement", "ExpectPropertyStatement",
    "ConcurrentAssertionMember", "ImmediateAssertStatement",
    "ImmediateAssumeStatement", "ImmediateCoverStatement",
    "ImmediateAssertionMember", "DeferredAssertion",
    # Class
    "ClassMethodDeclaration", "ClassMethodPrototype", "ClassPropertyDeclaration",
    "ClassSpecifier", "ExtendsClause", "ImplementsClause", "ConstructorName",
    # Constraint
    "ConstraintBlock", "ConstraintDeclaration", "ConstraintPrototype",
    # Coverage
    "CovergroupDeclaration", "Coverpoint", "CoverCross", "CoverageBins",
    # Package import/export
    "PackageImportDeclaration", "PackageImportItem",
    "PackageExportDeclaration", "PackageExportAllDeclaration",
    # Misc
    "BindDirective", "BindTargetList", "LetDeclaration",
    "ForwardTypedefDeclaration", "ForwardTypeRestriction",
    "FunctionPrototype", "FunctionPort", "FunctionPortList",
    "MemberAccessExpression", "VirtualInterfaceType",
    "StructType", "UnionType", "StructUnionMember",
    "OrderedPortConnection",
    "TimeUnitsDeclaration", "CheckerDataDeclaration",
    "CheckerInstantiation", "CheckerInstanceStatement",
    "AssertionItemPort", "AssertionItemPortList",
    "AnonymousProgram", "ExternModuleDecl", "ExternUdpDecl",
    "ExternInterfaceMethod", "PackageHeader", "InterfaceHeader",
    "InterfacePortHeader", "ProgramHeader",
    "ModuleHeader",  # also container; keep as PROMOTE because it carries module identity
}


def classify(kind: str) -> str:
    if kind in PROMOTE_NOW or kind in PROMOTE_IN_FLIGHT or kind in PROMOTE_FUTURE:
        return "PROMOTE"
    if DIRECTIVE_RE.search(kind):
        return "DIRECTIVE"
    if OOS_RE.match(kind) or kind in OOS_EXTRA:
        return "OUT-OF-SCOPE"
    if BLOB_RE.search(kind):
        return "BLOB"
    if CONTAINER_RE.search(kind):
        return "CONTAINER"
    # Fallback heuristics
    if kind.endswith("Declaration") or kind.endswith("Statement"):
        return "CONTAINER"
    if kind.endswith("Name") or kind.endswith("Reference"):
        return "BLOB"
    return "CONTAINER"


def status_marks(kind: str, covered: set[str]) -> tuple[str, str, str]:
    """Return (struct_status, sem_status, owner)."""
    syntax_class = kind + "Syntax"
    struct = "✅" if syntax_class in covered else "⬜"
    if kind in PROMOTE_NOW:
        return struct, "✅", PROMOTE_NOW[kind]
    if kind in PROMOTE_IN_FLIGHT:
        return struct, "⏳", PROMOTE_IN_FLIGHT[kind]
    cls = classify(kind)
    if cls == "PROMOTE":
        return struct, "⬜", "future"
    if cls in {"BLOB", "CONTAINER"}:
        return struct, "—", "structural lift only"
    if cls == "DIRECTIVE":
        return struct, "—", "preprocessor (no elab)"
    return struct, "—", "out-of-scope"


def main() -> int:
    kinds = [k for k in dir(pyslang.SyntaxKind) if not k.startswith("_") and k not in {"name", "value"}]
    kinds.sort()
    covered = set(json.loads(COVERED.read_text())) if COVERED.exists() else set()

    by_class: dict[str, list[tuple[str, str, str, str]]] = {
        "PROMOTE": [], "CONTAINER": [], "BLOB": [], "DIRECTIVE": [], "OUT-OF-SCOPE": [],
    }
    for k in kinds:
        cls = classify(k)
        s, sm, owner = status_marks(k, covered)
        by_class[cls].append((k, s, sm, owner))

    totals = {c: len(v) for c, v in by_class.items()}

    lines: list[str] = []
    lines.append("# Bucket 1 — SV-AST elaboration coverage checklist (per-SyntaxKind)\n")
    lines.append(f"Total `pyslang.SyntaxKind` enum size: **{len(kinds)}**.\n")
    lines.append("Per-row checkboxes — no grouping. Each SyntaxKind has its own status.\n")
    lines.append("\n## Column meanings\n")
    lines.append("| Column | Meaning |\n|--|--|\n")
    lines.append("| **Class** | PROMOTE (queryable node + typed edges), CONTAINER (lifted, traversable, not promoted), BLOB (payload only — operator/literal/type detail), DIRECTIVE (preprocessor — invisible post-elab), OUT-OF-SCOPE (UDP, SDF, library, config, randsequence). |\n")
    lines.append("| **Struct** | ✅ = seen in `ast_classes.json` (test-corpus exercised, round-trip green). ⬜ = NOT yet seen in any test source → structural lift is class-generic so it should work, but is **unverified**. |\n")
    lines.append("| **Semantic** | ✅ = promoted by an active S-rule. ⏳ = in flight in the running expansion loop. ⬜ = PROMOTE candidate with no rule yet. — = not applicable (BLOB/CONTAINER/DIRECTIVE/OOS — no semantic promotion expected). |\n")
    lines.append("| **Owner** | The S-rule that promotes this kind, or `structural lift only` for BLOB/CONTAINER, or the reason for —. |\n")
    lines.append("\n## Roll-up\n")
    lines.append(f"| Class | Count | Struct ✅ | Sem ✅ | Sem ⏳ | Sem ⬜ |\n|--|--|--|--|--|--|\n")
    for cls in ["PROMOTE", "CONTAINER", "BLOB", "DIRECTIVE", "OUT-OF-SCOPE"]:
        rows = by_class[cls]
        ss = sum(1 for r in rows if r[1] == "✅")
        sn = sum(1 for r in rows if r[2] == "✅")
        si = sum(1 for r in rows if r[2] == "⏳")
        su = sum(1 for r in rows if r[2] == "⬜")
        lines.append(f"| {cls} | {len(rows)} | {ss} | {sn} | {si} | {su} |\n")
    lines.append(f"| **Total** | **{len(kinds)}** | **{sum(1 for r in [x for v in by_class.values() for x in v] if r[1] == '✅')}** | | | |\n")

    for cls in ["PROMOTE", "CONTAINER", "BLOB", "DIRECTIVE", "OUT-OF-SCOPE"]:
        lines.append(f"\n## {cls} ({len(by_class[cls])} items)\n")
        lines.append("| SyntaxKind | Struct | Semantic | Owner |\n|--|--|--|--|\n")
        for k, s, sm, owner in sorted(by_class[cls]):
            lines.append(f"| `{k}` | {s} | {sm} | {owner} |\n")

    lines.append("\n## How to drive this to 100%\n")
    lines.append("1. Every `PROMOTE` row's Semantic column must be `✅`.\n")
    lines.append("2. Every `Struct` column should be `✅` after expanding the test corpus until every relevant SyntaxKind has been parsed at least once and round-tripped — UDP/SDF/library kinds may legitimately stay `⬜` if we never write source that uses them.\n")
    lines.append("3. `DIRECTIVE` and `OUT-OF-SCOPE` rows are decisions, not gaps.\n")
    lines.append("4. The checklist is correct iff: the union of ✅ + ⏳ + ⬜ in the PROMOTE block accounts for every queryable concept; nothing in CONTAINER/BLOB/DIRECTIVE/OOS deserves a rule.\n")
    OUT.write_text("".join(lines))
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
    print(f"totals: {totals}  total={sum(totals.values())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
