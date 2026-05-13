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
BIND = HERE / "fifo_asserts.sv"


@pytest.fixture(scope="module")
def bind_graph():
    text = BIND.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    comp = pyslang.Compilation()
    comp.addSyntaxTree(tree)
    from research.ast_experiment.src.lift import lift
    from research.ast_experiment.src.semantic import promote

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
