"""S22: CovergroupDeclaration promotion.

The corpus's ``fifo_asserts.sv`` declares two covergroups inside
``module fifo_asserts``:

* ``cg_fifo`` — has an ``@(posedge clk)`` clocking event clause.
* ``cg_simple`` — has no clocking event clause.

S22 promotes each ``CovergroupDeclarationSyntax`` graph node to
``role="covergroup"`` with path ``fifo_asserts.<name>``, attaches a
``has_covergroup`` edge from the parent module, and stamps
``attributes["clocking_event"]`` based on the presence of an
``EventControl*`` direct child.

Coverpoint and CoverCross sub-elements remain BLOB at this S-rule and
will be promoted by S23.
"""

from __future__ import annotations

from pathlib import Path

import pyslang
import pytest

HERE = Path(__file__).resolve().parent.parent.parent
BIND = HERE / "corpus" / "fifo_asserts.sv"


@pytest.fixture(scope="module")
def bind_graph():
    text = BIND.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    comp = pyslang.Compilation()
    comp.addSyntaxTree(tree)
    from knowledge_graph.builders.sv.lift import lift
    from knowledge_graph.builders.sv.semantic import promote

    graph = lift(tree)
    promote(graph, tree, comp)
    return graph


def _by_role(graph, role):
    return [n for n in graph["nodes"]
            if n.get("semantic", {}).get("role") == role]


def test_s22_covergroup_nodes_promoted(bind_graph):
    """Both covergroup declarations are promoted with role=covergroup and
    hierarchical paths ``<module>.<covergroup_name>``."""
    cgs = _by_role(bind_graph, "covergroup")
    paths = sorted(c["semantic"]["path"] for c in cgs)
    assert paths == ["fifo_asserts.cg_fifo", "fifo_asserts.cg_simple"], paths


def test_s22_has_covergroup_edges(bind_graph):
    """The parent module emits one has_covergroup edge per promoted
    covergroup node."""
    cgs = _by_role(bind_graph, "covergroup")
    assert len(cgs) == 2
    modules = _by_role(bind_graph, "module")
    parent = next((m for m in modules if m["semantic"]["name"] == "fifo_asserts"), None)
    assert parent is not None, "fifo_asserts module not promoted"
    cg_ids = {c["id"] for c in cgs}
    edges = [e for e in bind_graph["edges"]
             if e["type"] == "has_covergroup"
             and e["src"] == parent["id"]
             and e["dst"] in cg_ids]
    assert len(edges) == 2, f"expected 2 has_covergroup edges, got {len(edges)}"


def test_s22_clocking_event_attribute(bind_graph):
    """``cg_fifo`` carries a clocking event clause and thus
    attributes.clocking_event == True; ``cg_simple`` has none and is False."""
    cgs = {c["semantic"]["name"]: c for c in _by_role(bind_graph, "covergroup")}
    assert cgs["cg_fifo"]["semantic"]["attributes"]["clocking_event"] is True
    assert cgs["cg_simple"]["semantic"]["attributes"]["clocking_event"] is False


def test_s22_name_index_registers_paths(bind_graph):
    """Both hierarchical paths are registered in semantic_name_index so
    downstream rules can resolve covergroups by qualified name."""
    idx = bind_graph.get("semantic_name_index", {})
    assert "fifo_asserts.cg_fifo" in idx
    assert "fifo_asserts.cg_simple" in idx


# ---------------------------------------------------------------------------
# S23 — Coverpoint + CoverCross
# ---------------------------------------------------------------------------


def test_s23_coverpoint_nodes_promoted(bind_graph):
    """Every ``[label:] coverpoint <expr> ...;`` item is promoted with role
    ``coverpoint`` and a path of the form ``<module>.<covergroup>.<cp>``."""
    cps = _by_role(bind_graph, "coverpoint")
    paths = sorted(c["semantic"]["path"] for c in cps)
    assert paths == [
        "fifo_asserts.cg_fifo.cp_full",
        "fifo_asserts.cg_fifo.cp_push",
        "fifo_asserts.cg_fifo.cp_push_full",
        "fifo_asserts.cg_simple.cp_full",
    ], paths


