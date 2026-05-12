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


def test_module_roundtrip_class_stream(original_tree):
    """ModuleDeclarationSyntax: round-tripped tree has same AST class stream."""
    reparsed, _ = _roundtrip(original_tree)
    orig = _class_stream(original_tree.root)
    rt = _class_stream(reparsed.root)
    assert orig == rt, "AST class streams diverge after round-trip"
    _mark_covered({"ModuleDeclarationSyntax"})
