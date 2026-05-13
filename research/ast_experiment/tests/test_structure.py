"""Structural invariants for the src/semantic/ package layout.

These tests define the target shape of the migration from the monolithic
`scripts/semantic.py` into `src/semantic/`. They are intentionally written
to FAIL initially (at split-00) and turn green as the migration progresses.

Every test here is structural: it inspects the filesystem and the public
import surface only — it does NOT exercise compilation or query behaviour
(that is covered by test_roundtrip / test_invariants / test_queries*).
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

# The package root is research/ast_experiment/.
_EXPERIMENT_DIR = Path(__file__).resolve().parent.parent
_SRC_DIR = _EXPERIMENT_DIR / "src"
_SEMANTIC_DIR = _SRC_DIR / "semantic"
_SCRIPTS_DIR = _EXPERIMENT_DIR / "scripts"


# Public API exported from research.ast_experiment.src.semantic
_PUBLIC_API = [
    "promote",
    "queryable_nodes",
    "find_drivers",
    "cone_of_influence",
    "port_connections",
    "instances_of",
    "param_overrides",
    "sensitivity_of",
    "width_of",
    "default_value_of",
    "forward_cone",
    "graph_query",
    "find_by_name",
    "neighbors",
    "modports_of",
    "package_of",
]


# The active rule kinds derived from PROMOTE_NOW in build_bucket1_checklist.py.
_ACTIVE_RULE_KINDS = {
    "ModuleDeclaration", "ContinuousAssign", "AlwaysFFBlock", "AlwaysCombBlock",
    "IdentifierSelectName", "IdentifierName", "SystemName", "InvocationExpression",
    "HierarchyInstantiation", "HierarchicalInstance", "InstanceName",
    "NamedPortConnection", "ParameterValueAssignment", "NamedParamAssignment",
    "OrderedParamAssignment", "PackageDeclaration", "TypedefDeclaration",
    "EnumType", "FunctionDeclaration", "TaskDeclaration", "InterfaceDeclaration",
    "ModportDeclaration", "ModportItem", "ModportNamedPort", "LoopGenerate",
    "GenerateBlock", "IfGenerate", "CaseGenerate", "GenerateRegion",
    "BindDirective", "PropertyDeclaration", "SequenceDeclaration",
    "AssertPropertyStatement", "AssumePropertyStatement", "CoverPropertyStatement",
    "CoverSequenceStatement", "RestrictPropertyStatement", "ExpectPropertyStatement",
    "ImmediateAssertStatement", "ImmediateAssumeStatement", "ImmediateCoverStatement",
    "ClockingDeclaration",
    "ProceduralAssignStatement", "ProceduralDeassignStatement",
}


def test_semantic_package_exists():
    """src/semantic/ is importable."""
    mod = importlib.import_module("research.ast_experiment.src.semantic")
    assert mod is not None


def test_public_api_exports():
    """Every name in the public-API list is importable from src.semantic."""
    mod = importlib.import_module("research.ast_experiment.src.semantic")
    missing = [n for n in _PUBLIC_API if not hasattr(mod, n)]
    assert not missing, f"public API missing: {missing}"


def test_dispatch_table_exists():
    """src.semantic.dispatch.RULE_TABLE is a non-empty dict keyed by
    pyslang.SyntaxKind."""
    import pyslang  # noqa: PLC0415
    dispatch = importlib.import_module(
        "research.ast_experiment.src.semantic.dispatch"
    )
    assert hasattr(dispatch, "RULE_TABLE"), "dispatch.RULE_TABLE missing"
    table = dispatch.RULE_TABLE
    assert isinstance(table, dict) and len(table) > 0
    for key in table:
        assert isinstance(key, pyslang.SyntaxKind), (
            f"RULE_TABLE key {key!r} is not a pyslang.SyntaxKind"
        )


def test_no_duplicate_dispatch():
    """Composing RULE_TABLE from all rule modules raises no AssertionError."""
    # The act of importing rules/__init__.py runs the composition assertion.
    importlib.import_module("research.ast_experiment.src.semantic.rules")


def test_active_rule_kinds_present():
    """Every active rule kind appears in RULE_TABLE."""
    dispatch = importlib.import_module(
        "research.ast_experiment.src.semantic.dispatch"
    )
    present = {k.name for k in dispatch.RULE_TABLE}
    missing = _ACTIVE_RULE_KINDS - present
    assert not missing, f"RULE_TABLE missing kinds: {sorted(missing)}"


@pytest.mark.parametrize("name", ["coverage", "classes", "constraints"])
def test_stub_modules_export_empty_rules(name):
    """The four planned-but-not-yet-implemented rule modules each export
    RULES = [] and document their planned kinds in a header comment."""
    mod = importlib.import_module(
        f"research.ast_experiment.src.semantic.rules.{name}"
    )
    assert hasattr(mod, "RULES"), f"rules.{name} missing RULES"
    assert mod.RULES == [], f"rules.{name}.RULES should be empty"


# ---------------------------------------------------------------------------
# split2: 16-file target layout for rules/
# ---------------------------------------------------------------------------

_TARGET_RULES_FILES = [
    "__init__.py",
    "structure.py",
    "instantiation.py",
    "interfaces.py",
    "generate.py",
    "dataflow.py",
    "types.py",
    "behavior.py",
    "procedural.py",
    "clocking.py",
    "properties.py",
    "assertions.py",
    "coverage.py",
    "classes.py",
    "constraints.py",
    "checkers.py",
    "extern.py",
]

_TARGET_ACTIVE_MODULES = [
    "structure", "instantiation", "interfaces", "generate",
    "dataflow", "types", "behavior", "properties", "assertions",
    "clocking", "procedural",
]

_TARGET_STUB_MODULES = [
    "coverage", "classes", "constraints", "checkers", "extern",
]

_STUB_PLANNED_KIND_HINTS = {
    "coverage": ["CovergroupDeclaration", "Coverpoint", "CoverCross"],
    "classes": ["ClassDeclaration"],
    "constraints": ["ConstraintDeclaration", "ConstraintBlock"],
    "checkers": ["CheckerDeclaration", "CheckerInstantiation"],
    "extern": ["ExternModuleDecl", "ProgramDeclaration"],
}


def test_rules_target_layout_files_exist():
    """All 16 named .py files live in src/semantic/rules/."""
    rules_dir = _SEMANTIC_DIR / "rules"
    missing = [f for f in _TARGET_RULES_FILES if not (rules_dir / f).is_file()]
    assert not missing, f"missing target rule files: {missing}"


def test_legacy_hierarchy_module_removed():
    """rules/hierarchy.py is gone after the split."""
    assert not (_SEMANTIC_DIR / "rules" / "hierarchy.py").exists()


def test_legacy_sva_module_removed():
    """rules/sva.py is gone — replaced by properties.py + assertions.py."""
    assert not (_SEMANTIC_DIR / "rules" / "sva.py").exists()


def test_each_active_rule_module_exports_rules():
    """Every active rule module exports a non-empty RULES list."""
    for name in _TARGET_ACTIVE_MODULES:
        mod = importlib.import_module(
            f"research.ast_experiment.src.semantic.rules.{name}"
        )
        assert hasattr(mod, "RULES"), f"rules.{name} missing RULES"
        assert mod.RULES, f"rules.{name}.RULES should be non-empty"


def test_each_stub_module_exports_empty_rules():
    """Every stub rule module exports RULES == []."""
    for name in _TARGET_STUB_MODULES:
        mod = importlib.import_module(
            f"research.ast_experiment.src.semantic.rules.{name}"
        )
        assert hasattr(mod, "RULES"), f"rules.{name} missing RULES"
        assert mod.RULES == [], f"rules.{name}.RULES should be empty"


def test_active_rule_kinds_unchanged():
    """Union of RULES across active modules covers all expected active kinds."""
    union: set[str] = set()
    for name in _TARGET_ACTIVE_MODULES:
        mod = importlib.import_module(
            f"research.ast_experiment.src.semantic.rules.{name}"
        )
        for kind, _fn in mod.RULES:
            union.add(kind.name)
    missing = _ACTIVE_RULE_KINDS - union
    assert not missing, f"active kinds lost in split: {sorted(missing)}"


def test_no_kind_in_multiple_active_modules():
    """Every SyntaxKind is registered by exactly one rule module."""
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    for name in _TARGET_ACTIVE_MODULES:
        mod = importlib.import_module(
            f"research.ast_experiment.src.semantic.rules.{name}"
        )
        for kind, _fn in mod.RULES:
            if kind.name in seen:
                duplicates.append(f"{kind.name}: {seen[kind.name]} & {name}")
            else:
                seen[kind.name] = name
    assert not duplicates, f"double-registered kinds: {duplicates}"


def test_stub_modules_have_planned_kinds_docstring():
    """Every stub's docstring names at least one planned pyslang SyntaxKind."""
    for name, hints in _STUB_PLANNED_KIND_HINTS.items():
        mod = importlib.import_module(
            f"research.ast_experiment.src.semantic.rules.{name}"
        )
        doc = mod.__doc__ or ""
        found = [h for h in hints if h in doc]
        assert found, (
            f"rules.{name} docstring lacks planned kind hint "
            f"from {hints}: {doc!r}"
        )


