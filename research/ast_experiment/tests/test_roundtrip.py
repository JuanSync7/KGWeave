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


def test_full_token_text_stream(original_tree):
    """Strongest oracle: every Token's rawText survives the round-trip in DFS
    order (modulo trivia after the final token, which pyslang drops upstream)."""
    reparsed, _ = _roundtrip(original_tree)
    orig = _token_text_stream(original_tree.root)
    rt = _token_text_stream(reparsed.root)
    assert orig == rt, "Token text streams diverge"
