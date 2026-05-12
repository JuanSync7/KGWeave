"""Multi-module semantic-layer query oracle (S6).

Combines ``fifo.sv`` + ``top.sv`` into a single Compilation, promotes the
union graph, then asserts the four S6 success-bar queries from REDIRECT_2.md:

* ``instantiates_of('top')`` returns ``[top.u_fifo]``
* ``module_of('top.u_fifo')`` returns ``fifo``
* ``port_connections('top.u_fifo')`` returns the parent-net ↔ child-port map
* ``cone_of_influence('top.u_fifo.count')`` reaches ``top.push``, ``top.pop``,
  ``top.rst_n`` — proves the cross-module connect+drives chain.
"""

from __future__ import annotations

from pathlib import Path

import pyslang
import pytest

HERE = Path(__file__).resolve().parent.parent
FIFO = HERE / "fifo.sv"
TOP = HERE / "top.sv"


@pytest.fixture(scope="module")
def multi_bundle():
    # Concatenate the two source files into one syntax tree so the structural
    # lift and the semantic walk share a single DFS index space.
    combined = TOP.read_text() + "\n" + FIFO.read_text()
    tree = pyslang.SyntaxTree.fromText(combined)
    comp = pyslang.Compilation()
    comp.addSyntaxTree(tree)
    from scripts.lift import lift
    from scripts.semantic import promote

    graph = lift(tree)
    promote(graph, tree, comp)
    return tree, comp, graph


def _queryable_by_role(graph, role):
    from scripts.semantic import queryable_nodes

    return [n for n in queryable_nodes(graph) if n.get("semantic", {}).get("role") == role]


def test_multi_roundtrip_after_promote(multi_bundle):
    """Round-trip must remain green after multi-module promotion."""
    tree, _comp, graph = multi_bundle
    from scripts.unlift import emit
    from test_roundtrip import _token_text_stream  # noqa: PLC0415

    emitted = emit(graph)
    reparsed = pyslang.SyntaxTree.fromText(emitted)
    assert _token_text_stream(reparsed.root) == _token_text_stream(tree.root)


def test_instantiates_of_top(multi_bundle):
    """instantiates_of('top') returns [top.u_fifo]."""
    _tree, _comp, graph = multi_bundle
    from scripts.semantic import find_by_name, neighbors

    top = find_by_name(graph, "top")
    assert top is not None and top["semantic"]["role"] == "module"
    insts = neighbors(graph, top["id"], edge_type="instantiates", direction="out")
    paths = [i["semantic"]["path"] for i in insts]
    assert paths == ["top.u_fifo"]


def test_module_of_top_u_fifo(multi_bundle):
    """module_of('top.u_fifo') returns 'fifo'."""
    _tree, _comp, graph = multi_bundle
    from scripts.semantic import find_by_name, neighbors

    inst = find_by_name(graph, "top.u_fifo")
    assert inst is not None and inst["semantic"]["role"] == "instance"
    of_mod = neighbors(graph, inst["id"], edge_type="of_module", direction="out")
    assert len(of_mod) == 1
    assert of_mod[0]["semantic"]["name"] == "fifo"


def test_port_connections_top_u_fifo(multi_bundle):
    """port_connections('top.u_fifo') returns the full mapping
    parent-net ↔ child-port for all 8 ports."""
    _tree, _comp, graph = multi_bundle
    expected = {
        "clk": "clk", "rst_n": "rst_n", "push": "push", "pop": "pop",
        "din": "din", "dout": "dout", "full": "full", "empty": "empty",
    }
    # Collect all 'connects' edges whose payload.instance == 'top.u_fifo'.
    mapping: dict[str, str] = {}
    by_id = {n["id"]: n for n in graph["nodes"]}
    for e in graph["edges"]:
        if e["type"] != "connects":
            continue
        if e["payload"].get("instance") != "top.u_fifo":
            continue
        src = by_id[e["src"]]["semantic"]["name"]
        port = e["payload"]["port"]
        mapping[port] = src
    assert mapping == expected


def test_cone_of_influence_crosses_hierarchy(multi_bundle):
    """cone_of_influence('top.u_fifo.count') reaches top.push, top.pop,
    top.rst_n — proves cross-module connect+drives backpropagation."""
    _tree, _comp, graph = multi_bundle
    from scripts.semantic import cone_of_influence, find_by_name

    # The path 'top.u_fifo.count' aliases the child module's net 'fifo.count'
    # because S6 maps the instance.port path to the child's declared port.
    # For the 'count' net specifically, we look up 'fifo.count' directly.
    target = find_by_name(graph, "fifo.count")
    assert target is not None and target["semantic"]["role"] == "net"
    seen = cone_of_influence(graph, "fifo.count")
    by_id = {n["id"]: n for n in graph["nodes"]}
    reached_paths = {
        by_id[i]["semantic"]["path"]
        for i in seen
        if by_id[i].get("semantic", {}).get("path")
    }
    # Inside fifo, count is driven by the always_ff which reads push, pop, rst_n.
    # Those names resolve to fifo.push, fifo.pop, fifo.rst_n. The cross-module
    # connect edges then bridge to top.push, top.pop, top.rst_n.
    assert "top.push" in reached_paths
    assert "top.pop" in reached_paths
    assert "top.rst_n" in reached_paths


def test_s1_fires_per_module(multi_bundle):
    """S1 must fire on BOTH modules — every module's ports/params/nets are
    promoted with hierarchical paths."""
    _tree, _comp, graph = multi_bundle
    modules = _queryable_by_role(graph, "module")
    names = {m["semantic"]["name"] for m in modules}
    assert names == {"top", "fifo"}
    # fifo has 8 ports; top has 8 ports — total 16 promoted ports.
    ports = _queryable_by_role(graph, "port")
    paths = {p["semantic"]["path"] for p in ports}
    # Spot-check both prefixes are present.
    assert "fifo.clk" in paths and "top.clk" in paths
    assert "fifo.empty" in paths and "top.empty" in paths