def test_s23_cross_nodes_promoted(bind_graph):
    """Every ``[label:] cross <cp>, <cp> ...;`` item is promoted with role
    ``cross`` and a path of the form ``<module>.<covergroup>.<cross>``."""
    crosses = _by_role(bind_graph, "cross")
    paths = sorted(c["semantic"]["path"] for c in crosses)
    assert paths == ["fifo_asserts.cg_fifo.cx_push_full"], paths


def test_s23_has_coverpoint_edges(bind_graph):
    """The parent covergroup emits one has_coverpoint edge per promoted
    coverpoint node — never the module."""
    cps = _by_role(bind_graph, "coverpoint")
    cgs = {c["semantic"]["path"]: c for c in _by_role(bind_graph, "covergroup")}
    cp_ids = {c["id"] for c in cps}
    edges = [e for e in bind_graph["edges"]
             if e["type"] == "has_coverpoint" and e["dst"] in cp_ids]
    assert len(edges) == len(cps), (
        f"expected one has_coverpoint edge per coverpoint; got {len(edges)}/{len(cps)}"
    )
    parent_ids = {cgs[p]["id"] for p in cgs}
    bad = [e for e in edges if e["src"] not in parent_ids]
    assert not bad, f"has_coverpoint with non-covergroup parent: {bad}"


def test_s23_has_cross_edges(bind_graph):
    """The parent covergroup emits one has_cross edge per promoted cross
    node — never the module."""
    crosses = _by_role(bind_graph, "cross")
    cgs = {c["semantic"]["path"]: c for c in _by_role(bind_graph, "covergroup")}
    cx_ids = {c["id"] for c in crosses}
    edges = [e for e in bind_graph["edges"]
             if e["type"] == "has_cross" and e["dst"] in cx_ids]
    assert len(edges) == 1
    parent_ids = {cgs[p]["id"] for p in cgs}
    assert edges[0]["src"] in parent_ids


def test_s23_coverpoint_simple_expr_text(bind_graph):
    """A coverpoint whose expression is a single bare identifier carries
    ``attributes.expr_text`` with that identifier; richer expressions carry
    ``attributes.expr_blob = True`` and no ``expr_text``."""
    cps = {c["semantic"]["path"]: c for c in _by_role(bind_graph, "coverpoint")}
    full = cps["fifo_asserts.cg_fifo.cp_full"]["semantic"]["attributes"]
    assert full.get("expr_text") == "full"
    assert "expr_blob" not in full
    push = cps["fifo_asserts.cg_fifo.cp_push"]["semantic"]["attributes"]
    assert push.get("expr_text") == "push"
    concat = cps["fifo_asserts.cg_fifo.cp_push_full"]["semantic"]["attributes"]
    assert concat.get("expr_blob") is True
    assert "expr_text" not in concat


def test_s23_cross_members_extracted(bind_graph):
    """A cross node's ``attributes.members`` lists the coverpoint names it
    references, in source order."""
    crosses = {c["semantic"]["path"]: c for c in _by_role(bind_graph, "cross")}
    cx = crosses["fifo_asserts.cg_fifo.cx_push_full"]
    assert cx["semantic"]["attributes"]["members"] == ["cp_push", "cp_full"]


def test_s23_coverpoint_name_index_registers_paths(bind_graph):
    """Coverpoint and cross hierarchical paths are registered in the shared
    name index so downstream rules can resolve them by qualified name."""
    idx = bind_graph.get("semantic_name_index", {})
    assert "fifo_asserts.cg_fifo.cp_full" in idx
    assert "fifo_asserts.cg_fifo.cp_push" in idx
    assert "fifo_asserts.cg_fifo.cp_push_full" in idx
    assert "fifo_asserts.cg_simple.cp_full" in idx
    assert "fifo_asserts.cg_fifo.cx_push_full" in idx


