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
    from knowledge_graph.builders.sv.lift import lift
    from knowledge_graph.builders.sv.semantic import promote

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


# ---------------------------------------------------------------------------
# S40 — DefaultClockingReference tests
# ---------------------------------------------------------------------------


def test_s40_default_clocking_edge_exists(bind_graph):
    """``default clocking cb_fifo;`` emits a ``default_clocking`` edge from
    the enclosing module (fifo_asserts) to the clocking block node for
    cb_fifo."""
    modules = [n for n in bind_graph["nodes"]
               if n.get("semantic", {}).get("role") == "module"]
    parent = next(
        (m for m in modules if m["semantic"]["name"] == "fifo_asserts"), None
    )
    assert parent is not None, "fifo_asserts module not promoted"

    idx = bind_graph.get("semantic_name_index", {})
    clk_gid = idx.get("fifo_asserts.cb_fifo")
    assert clk_gid is not None, "cb_fifo not in name_index"

    edges = [
        e for e in bind_graph["edges"]
        if e["type"] == "default_clocking"
        and e["src"] == parent["id"]
        and e["dst"] == clk_gid
    ]
    assert len(edges) == 1, (
        f"expected 1 default_clocking edge from fifo_asserts to cb_fifo, "
        f"got {len(edges)}"
    )


def test_s40_default_clocking_edge_payload(bind_graph):
    """The ``default_clocking`` edge carries ``name`` metadata equal to the
    referenced clocking block name."""
    idx = bind_graph.get("semantic_name_index", {})
    clk_gid = idx.get("fifo_asserts.cb_fifo")
    assert clk_gid is not None

    modules = [n for n in bind_graph["nodes"]
               if n.get("semantic", {}).get("role") == "module"]
    parent = next(
        (m for m in modules if m["semantic"]["name"] == "fifo_asserts"), None
    )
    assert parent is not None

    edges = [
        e for e in bind_graph["edges"]
        if e["type"] == "default_clocking"
        and e["src"] == parent["id"]
        and e["dst"] == clk_gid
    ]
    assert len(edges) == 1
    assert edges[0].get("payload", {}).get("name") == "cb_fifo"


# ---------------------------------------------------------------------------
# S59 — ClockingItem / DefaultSkewItem tests
# ---------------------------------------------------------------------------


def test_s59_clocking_item_fanout(bind_graph):
    """Each identifier in a ClockingItem direction-list fans out to its own
    role=clocking_item node. ``input full, push;`` produces two nodes; the
    ``output #1 rst_n;`` item produces one — three direction-items total
    in cb_fifo."""
    items = [n for n in bind_graph["nodes"]
             if n.get("semantic", {}).get("role") == "clocking_item"]
    paths = sorted(i["semantic"]["path"] for i in items)
    assert "fifo_asserts.cb_fifo.full" in paths
    assert "fifo_asserts.cb_fifo.push" in paths
    assert "fifo_asserts.cb_fifo.rst_n" in paths


def test_s59_clocking_item_direction_attr(bind_graph):
    """ClockingItem nodes carry attributes.direction = input/output/inout
    derived structurally from the leading ClockingDirection token kind."""
    items = {n["semantic"]["path"]: n for n in bind_graph["nodes"]
             if n.get("semantic", {}).get("role") == "clocking_item"}
    assert items["fifo_asserts.cb_fifo.full"]["semantic"]["attributes"]["direction"] == "input"
    assert items["fifo_asserts.cb_fifo.push"]["semantic"]["attributes"]["direction"] == "input"
    assert items["fifo_asserts.cb_fifo.rst_n"]["semantic"]["attributes"]["direction"] == "output"


def test_s59_clocking_item_skew_attr(bind_graph):
    """The ``output #1 rst_n;`` item carries attributes.skew == "# 1"
    (whitespace-joined token text). The bare ``input full, push;`` items
    carry attributes.skew == None."""
    items = {n["semantic"]["path"]: n for n in bind_graph["nodes"]
             if n.get("semantic", {}).get("role") == "clocking_item"}
    assert items["fifo_asserts.cb_fifo.full"]["semantic"]["attributes"]["skew"] is None
    assert items["fifo_asserts.cb_fifo.rst_n"]["semantic"]["attributes"]["skew"] == "# 1"


def test_s59_has_clocking_item_edges(bind_graph):
    """Each ClockingItem (per identifier) gets a has_clocking_item edge from
    its enclosing ClockingDeclaration node."""
    idx = bind_graph.get("semantic_name_index", {})
    clk_gid = idx["fifo_asserts.cb_fifo"]
    items = [n for n in bind_graph["nodes"]
             if n.get("semantic", {}).get("role") == "clocking_item"
             and n["semantic"]["path"].startswith("fifo_asserts.cb_fifo.")]
    item_ids = {i["id"] for i in items}
    edges = [e for e in bind_graph["edges"]
             if e["type"] == "has_clocking_item"
             and e["src"] == clk_gid
             and e["dst"] in item_ids]
    assert len(edges) == len(items) == 3, (
        f"expected 3 has_clocking_item edges from cb_fifo, got {len(edges)} "
        f"(items={len(items)})"
    )


def test_s59_default_skew_item(bind_graph):
    """The ``default input #1step output #2;`` row in cb_default promotes
    to a single role=clocking_item node with direction="default" and
    both input_skew + output_skew attributes set."""
    items = [n for n in bind_graph["nodes"]
             if n.get("semantic", {}).get("role") == "clocking_item"
             and n["semantic"]["path"] == "fifo_asserts.cb_default.__default__"]
    assert len(items) == 1, (
        f"expected exactly one default-skew clocking_item node, got {len(items)}"
    )
    attrs = items[0]["semantic"]["attributes"]
    assert attrs["direction"] == "default"
    assert attrs["input_skew"] == "# 1step"
    assert attrs["output_skew"] == "# 2"
    # And it must have a has_clocking_item edge from cb_default.
    idx = bind_graph.get("semantic_name_index", {})
    clk_gid = idx["fifo_asserts.cb_default"]
    edges = [e for e in bind_graph["edges"]
             if e["type"] == "has_clocking_item"
             and e["src"] == clk_gid
             and e["dst"] == items[0]["id"]]
    assert len(edges) == 1


def test_s59_name_index_registers_items(bind_graph):
    """All clocking_item paths are registered in semantic_name_index for
    downstream qualified-name resolution."""
    idx = bind_graph.get("semantic_name_index", {})
    assert "fifo_asserts.cb_fifo.full" in idx
    assert "fifo_asserts.cb_fifo.push" in idx
    assert "fifo_asserts.cb_fifo.rst_n" in idx
    assert "fifo_asserts.cb_default.__default__" in idx


def test_s40_roundtrip(bind_graph):
    """Byte-equal round-trip: emit(lift(corpus)) must reconstruct the source
    exactly — the default_clocking edge must not mutate any node structure."""
    from pathlib import Path
    from knowledge_graph.builders.sv.lift import lift
    from knowledge_graph.builders.sv.unlift import emit
    import pyslang

    corpus = Path(__file__).resolve().parent.parent.parent / "corpus" / "fifo_asserts.sv"
    text = corpus.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    graph = lift(tree)
    reconstructed = emit(graph)
    assert reconstructed == text, (
        f"round-trip mismatch: got {len(reconstructed)} bytes, "
        f"expected {len(text)} bytes"
    )