def test_rule_module_count_is_sixteen():
    """rules/ contains exactly 16 .py files outside __init__.py."""
    rules_dir = _SEMANTIC_DIR / "rules"
    files = [p for p in rules_dir.iterdir()
             if p.is_file() and p.suffix == ".py" and p.name != "__init__.py"]
    assert len(files) == 16, f"expected 16, got {len(files)}: {sorted(p.name for p in files)}"


def test_rules_modules_isolated_from_each_other():
    """No cross-imports between rule submodules; queries do not import rules
    and rules do not import queries."""
    rules_dir = _SEMANTIC_DIR / "rules"
    queries_dir = _SEMANTIC_DIR / "queries"
    rule_files = sorted(p for p in rules_dir.glob("*.py") if p.name != "__init__.py")
    query_files = sorted(p for p in queries_dir.glob("*.py") if p.name != "__init__.py")

    def _imports(path: Path) -> list[str]:
        tree = ast.parse(path.read_text())
        out: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                out.append(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    out.append(alias.name)
        return out

    for rf in rule_files:
        imports = _imports(rf)
        for other in rule_files:
            if other == rf:
                continue
            stem = other.stem
            # Allow imports from .common.* or queries; forbid rules.<other>.
            bad = [
                i for i in imports
                if i.endswith(f"rules.{stem}") or i.endswith(f".{stem}")
                and "rules" in i
            ]
            assert not bad, f"{rf.name} imports peer rule module {stem}: {bad}"
        # Rules must not import queries.
        bad_q = [i for i in imports if ".queries" in i or "src.semantic.queries" in i]
        assert not bad_q, f"{rf.name} imports queries: {bad_q}"

    for qf in query_files:
        imports = _imports(qf)
        bad = [i for i in imports if ".rules" in i or "src.semantic.rules" in i]
        assert not bad, f"{qf.name} imports rules: {bad}"


def test_common_helpers_single_source():
    """Helpers like _resolve / _add_edge / _walk_with_index are defined only
    inside src/semantic/common/."""
    helpers = {"_resolve", "_add_edge", "_walk_with_index", "_lookup_name",
               "_mark", "_has_edge"}
    # The shim scripts/semantic.py (until split-07) may re-export them via
    # `from … import *`; this test only forbids defining them outside common/.
    src_files: list[Path] = []
    for base in (_SEMANTIC_DIR,):
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            if "common" in p.parts:
                continue
            src_files.append(p)
    for f in src_files:
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in helpers:
                pytest.fail(
                    f"helper {node.name} defined outside common/: {f}"
                )


def test_bucket1_checklist_derives_from_registry():
    """build_bucket1_checklist.py's PROMOTE_NOW imports RULE_TABLE (registry
    derivation) — the hand-maintained duplicate is gone."""
    src = (_SCRIPTS_DIR / "build_bucket1_checklist.py").read_text()
    # Either it imports RULE_TABLE OR (less ideal) its keys are a subset of
    # RULE_TABLE.name set. We assert the first: the import line must exist.
    assert "RULE_TABLE" in src, (
        "build_bucket1_checklist.py must import RULE_TABLE from "
        "research.ast_experiment.src.semantic.dispatch"
    )
    # And the legacy "keep in sync with semantic.py" comment must be gone.
    assert "keep in sync with semantic.py" not in src, (
        "registry-derived PROMOTE_NOW should not carry the 'keep in sync' note"
    )


def test_scripts_directory_only_has_entry_points():
    """scripts/ contains only CLI entry points after migration."""
    allowed = {
        "__init__.py",
        "score.py",
        "build_bucket1_checklist.py",
        "render_graph.py",
        "render_kgweave.py",
        "inventory.py",
    }
    actual = {
        p.name for p in _SCRIPTS_DIR.iterdir()
        if p.is_file() and p.suffix == ".py"
    }
    extra = actual - allowed
    assert not extra, f"unexpected files in scripts/: {sorted(extra)}"


def test_no_regex_in_semantic_package():
    """Recursive walk of src/semantic/: zero `import re` or `from re`."""
    if not _SEMANTIC_DIR.exists():
        pytest.fail(f"src/semantic/ does not exist: {_SEMANTIC_DIR}")
    bad: list[str] = []
    for p in _SEMANTIC_DIR.rglob("*.py"):
        tree = ast.parse(p.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "re" or alias.name.startswith("re."):
                        bad.append(f"{p}: import re")
            elif isinstance(node, ast.ImportFrom):
                if node.module == "re":
                    bad.append(f"{p}: from re import …")
    assert not bad, f"regex used in src/semantic/: {bad}"
