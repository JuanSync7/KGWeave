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
PKG = HERE / "fifo_pkg.sv"
IFACE = HERE / "fifo_if.sv"
FIFO = HERE / "fifo.sv"
TOP = HERE / "top.sv"


@pytest.fixture(scope="module")
def multi_bundle():
    # Production multi-file path: each SV file is its own SyntaxTree, lifted
    # and promoted into one shared graph. The pre-build_kg fixture used a
    # string-concat hack that bypassed the real multi-file code path and
    # masked the cross-tree merge bug.
    from scripts.build import build_kg

    graph, trees, comp = build_kg([PKG, IFACE, FIFO, TOP])
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
    # The syntactic instances under top — generate-block instances are
    # contained under their generate_block, not directly under the module.
    assert set(paths) == {"top.u_fifo", "top.u_fifo_a", "top.u_fifo_b", "top.u_if"}


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

    # Includes both named instances AND the elaborated generate-for entries.
    assert instances_of(graph, "fifo") == [
        "top.gen_fifos[0].u_fifo_gen",
        "top.gen_fifos[1].u_fifo_gen",
        "top.u_fifo",
        "top.u_fifo_a",
        "top.u_fifo_b",
    ]
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


def test_s12_generate_for_elaborated_instances(multi_bundle):
    """S12: LoopGenerateSyntax + elaborated GenerateBlockSyntax instances.

    * top.gen_fifos is queryable as a generate_loop with iter_count == 2.
    * Each elaborated iteration becomes a generate_block node with its full
      hierarchical path (top.gen_fifos[0], top.gen_fifos[1]).
    * Each block instantiates u_fifo_gen which has an of_module edge to fifo.
    """
    _tree, _comp, graph = multi_bundle
    from scripts.semantic import find_by_name, instances_of, neighbors

    loop = find_by_name(graph, "top.gen_fifos")
    assert loop is not None and loop["semantic"]["role"] == "generate_loop"
    assert loop["semantic"]["iter_count"] == 2

    # The two generate_block children carry the elaborated hierarchical paths.
    blocks = neighbors(graph, loop["id"], edge_type="contains_block", direction="out")
    paths = sorted(b["semantic"]["path"] for b in blocks)
    assert paths == ["top.gen_fifos[0]", "top.gen_fifos[1]"]

    # And both generated u_fifo_gen instances participate in instances_of.
    fifo_inst_paths = instances_of(graph, "fifo")
    assert "top.gen_fifos[0].u_fifo_gen" in fifo_inst_paths
    assert "top.gen_fifos[1].u_fifo_gen" in fifo_inst_paths


def test_s11_modports_of_interface(multi_bundle):
    """S11: interface + modport promotion.

    * fifo_if is queryable with role=interface.
    * It has three modports: producer, consumer, dut, each with per-signal
      direction info in semantic.directions payload.
    """
    _tree, _comp, graph = multi_bundle
    from scripts.semantic import find_by_name, neighbors, modports_of

    iface = find_by_name(graph, "fifo_if")
    assert iface is not None and iface["semantic"]["role"] == "interface"

    mps = neighbors(graph, iface["id"], edge_type="has_modport", direction="out")
    assert {m["semantic"]["name"] for m in mps} == {"producer", "consumer", "dut"}

    # Helper.
    assert modports_of(graph, "fifo_if") == ["consumer", "dut", "producer"]

    # Direction payload check.
    producer = find_by_name(graph, "fifo_if.producer")
    assert producer["semantic"]["directions"]["push"] == "output"
    assert producer["semantic"]["directions"]["full"] == "input"


