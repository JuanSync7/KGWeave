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
    # Production multi-file path: each SV file is its own SyntaxTree, lifted
    # and promoted into one shared graph. The pre-build_kg fixture used a
    # string-concat hack that bypassed the real multi-file code path and
    # masked the cross-tree merge bug.
    from scripts.build import build_kg

    graph, trees, comp = build_kg([TOP, FIFO])
    # Pick the first tree as the "round-trip representative" — round-trip
    # tests still exercise the per-tree lift+emit invariant.
    return trees[0], comp, graph


def _queryable_by_role(graph, role):
    from scripts.semantic import queryable_nodes

    return [n for n in queryable_nodes(graph) if n.get("semantic", {}).get("role") == role]


def test_multi_roundtrip_after_promote(multi_bundle):
    """Round-trip on the first promoted tree must remain green.

    ``emit(graph)`` walks ``graph['order'][0]`` — the first tree's root — so
    the byte-equal check applies to that tree only. The build_kg multi-file
    path stores per-tree roots in ``graph['order']`` so individual files can
    still be re-emitted independently."""
    tree, _comp, graph = multi_bundle
    from scripts.unlift import unlift, emit  # noqa: PLC0415
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


def test_tool_instances_of(multi_bundle):
    """instances_of('fifo') returns every instance path typed as `fifo`."""
    _tree, _comp, graph = multi_bundle
    from scripts.semantic import instances_of

    assert instances_of(graph, "fifo") == ["top.u_fifo"]
    assert instances_of(graph, "nonexistent") == []


def test_tool_port_connections(multi_bundle):
    """port_connections('top.u_fifo') returns the 8 named-connection entries."""
    _tree, _comp, graph = multi_bundle
    from scripts.semantic import port_connections

    pcs = port_connections(graph, "top.u_fifo")
    by_port = {pc["port"]: pc["src_path"] for pc in pcs}
    assert by_port == {
        "clk": "top.clk", "rst_n": "top.rst_n", "push": "top.push",
        "pop": "top.pop", "din": "top.din", "dout": "top.dout",
        "full": "top.full", "empty": "top.empty",
    }


def test_tool_sensitivity_of(multi_bundle):
    """sensitivity_of(<always_ff>) returns clk(posedge) + rst_n(negedge)."""
    _tree, _comp, graph = multi_bundle
    from scripts.semantic import queryable_nodes, sensitivity_of

    aff = next(n for n in queryable_nodes(graph)
               if n.get("semantic", {}).get("role") == "always_ff")
    s = sensitivity_of(graph, aff["id"])
    by_sig = {x["signal"]: x["edge"] for x in s}
    assert by_sig == {"fifo.clk": "posedge", "fifo.rst_n": "negedge"}


def test_tool_width_of(multi_bundle):
    """width_of reports packed/unpacked dim text + data_type keyword."""
    _tree, _comp, graph = multi_bundle
    from scripts.semantic import width_of

    assert width_of(graph, "fifo.mem") == {
        "packed_dim": "[WIDTH-1:0]", "unpacked_dim": "[DEPTH]",
        "data_type": "logic",
    }
    assert width_of(graph, "fifo.wr_ptr")["packed_dim"] == "[$clog2(DEPTH):0]"
    assert width_of(graph, "fifo.din")["packed_dim"] == "[WIDTH-1:0]"
    assert width_of(graph, "fifo.full")["packed_dim"] is None
    assert width_of(graph, "fifo.full")["data_type"] == "logic"


def test_tool_default_value_of(multi_bundle):
    """default_value_of returns the textual default expression of a parameter."""
    _tree, _comp, graph = multi_bundle
    from scripts.semantic import default_value_of

    assert default_value_of(graph, "fifo.DEPTH") == "8"
    assert default_value_of(graph, "fifo.WIDTH") == "32"
    assert default_value_of(graph, "fifo.mem") is None  # not a param


def test_tool_forward_cone(multi_bundle):
    """forward_cone is the symmetric counterpart of cone_of_influence."""
    _tree, _comp, graph = multi_bundle
    from scripts.semantic import forward_cone

    by_id = {n["id"]: n for n in graph["nodes"]}
    paths = {by_id[i].get("semantic", {}).get("path")
             for i in forward_cone(graph, "fifo.din")}
    # din reaches mem (via always_ff write) and dout (via the assign).
    assert "fifo.mem" in paths
    assert "fifo.dout" in paths


def test_graph_query_always_ff_clocked_by_port_clk(multi_bundle):
    """gq: every always_ff sensitive to a port named 'clk' (2-hop typed walk)."""
    _tree, _comp, graph = multi_bundle
    from scripts.semantic import graph_query

    out = graph_query(graph, {
        "match": {"role": "always_ff"},
        "follow": [{"edge": "sensitive_to", "direction": "out",
                    "filter": {"role": "port", "name": "clk"}}],
        "return": "path",
    })
    assert out == ["fifo.clk"]


def test_graph_query_output_port_driven_by_assign_reading_param(multi_bundle):
    """gq: every output port driven by a continuous_assign that reads a parameter."""
    _tree, _comp, graph = multi_bundle
    from scripts.semantic import graph_query

    out = graph_query(graph, {
        "match": {"role": "param"},
        "follow": [
            {"edge": "reads", "direction": "in",
             "filter": {"role": "continuous_assign"}},
            {"edge": "drives", "direction": "out",
             "filter": {"role": "port"}},
        ],
        "return": "path",
    })
    assert set(out) == {"fifo.dout", "fifo.full"}


def test_graph_query_connects_edge_payload_filter(multi_bundle):
    """gq: parent-net side of a specific (instance, port) connection via edge-payload filter."""
    _tree, _comp, graph = multi_bundle
    from scripts.semantic import graph_query

    out = graph_query(graph, {
        "match": {"queryable": True},
        "follow": [{"edge": "connects", "direction": "in",
                    "filter": {"payload_edge": {"instance": "top.u_fifo",
                                                "port": "clk"}}}],
        "return": "path",
    })
    assert out == ["top.clk"]


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
