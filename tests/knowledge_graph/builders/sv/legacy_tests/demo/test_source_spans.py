"""Characterise pyslang's source-span API for the GH-Pages demo.

These are *probe tests* — they document the API SA2 will use to attach
``span = {file, start_offset, end_offset, start_line, end_line}`` to every
graph node when exporting ``demo/data/graph.json``. They are deliberately
narrow: they pin the API surface (``node.sourceRange.start.offset`` /
``token.location.offset`` + ``len(token.rawText)``) so a future pyslang
upgrade that renames either path trips a red bar immediately.

If these tests pass, SA2 can rely on the documented API. If they fail, SA2
must update the export shim and re-baseline these tests.
"""

from __future__ import annotations

from pathlib import Path

import pyslang
import pytest

CORPUS = Path(__file__).resolve().parents[2] / "corpus"


def _walk(node):
    yield node
    try:
        for c in node:
            if c is None:
                continue
            yield from _walk(c)
    except TypeError:
        return


def _first_of(root, kind_name: str):
    for n in _walk(root):
        if type(n).__name__ == "Token":
            continue
        k = str(getattr(n, "kind", "")).split(".")[-1]
        if k == kind_name:
            return n
    return None


def test_syntax_node_exposes_source_range() -> None:
    """Every non-Token SyntaxNode exposes ``.sourceRange`` with ``start.offset`` and ``end.offset``."""
    tree = pyslang.SyntaxTree.fromText("module m; endmodule\n")
    sr = tree.root.sourceRange
    assert hasattr(sr, "start") and hasattr(sr, "end")
    assert isinstance(sr.start.offset, int)
    assert isinstance(sr.end.offset, int)
    assert sr.start.offset == 0
    # end.offset is exclusive (points one past the last byte)
    assert sr.end.offset == len("module m; endmodule")


def test_token_exposes_location_offset_and_rawtext_length() -> None:
    """Tokens have ``.location.offset`` (start) and ``len(rawText)`` gives the span width."""
    tree = pyslang.SyntaxTree.fromText("module m; endmodule\n")
    tok = tree.root.getFirstToken()
    assert tok.location.offset == 0
    assert tok.rawText == "module"
    # No ``sourceRange`` on Token — only ``location`` + ``rawText``.
    assert getattr(tok, "sourceRange", None) is None


def test_source_manager_maps_offset_to_line_column() -> None:
    """``tree.sourceManager.getLineNumber(loc)`` / ``getColumnNumber(loc)`` are stable."""
    src = "module m;\n  wire w;\nendmodule\n"
    tree = pyslang.SyntaxTree.fromText(src)
    sm = tree.sourceManager
    # First token "module" -> line 1
    tok = tree.root.getFirstToken()
    assert sm.getLineNumber(tok.location) == 1
    assert sm.getColumnNumber(tok.location) == 1
    # End of root -> line 3 (after "endmodule")
    end = tree.root.sourceRange.end
    assert sm.getLineNumber(end) == 3


@pytest.mark.parametrize(
    "kind_name,corpus_file",
    [
        ("ConcurrentAssertionMember", "fifo_asserts.sv"),
        ("HierarchicalInstance",      "fifo_asserts.sv"),
        ("Declarator",                "fifo_asserts.sv"),
        ("ExternModuleDecl",          "extern_corpus.sv"),
        ("ClockingDeclaration",       "fifo_asserts.sv"),
    ],
)
def test_wave5_kinds_expose_source_range(kind_name: str, corpus_file: str) -> None:
    """Each S-rule output kind we plan to attach spans to has a usable .sourceRange."""
    txt = (CORPUS / corpus_file).read_text()
    tree = pyslang.SyntaxTree.fromText(txt)
    n = _first_of(tree.root, kind_name)
    assert n is not None, f"{kind_name} not found in {corpus_file}"
    sr = n.sourceRange
    assert sr.start.offset < sr.end.offset
    # Slice the actual source to confirm the range is a substring of the file.
    snippet = txt[sr.start.offset:sr.end.offset]
    assert snippet, f"empty span for {kind_name}"