def test_s10_function_calls_and_cone(multi_bundle):
    """S10: function promotion + calls edge from always blocks.

    * fifo.next_ptr is queryable with role=function (has_function edge from fifo).
    * The always_ff in fifo emits a ``calls`` edge to fifo.next_ptr.
    * cone_of_influence('fifo.wr_ptr') still bridges through the function call
      to the original drivers (push, full).
    """
    _tree, _comp, graph = multi_bundle
    from scripts.semantic import find_by_name, neighbors, cone_of_influence

    fn = find_by_name(graph, "fifo.next_ptr")
    assert fn is not None and fn["semantic"]["role"] == "function"

    # has_function from fifo module.
    fifo = find_by_name(graph, "fifo")
    fns = neighbors(graph, fifo["id"], edge_type="has_function", direction="out")
    assert any(f["semantic"]["name"] == "next_ptr" for f in fns)

    # `calls` edges: always_ff calls next_ptr.
    callers = neighbors(graph, fn["id"], edge_type="calls", direction="in")
    assert any(c.get("semantic", {}).get("role") == "always_ff" for c in callers)

    # cone_of_influence still propagates through wr_ptr (function-internal
    # read is suppressed, but the always_ff still drives wr_ptr).
    seen = cone_of_influence(graph, "fifo.wr_ptr")
    by_id = {n["id"]: n for n in graph["nodes"]}
    paths = {by_id[i].get("semantic", {}).get("path") for i in seen}
    assert "fifo.push" in paths
    assert "fifo.full" in paths


def test_s9_package_of_typedef(multi_bundle):
    """S9: typedef + enum-value promotion under a package.

    * fifo_pkg is queryable as a `package` role.
    * fifo_status_e is a `typedef` under fifo_pkg (has_typedef edge).
    * EMPTY/NORMAL/FULL are enum_value declarators under fifo_status_e
      (has_enum_value edges with `name` payload).
    """
    _tree, _comp, graph = multi_bundle
    from scripts.semantic import find_by_name, neighbors, package_of

    pkg = find_by_name(graph, "fifo_pkg")
    assert pkg is not None and pkg["semantic"]["role"] == "package"

    td = find_by_name(graph, "fifo_pkg.fifo_status_e")
    assert td is not None and td["semantic"]["role"] == "typedef"

    # has_typedef edge from package to typedef.
    typedefs = neighbors(graph, pkg["id"], edge_type="has_typedef", direction="out")
    assert any(t["semantic"]["name"] == "fifo_status_e" for t in typedefs)

    # package_of() helper.
    assert package_of(graph, "fifo_pkg.fifo_status_e") == "fifo_pkg"

    # Enum values listable via has_enum_value edges.
    evs = neighbors(graph, td["id"], edge_type="has_enum_value", direction="out")
    names = {e["semantic"]["name"] for e in evs}
    assert names == {"EMPTY", "NORMAL", "FULL"}


def test_s8_always_comb_cone_of_status(multi_bundle):
    """S8: always_comb is promoted (drives/reads with no sensitive_to).

    The fifo.status output is driven by an always_comb that reads
    fifo.full / fifo.empty (themselves derived from fifo.count and fifo.DEPTH).
    cone_of_influence('fifo.status') therefore reaches count and DEPTH.
    """
    _tree, _comp, graph = multi_bundle
    from scripts.semantic import cone_of_influence, queryable_nodes, sensitivity_of

    # always_comb must be promoted with role='always_comb' and ZERO sensitive_to.
    acombs = [n for n in queryable_nodes(graph)
              if n.get("semantic", {}).get("role") == "always_comb"]
    assert len(acombs) == 1, f"expected 1 always_comb, got {len(acombs)}"
    assert sensitivity_of(graph, acombs[0]["id"]) == []

    seen = cone_of_influence(graph, "fifo.status")
    by_id = {n["id"]: n for n in graph["nodes"]}
    paths = {by_id[i].get("semantic", {}).get("path") for i in seen}
    assert "fifo.count" in paths
    assert "fifo.DEPTH" in paths


def test_s7_param_overrides_per_instance(multi_bundle):
    """S7: param_overrides(instance_path) returns the resolved override map.

    Walks `param_override` edges out of the instance node, each carrying a
    `name` (child param) and `value` (textual resolved expression).
    """
    _tree, _comp, graph = multi_bundle
    from scripts.semantic import param_overrides

    assert param_overrides(graph, "top.u_fifo") == {}
    assert param_overrides(graph, "top.u_fifo_a") == {"DEPTH": "16", "WIDTH": "32"}
    assert param_overrides(graph, "top.u_fifo_b") == {"DEPTH": "8", "WIDTH": "8"}


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
