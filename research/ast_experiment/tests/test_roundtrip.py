"""Round-trip test: parse(emit(unlift(lift(parse(fifo.sv))))) ≡ parse(fifo.sv).

Equivalence is checked at the AST class-stream level (a depth-first sequence of
class names with leaf-token text where relevant), modulo trivia (whitespace,
comments). Each construct that round-trips marks its AST class names as
'covered' in covered_classes.json — that file feeds score.py.

This file is the TDD anchor for every iteration: a construct is not 'done'
until its assertion here passes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pyslang
import pytest

HERE = Path(__file__).resolve().parent.parent
SRC = HERE / "fifo.sv"
TOP = HERE / "top.sv"
PKG = HERE / "fifo_pkg.sv"
COVERED = HERE / "covered_classes.json"


def _class_stream(node, out=None):
    if out is None:
        out = []
    out.append(type(node).__name__)
    try:
        for c in node:
            _class_stream(c, out)
    except TypeError:
        pass
    return out


def _mark_covered(classes):
    existing = set(json.loads(COVERED.read_text())) if COVERED.exists() else set()
    existing.update(classes)
    COVERED.write_text(json.dumps(sorted(existing), indent=2))


@pytest.fixture(scope="module")
def original_tree():
    return pyslang.SyntaxTree.fromText(SRC.read_text())


@pytest.fixture(scope="module")
def top_tree():
    return pyslang.SyntaxTree.fromText(TOP.read_text())


def test_parse_baseline(original_tree):
    """Sanity: pyslang can parse fifo.sv with no diagnostics."""
    diags = list(original_tree.diagnostics)
    assert not diags, f"baseline parse has diagnostics: {diags}"


def _roundtrip(tree):
    from scripts.lift import lift  # noqa: I001
    from scripts.unlift import emit

    graph = lift(tree)
    emitted_text = emit(graph)
    reparsed = pyslang.SyntaxTree.fromText(emitted_text)
    return reparsed, emitted_text


def _token_text_stream(node, out=None):
    """Concatenation of every Token rawText (and leading trivia text) reachable
    from `node`, in DFS order. Strong oracle: byte-equal at the token level."""
    if out is None:
        out = []
    if type(node).__name__ == "Token":
        for tr in node.trivia:
            out.append(tr.getRawText())
        out.append(node.rawText)
        return out
    try:
        for c in node:
            _token_text_stream(c, out)
    except TypeError:
        pass
    return out


def _subtrees_of_class(root, class_name):
    """All subtree roots whose Python class is `class_name`, in DFS order."""
    found = []

    def walk(n):
        if type(n).__name__ == class_name:
            found.append(n)
        try:
            for c in n:
                walk(c)
        except TypeError:
            pass

    walk(root)
    return found


def _assert_class_roundtrip(original_root, reparsed_root, class_name):
    """For every subtree rooted at `class_name`, the token-text stream is
    preserved byte-for-byte through the round-trip (positional match)."""
    orig_subs = _subtrees_of_class(original_root, class_name)
    rt_subs = _subtrees_of_class(reparsed_root, class_name)
    assert len(orig_subs) == len(rt_subs), (
        f"{class_name}: subtree count {len(orig_subs)} != {len(rt_subs)}"
    )
    for i, (o, r) in enumerate(zip(orig_subs, rt_subs)):
        os_ = "".join(_token_text_stream(o))
        rs_ = "".join(_token_text_stream(r))
        assert os_ == rs_, (
            f"{class_name}[{i}] token text diverges:\nORIG: {os_!r}\nRT:   {rs_!r}"
        )


def test_module_roundtrip_class_stream(original_tree):
    """ModuleDeclarationSyntax: round-tripped tree has same AST class stream."""
    reparsed, _ = _roundtrip(original_tree)
    orig = _class_stream(original_tree.root)
    rt = _class_stream(reparsed.root)
    assert orig == rt, "AST class streams diverge after round-trip"
    _assert_class_roundtrip(original_tree.root, reparsed.root, "ModuleDeclarationSyntax")
    _mark_covered({"ModuleDeclarationSyntax"})


def test_module_header_and_port_lists(original_tree):
    """iter-002: ModuleHeaderSyntax + ParameterPortListSyntax + AnsiPortListSyntax
    each round-trip with byte-equal token-text streams."""
    reparsed, _ = _roundtrip(original_tree)
    for cls in ("ModuleHeaderSyntax", "ParameterPortListSyntax", "AnsiPortListSyntax"):
        _assert_class_roundtrip(original_tree.root, reparsed.root, cls)
    _mark_covered({"ModuleHeaderSyntax", "ParameterPortListSyntax", "AnsiPortListSyntax"})


def test_port_family(original_tree):
    """iter-003: implicit ANSI port + variable port header round-trip."""
    reparsed, _ = _roundtrip(original_tree)
    for cls in ("ImplicitAnsiPortSyntax", "VariablePortHeaderSyntax"):
        _assert_class_roundtrip(original_tree.root, reparsed.root, cls)
    _mark_covered({"ImplicitAnsiPortSyntax", "VariablePortHeaderSyntax"})


def test_param_decl_family(original_tree):
    """iter-004: parameter decl + integer type + declarator + equals clause."""
    reparsed, _ = _roundtrip(original_tree)
    for cls in (
        "ParameterDeclarationSyntax",
        "IntegerTypeSyntax",
        "DeclaratorSyntax",
        "EqualsValueClauseSyntax",
    ):
        _assert_class_roundtrip(original_tree.root, reparsed.root, cls)
    _mark_covered({
        "ParameterDeclarationSyntax",
        "IntegerTypeSyntax",
        "DeclaratorSyntax",
        "EqualsValueClauseSyntax",
    })


def test_data_decl_family(original_tree):
    """iter-005: data declaration + variable dim + range dim specifier."""
    reparsed, _ = _roundtrip(original_tree)
    for cls in (
        "DataDeclarationSyntax",
        "VariableDimensionSyntax",
        "RangeDimensionSpecifierSyntax",
    ):
        _assert_class_roundtrip(original_tree.root, reparsed.root, cls)
    _mark_covered({
        "DataDeclarationSyntax",
        "VariableDimensionSyntax",
        "RangeDimensionSpecifierSyntax",
    })


def test_continuous_assign(original_tree):
    """iter-006: continuous assign + expression statement round-trip."""
    reparsed, _ = _roundtrip(original_tree)
    for cls in ("ContinuousAssignSyntax", "ExpressionStatementSyntax"):
        _assert_class_roundtrip(original_tree.root, reparsed.root, cls)
    _mark_covered({"ContinuousAssignSyntax", "ExpressionStatementSyntax"})


def test_procedural_and_timing(original_tree):
    """iter-007: procedural block + timing control + event expressions round-trip."""
    reparsed, _ = _roundtrip(original_tree)
    for cls in (
        "ProceduralBlockSyntax",
        "TimingControlStatementSyntax",
        "EventControlWithExpressionSyntax",
        "BinaryEventExpressionSyntax",
        "SignalEventExpressionSyntax",
        "ParenthesizedEventExpressionSyntax",
    ):
        _assert_class_roundtrip(original_tree.root, reparsed.root, cls)
    _mark_covered({
        "ProceduralBlockSyntax",
        "TimingControlStatementSyntax",
        "EventControlWithExpressionSyntax",
        "BinaryEventExpressionSyntax",
        "SignalEventExpressionSyntax",
        "ParenthesizedEventExpressionSyntax",
    })


def test_conditional_family(original_tree):
    """iter-008: block statement + conditional statement + else clause + predicate + pattern."""
    reparsed, _ = _roundtrip(original_tree)
    for cls in (
        "BlockStatementSyntax",
        "ConditionalStatementSyntax",
        "ElseClauseSyntax",
        "ConditionalPredicateSyntax",
        "ConditionalPatternSyntax",
    ):
        _assert_class_roundtrip(original_tree.root, reparsed.root, cls)
    _mark_covered({
        "BlockStatementSyntax",
        "ConditionalStatementSyntax",
        "ElseClauseSyntax",
        "ConditionalPredicateSyntax",
        "ConditionalPatternSyntax",
    })


def test_case_family(original_tree):
    """iter-009: case statement + standard case item + default case item round-trip."""
    reparsed, _ = _roundtrip(original_tree)
    for cls in ("CaseStatementSyntax", "StandardCaseItemSyntax", "DefaultCaseItemSyntax"):
        _assert_class_roundtrip(original_tree.root, reparsed.root, cls)
    _mark_covered({"CaseStatementSyntax", "StandardCaseItemSyntax", "DefaultCaseItemSyntax"})


def test_expression_family(original_tree):
    """iter-010: binary + prefix-unary + parenthesized + concatenation expressions round-trip."""
    reparsed, _ = _roundtrip(original_tree)
    for cls in (
        "BinaryExpressionSyntax",
        "PrefixUnaryExpressionSyntax",
        "ParenthesizedExpressionSyntax",
        "ConcatenationExpressionSyntax",
    ):
        _assert_class_roundtrip(original_tree.root, reparsed.root, cls)
    _mark_covered({
        "BinaryExpressionSyntax",
        "PrefixUnaryExpressionSyntax",
        "ParenthesizedExpressionSyntax",
        "ConcatenationExpressionSyntax",
    })


def test_atom_expressions(original_tree):
    """iter-011: integer vector + literal + identifier name + identifier-select name round-trip."""
    reparsed, _ = _roundtrip(original_tree)
    for cls in (
        "IntegerVectorExpressionSyntax",
        "LiteralExpressionSyntax",
        "IdentifierNameSyntax",
        "IdentifierSelectNameSyntax",
    ):
        _assert_class_roundtrip(original_tree.root, reparsed.root, cls)
    _mark_covered({
        "IntegerVectorExpressionSyntax",
        "LiteralExpressionSyntax",
        "IdentifierNameSyntax",
        "IdentifierSelectNameSyntax",
    })


def test_select_family(original_tree):
    """iter-012: bit select + element select + range select round-trip."""
    reparsed, _ = _roundtrip(original_tree)
    for cls in ("BitSelectSyntax", "ElementSelectSyntax", "RangeSelectSyntax"):
        _assert_class_roundtrip(original_tree.root, reparsed.root, cls)
    _mark_covered({"BitSelectSyntax", "ElementSelectSyntax", "RangeSelectSyntax"})


def test_invocation_family(original_tree):
    """iter-013: system name + invocation expression + argument list + ordered argument round-trip."""
    reparsed, _ = _roundtrip(original_tree)
    for cls in (
        "SystemNameSyntax",
        "InvocationExpressionSyntax",
        "ArgumentListSyntax",
        "OrderedArgumentSyntax",
    ):
        _assert_class_roundtrip(original_tree.root, reparsed.root, cls)
    _mark_covered({
        "SystemNameSyntax",
        "InvocationExpressionSyntax",
        "ArgumentListSyntax",
        "OrderedArgumentSyntax",
    })


def test_property_sequence_and_universal(original_tree):
    """iter-014: simple property + simple sequence + universal SyntaxNode + Token round-trip."""
    reparsed, _ = _roundtrip(original_tree)
    for cls in (
        "SimplePropertyExprSyntax",
        "SimpleSequenceExprSyntax",
        "SyntaxNode",
        "Token",
    ):
        _assert_class_roundtrip(original_tree.root, reparsed.root, cls)
    _mark_covered({
        "SimplePropertyExprSyntax",
        "SimpleSequenceExprSyntax",
        "SyntaxNode",
        "Token",
    })


def test_full_token_text_stream(original_tree):
    """Strongest oracle: every Token's rawText survives the round-trip in DFS
    order (modulo trivia after the final token, which pyslang drops upstream)."""
    reparsed, _ = _roundtrip(original_tree)
    orig = _token_text_stream(original_tree.root)
    rt = _token_text_stream(reparsed.root)
    assert orig == rt, "Token text streams diverge"


def test_top_parse_baseline(top_tree):
    """Sanity: pyslang can parse top.sv with no diagnostics."""
    diags = list(top_tree.diagnostics)
    assert not diags, f"top.sv baseline parse has diagnostics: {diags}"


def test_top_full_token_text_stream(top_tree):
    """Round-trip on top.sv: full token text stream is byte-equal."""
    reparsed, _ = _roundtrip(top_tree)
    orig = _token_text_stream(top_tree.root)
    rt = _token_text_stream(reparsed.root)
    assert orig == rt, "top.sv token text streams diverge"


def test_iter015_hierarchy_instantiation(top_tree):
    """iter-015: HierarchyInstantiationSyntax round-trips byte-equal."""
    reparsed, _ = _roundtrip(top_tree)
    _assert_class_roundtrip(top_tree.root, reparsed.root, "HierarchyInstantiationSyntax")
    _mark_covered({"HierarchyInstantiationSyntax"})


def test_iter016_hierarchical_instance(top_tree):
    """iter-016: HierarchicalInstanceSyntax round-trips byte-equal."""
    reparsed, _ = _roundtrip(top_tree)
    _assert_class_roundtrip(top_tree.root, reparsed.root, "HierarchicalInstanceSyntax")
    _mark_covered({"HierarchicalInstanceSyntax"})


def test_iter017_instance_name(top_tree):
    """iter-017: InstanceNameSyntax round-trips byte-equal."""
    reparsed, _ = _roundtrip(top_tree)
    _assert_class_roundtrip(top_tree.root, reparsed.root, "InstanceNameSyntax")
    _mark_covered({"InstanceNameSyntax"})


def test_iter018_named_port_connection(top_tree):
    """iter-018: NamedPortConnectionSyntax round-trips byte-equal."""
    reparsed, _ = _roundtrip(top_tree)
    _assert_class_roundtrip(top_tree.root, reparsed.root, "NamedPortConnectionSyntax")
    _mark_covered({"NamedPortConnectionSyntax"})


def test_iter019_parameter_value_assignment(top_tree):
    """iter-019: ParameterValueAssignmentSyntax round-trips byte-equal."""
    reparsed, _ = _roundtrip(top_tree)
    _assert_class_roundtrip(top_tree.root, reparsed.root, "ParameterValueAssignmentSyntax")
    _mark_covered({"ParameterValueAssignmentSyntax"})


def test_iter020_named_param_assignment(top_tree):
    """iter-020: NamedParamAssignmentSyntax round-trips byte-equal."""
    reparsed, _ = _roundtrip(top_tree)
    _assert_class_roundtrip(top_tree.root, reparsed.root, "NamedParamAssignmentSyntax")
    _mark_covered({"NamedParamAssignmentSyntax"})


@pytest.fixture(scope="module")
def pkg_tree():
    return pyslang.SyntaxTree.fromText(PKG.read_text())


def test_pkg_parse_baseline(pkg_tree):
    """Sanity: pyslang can parse fifo_pkg.sv with no diagnostics."""
    diags = list(pkg_tree.diagnostics)
    assert not diags, f"fifo_pkg.sv parse has diagnostics: {diags}"


def test_pkg_full_token_text_stream(pkg_tree):
    """Round-trip on fifo_pkg.sv: token text stream is byte-equal."""
    reparsed, _ = _roundtrip(pkg_tree)
    orig = _token_text_stream(pkg_tree.root)
    rt = _token_text_stream(reparsed.root)
    assert orig == rt, "fifo_pkg.sv token streams diverge"


def test_iter021_typedef_declaration(pkg_tree):
    """iter-021: TypedefDeclarationSyntax round-trips byte-equal."""
    reparsed, _ = _roundtrip(pkg_tree)
    _assert_class_roundtrip(pkg_tree.root, reparsed.root, "TypedefDeclarationSyntax")
    _mark_covered({"TypedefDeclarationSyntax"})


def test_iter022_enum_type(pkg_tree):
    """iter-022: EnumTypeSyntax round-trips byte-equal."""
    reparsed, _ = _roundtrip(pkg_tree)
    _assert_class_roundtrip(pkg_tree.root, reparsed.root, "EnumTypeSyntax")
    _mark_covered({"EnumTypeSyntax"})


def test_iter023_parameter_declaration_statement(pkg_tree):
    """iter-023: ParameterDeclarationStatementSyntax round-trips byte-equal."""
    reparsed, _ = _roundtrip(pkg_tree)
    _assert_class_roundtrip(pkg_tree.root, reparsed.root,
                            "ParameterDeclarationStatementSyntax")
    _mark_covered({"ParameterDeclarationStatementSyntax"})


@pytest.fixture(scope="module")
def fifo_tree_post_import():
    """Re-parse fifo.sv now that it has `import fifo_pkg::*` + NamedType usage."""
    return pyslang.SyntaxTree.fromText(SRC.read_text())


def test_iter024_package_import(fifo_tree_post_import):
    """iter-024: PackageImportDeclarationSyntax + PackageImportItemSyntax round-trip."""
    reparsed, _ = _roundtrip(fifo_tree_post_import)
    for cls in ("PackageImportDeclarationSyntax", "PackageImportItemSyntax"):
        _assert_class_roundtrip(fifo_tree_post_import.root, reparsed.root, cls)
    _mark_covered({"PackageImportDeclarationSyntax", "PackageImportItemSyntax"})


def test_iter026_function_declaration(fifo_tree_post_import):
    """iter-026: FunctionDeclarationSyntax + FunctionPrototypeSyntax +
    FunctionPortListSyntax + FunctionPortSyntax round-trip byte-equal."""
    reparsed, _ = _roundtrip(fifo_tree_post_import)
    for cls in (
        "FunctionDeclarationSyntax",
        "FunctionPrototypeSyntax",
        "FunctionPortListSyntax",
        "FunctionPortSyntax",
    ):
        _assert_class_roundtrip(fifo_tree_post_import.root, reparsed.root, cls)
    _mark_covered({
        "FunctionDeclarationSyntax",
        "FunctionPrototypeSyntax",
        "FunctionPortListSyntax",
        "FunctionPortSyntax",
    })


def test_iter025_named_type(fifo_tree_post_import):
    """iter-025: NamedTypeSyntax round-trips byte-equal (fifo_status_e port type)."""
    reparsed, _ = _roundtrip(fifo_tree_post_import)
    _assert_class_roundtrip(fifo_tree_post_import.root, reparsed.root, "NamedTypeSyntax")
    _mark_covered({"NamedTypeSyntax"})
