"""S18: ClockingDeclaration promotion.

The corpus's ``fifo_asserts.sv`` declares two clocking blocks inside
``module fifo_asserts``:

* ``cb_fifo`` — an ordinary clocking block.
* ``cb_default`` — declared with the leading ``default`` keyword.

S18 promotes each ``ClockingDeclarationSyntax`` graph node to
``role="clocking"`` with path ``fifo_asserts.<name>``, attaches a
``has_clocking`` edge from the parent module, and stamps
``attributes["default"]`` / ``attributes["global"]`` flags based on the
leading keyword token.
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
    from research.ast_experiment.src.lift import lift
    from research.ast_experiment.src.semantic import promote

    graph = lift(tree)
    promote(graph, tree, comp)
    return graph


def _by_role(graph, role):
    return [n for n in graph["nodes"]
            if n.get("semantic", {}).get("role") == role]


def test_s18_clocking_nodes_promoted(bind_graph):
    """Both clocking declarations are promoted with role=clocking and
    hierarchical paths ``<module>.<clocking_name>``."""
    clks = _by_role(bind_graph, "clocking")
    paths = sorted(c["semantic"]["path"] for c in clks)
    assert paths == ["fifo_asserts.cb_default", "fifo_asserts.cb_fifo"], paths


def test_s18_has_clocking_edges(bind_graph):
    """The parent module emits one has_clocking edge per promoted clocking
    node."""
    clks = _by_role(bind_graph, "clocking")
    assert len(clks) == 2
    modules = _by_role(bind_graph, "module")
    parent = next((m for m in modules if m["semantic"]["name"] == "fifo_asserts"), None)
    assert parent is not None, "fifo_asserts module not promoted"
    clk_ids = {c["id"] for c in clks}
    edges = [e for e in bind_graph["edges"]
             if e["type"] == "has_clocking"
             and e["src"] == parent["id"]
             and e["dst"] in clk_ids]
    assert len(edges) == 2, f"expected 2 has_clocking edges, got {len(edges)}"


def test_s18_default_attribute(bind_graph):
    """``default clocking`` form sets attributes.default = True; the plain
    form leaves it False."""
    clks = {c["semantic"]["name"]: c for c in _by_role(bind_graph, "clocking")}
    assert clks["cb_default"]["semantic"]["attributes"]["default"] is True
    assert clks["cb_default"]["semantic"]["attributes"]["global"] is False
    assert clks["cb_fifo"]["semantic"]["attributes"]["default"] is False
    assert clks["cb_fifo"]["semantic"]["attributes"]["global"] is False


def test_s18_name_index_registers_paths(bind_graph):
    """Both hierarchical paths are registered in semantic_name_index so
    downstream rules can resolve clocking blocks by qualified name."""
    idx = bind_graph.get("semantic_name_index", {})
    assert "fifo_asserts.cb_fifo" in idx
    assert "fifo_asserts.cb_default" in idx
