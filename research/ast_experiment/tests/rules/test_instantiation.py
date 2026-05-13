"""S33 PrimitiveInstantiation: gate-level primitive promotion tests.

The S6 / S7 / S13 active rules are already exercised end-to-end by the
top.sv-backed test_invariants.py / test_roundtrip.py suites; S33 introduces
its own corpus (``prim_corpus.sv``) so the tests here focus on the new
behaviour:

* gate-type label (and / or / buf / not) stamped per instance
* multi-instance declaration fans out into one node per HierarchicalInstance
* positional port list captured
* optional ``#5`` delay attribute when present, absent otherwise
* ``has_primitive_instance`` containment edge from the enclosing module
* optional ``drives`` edge from the gate to its output net
"""

from __future__ import annotations

from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent.parent
PRIM = HERE / "corpus" / "prim_corpus.sv"


@pytest.fixture(scope="module")
def prim_graph():
    from research.ast_experiment.src.build import build_kg

    graph, _trees, _comp = build_kg([PRIM])
    return graph


def _primitive_nodes(graph):
    return [
        n for n in graph["nodes"]
        if n.get("semantic", {}).get("role") == "primitive_instance"
    ]


def _by_name(nodes, name):
    for n in nodes:
        if n["semantic"]["name"] == name:
            return n
    return None


def test_promotes_four_primitive_instances(prim_graph):
    """g_and / g_or / g_buf / g_not1 / g_not2 are all promoted."""
    prims = _primitive_nodes(prim_graph)
    names = sorted(n["semantic"]["name"] for n in prims)
    assert names == ["g_and", "g_buf", "g_not1", "g_not2", "g_or"]


def test_primitive_type_attribute(prim_graph):
    """Each instance carries the correct gate-type label."""
    prims = _primitive_nodes(prim_graph)
    types = {
        n["semantic"]["name"]: n["semantic"]["attributes"]["primitive"]
        for n in prims
    }
    assert types == {
        "g_and": "and",
        "g_or": "or",
        "g_buf": "buf",
        "g_not1": "not",
        "g_not2": "not",
    }


def test_multi_instance_fanout(prim_graph):
    """``not g_not1(...), g_not2(...);`` promotes BOTH HierarchicalInstance
    children — single PrimitiveInstantiation with two instances."""
    prims = _primitive_nodes(prim_graph)
    nots = [n for n in prims
            if n["semantic"]["attributes"]["primitive"] == "not"]
    assert len(nots) == 2
    paths = sorted(n["semantic"]["path"] for n in nots)
    assert paths == ["prim_demo.g_not1", "prim_demo.g_not2"]


def test_positional_ports_extracted(prim_graph):
    """Each instance's positional port list survives."""
    prims = _primitive_nodes(prim_graph)
    g_and = _by_name(prims, "g_and")
    assert g_and["semantic"]["attributes"]["ports"] == ["out_and", "a", "b"]
    g_not2 = _by_name(prims, "g_not2")
    assert g_not2["semantic"]["attributes"]["ports"] == ["n_b", "b"]


def test_delay_extracted_on_buf(prim_graph):
    """``buf #5 g_buf(...)`` captures the ``#5`` delay; other gates omit
    the ``delay`` key entirely (no surprise empty strings to filter)."""
    prims = _primitive_nodes(prim_graph)
    g_buf = _by_name(prims, "g_buf")
    assert g_buf["semantic"]["attributes"].get("delay") == "#5"
    g_and = _by_name(prims, "g_and")
    assert "delay" not in g_and["semantic"]["attributes"]


def test_has_primitive_instance_edges(prim_graph):
    """The enclosing module emits one ``has_primitive_instance`` edge per
    promoted instance node."""
    prims = _primitive_nodes(prim_graph)
    prim_ids = {n["id"] for n in prims}
    edges = [
        e for e in prim_graph["edges"]
        if e["type"] == "has_primitive_instance" and e["dst"] in prim_ids
    ]
    assert len(edges) == 5
    # All edges originate from the same parent module node.
    sources = {e["src"] for e in edges}
    assert len(sources) == 1
    module_node = next(
        n for n in prim_graph["nodes"]
        if n["id"] in sources and n.get("semantic", {}).get("role") == "module"
    )
    assert module_node["semantic"]["name"] == "prim_demo"


def test_drives_edge_to_output_port(prim_graph):
    """Gate primitives drive their first positional port. ``g_and`` drives
    the module output net ``out_and`` (resolvable via the name index)."""
    prims = _primitive_nodes(prim_graph)
    g_and = _by_name(prims, "g_and")
    out_drives = [
        e for e in prim_graph["edges"]
        if e["src"] == g_and["id"] and e["type"] == "drives"
    ]
    assert len(out_drives) == 1
    # Target node should be the ``out_and`` port (promoted by S1's ANSI-port
    # branch). Verify the name index entry was used.
    target_id = out_drives[0]["dst"]
    target = next(n for n in prim_graph["nodes"] if n["id"] == target_id)
    assert target["semantic"]["name"] == "out_and"


def test_rule_s33_metadata_registered():
    """The new rule is registered in the dispatch table with __rule_id__=S33."""
    import pyslang  # noqa: PLC0415

    from research.ast_experiment.src.semantic.dispatch import RULE_TABLE
    fn = RULE_TABLE.get(pyslang.SyntaxKind.PrimitiveInstantiation)
    assert fn is not None
    assert getattr(fn, "__rule_id__", None) == "S33"


def test_round_trip_primitive_instantiation():
    """PrimitiveInstantiationSyntax round-trips byte-equal through
    lift→emit→reparse, mirroring the round-trip oracle used by S6/S7/S13."""
    import pyslang  # noqa: PLC0415

    from research.ast_experiment.src.lift import lift
    from research.ast_experiment.src.unlift import emit

    src = PRIM.read_text()
    tree = pyslang.SyntaxTree.fromText(src)
    assert not list(tree.diagnostics)
    graph = lift(tree)
    out = emit(graph)
    reparsed = pyslang.SyntaxTree.fromText(out)
    # Compare token text streams (the standard round-trip oracle).
    def _tokens(node, acc):
        if type(node).__name__ == "Token":
            for tr in node.trivia:
                acc.append(tr.getRawText())
            acc.append(node.rawText)
            return
        try:
            for c in node:
                _tokens(c, acc)
        except TypeError:
            pass

    orig: list[str] = []
    rt: list[str] = []
    _tokens(tree.root, orig)
    _tokens(reparsed.root, rt)
    assert orig == rt