def test_s23_synthetic_coverpoint_name_fallback():
    """An anonymous coverpoint (no ``label:``) gets a synthetic name
    ``coverpoint_<n>`` scoped to its enclosing covergroup."""
    src = """
    module m;
      covergroup cg @(posedge clk);
        coverpoint a;
        coverpoint b;
      endgroup
    endmodule
    """
    import pyslang  # noqa: PLC0415
    from knowledge_graph.builders.sv.lift import lift  # noqa: PLC0415
    from knowledge_graph.builders.sv.semantic import promote  # noqa: PLC0415

    tree = pyslang.SyntaxTree.fromText(src)
    comp = pyslang.Compilation()
    comp.addSyntaxTree(tree)
    graph = lift(tree)
    promote(graph, tree, comp)
    cps = [n for n in graph["nodes"]
           if n.get("semantic", {}).get("role") == "coverpoint"]
    names = sorted(c["semantic"]["name"] for c in cps)
    assert names == ["coverpoint_0", "coverpoint_1"], names


# ---------------------------------------------------------------------------
# S41 — CoverageBins
# ---------------------------------------------------------------------------


def test_s41_coverage_bins_nodes_promoted(bind_graph):
    """Each ``bins``/``illegal_bins``/``ignore_bins`` declaration inside
    ``cp_push`` is promoted with role ``coverage_bins`` and a three-level
    hierarchical path ``<module>.<covergroup>.<coverpoint>.<bins_name>``."""
    bins_nodes = _by_role(bind_graph, "coverage_bins")
    paths = sorted(b["semantic"]["path"] for b in bins_nodes)
    assert paths == [
        "fifo_asserts.cg_fifo.cp_push.bad",
        "fifo_asserts.cg_fifo.cp_push.high",
        "fifo_asserts.cg_fifo.cp_push.low",
    ], paths


def test_s41_bins_kind_attribute(bind_graph):
    """Each bins node carries ``attributes.bins_kind`` discriminating
    ``bins``, ``illegal_bins``, and ``ignore_bins``."""
    bins_nodes = {b["semantic"]["name"]: b for b in _by_role(bind_graph, "coverage_bins")}
    assert bins_nodes["low"]["semantic"]["attributes"]["bins_kind"] == "bins"
    assert bins_nodes["high"]["semantic"]["attributes"]["bins_kind"] == "bins"
    assert bins_nodes["bad"]["semantic"]["attributes"]["bins_kind"] == "illegal_bins"


def test_s41_has_bins_edges(bind_graph):
    """The parent coverpoint emits one ``has_bins`` edge per promoted bins
    node — never the covergroup or module."""
    bins_nodes = _by_role(bind_graph, "coverage_bins")
    cps = {c["semantic"]["path"]: c for c in _by_role(bind_graph, "coverpoint")}
    bins_ids = {b["id"] for b in bins_nodes}
    edges = [e for e in bind_graph["edges"]
             if e["type"] == "has_bins" and e["dst"] in bins_ids]
    assert len(edges) == len(bins_nodes), (
        f"expected {len(bins_nodes)} has_bins edges, got {len(edges)}"
    )
    parent_cp = cps["fifo_asserts.cg_fifo.cp_push"]
    assert all(e["src"] == parent_cp["id"] for e in edges), (
        "has_bins edge sourced from wrong parent"
    )


def test_s41_array_form_attribute(bind_graph):
    """Bins declared as ``bins name[]`` carry ``attributes.array_form = True``;
    plain ``bins name`` do not."""
    bins_nodes = {b["semantic"]["name"]: b for b in _by_role(bind_graph, "coverage_bins")}
    assert bins_nodes["high"]["semantic"]["attributes"].get("array_form") is True
    assert "array_form" not in bins_nodes["low"]["semantic"]["attributes"]
    assert "array_form" not in bins_nodes["bad"]["semantic"]["attributes"]


def test_s41_roundtrip(bind_graph):
    """Bins promotion must not alter the lossless round-trip property: every
    corpus file lifts and emits to byte-equal source."""
    from knowledge_graph.builders.sv.unlift import emit  # noqa: PLC0415

    text = BIND.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    comp = pyslang.Compilation()
    comp.addSyntaxTree(tree)
    from knowledge_graph.builders.sv.lift import lift  # noqa: PLC0415
    from knowledge_graph.builders.sv.semantic import promote  # noqa: PLC0415

    graph = lift(tree)
    promote(graph, tree, comp)
    reconstructed = emit(graph)
    assert reconstructed == text, "round-trip broke after S41"
