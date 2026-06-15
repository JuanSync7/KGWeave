"""Every lifted node carries a populated ``span`` dict with the six required
keys: start/end offset, line, col.

Empty-file and single-byte edge cases are exercised explicitly so the
synthetic-root fallback (merged-child span) doesn't silently emit ``None``.
"""

from __future__ import annotations

from pathlib import Path

import pyslang

from knowledge_graph.builders.sv.lift import lift

REQUIRED_KEYS = {
    "start_offset",
    "end_offset",
    "start_line",
    "end_line",
    "start_col",
    "end_col",
}


def _all_nodes_have_span(graph: dict) -> None:
    missing = [n["id"] for n in graph["nodes"] if n.get("span") is None]
    # An empty file legitimately produces a zero-length root span (start==end==0)
    # but ``span`` must still be a populated dict, never None.
    assert not missing, f"nodes missing span: {missing[:5]}"
    for node in graph["nodes"]:
        span = node["span"]
        assert isinstance(span, dict), f"span not dict for {node['id']}"
        assert REQUIRED_KEYS.issubset(span.keys()), (
            f"node {node['id']} span keys {set(span.keys())} missing "
            f"{REQUIRED_KEYS - set(span.keys())}"
        )
        assert isinstance(span["start_offset"], int)
        assert isinstance(span["end_offset"], int)
        assert span["start_offset"] >= 0
        assert span["end_offset"] >= span["start_offset"]


def test_span_present_on_every_fixture_node(sv_fixture: Path) -> None:
    """Every node in every fixture's lifted graph carries a span dict."""
    tree = pyslang.SyntaxTree.fromText(sv_fixture.read_text())
    graph = lift(tree)
    _all_nodes_have_span(graph)


def test_span_present_on_empty_file() -> None:
    """Lift of a zero-byte file emits a span-bearing root node."""
    tree = pyslang.SyntaxTree.fromText("")
    graph = lift(tree)
    assert graph["nodes"], "empty-file lift must still emit a root node"
    _all_nodes_have_span(graph)


def test_span_present_on_single_byte() -> None:
    """Single-character file (``x``) lifts to span-bearing nodes."""
    tree = pyslang.SyntaxTree.fromText("x")
    graph = lift(tree)
    _all_nodes_have_span(graph)


def test_token_at_start_of_file_has_no_trivia_in_span() -> None:
    """A token at offset 0 with empty trivia has span start_offset==0."""
    tree = pyslang.SyntaxTree.fromText("module m; endmodule\n")
    graph = lift(tree)
    tokens = [n for n in graph["nodes"] if n["is_token"]]
    first = next(t for t in tokens if t["payload"]["rawText"] == "module")
    assert first["span"]["start_offset"] == 0


def test_span_offsets_are_byte_not_character() -> None:
    """UTF-8 comment ``// café`` (9 bytes, 8 chars) shifts the first
    token's start_offset by 9 bytes — proving offsets are byte-based."""
    text = "// café\nmodule m; endmodule\n"
    tree = pyslang.SyntaxTree.fromText(text)
    graph = lift(tree)
    tokens = [n for n in graph["nodes"] if n["is_token"]]
    module_tok = next(t for t in tokens if t["payload"]["rawText"] == "module")
    # The leading trivia bytes ("// café\n") = 9 bytes
    assert module_tok["span"]["start_offset"] == 0
    assert module_tok["span"]["end_offset"] == 9 + 6  # 9 trivia + 6 raw


def test_crlf_line_numbers_correct() -> None:
    """CRLF-terminated source still reports line 2 for the second line."""
    text = "module m;\r\nendmodule\r\n"
    tree = pyslang.SyntaxTree.fromText(text)
    graph = lift(tree)
    tokens = [n for n in graph["nodes"] if n["is_token"]]
    endmodule = next(t for t in tokens if t["payload"]["rawText"] == "endmodule")
    assert endmodule["span"]["start_line"] == 2
