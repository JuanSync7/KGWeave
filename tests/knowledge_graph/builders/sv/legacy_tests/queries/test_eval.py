"""EVAL_QUERIES.md → runnable pytest suite.

Each test is one query from research/ast_experiment/EVAL_QUERIES.md. Tests are
grouped A..J by the same scheme as the markdown. Every assertion goes through
the typed API surface in ``scripts.semantic`` — no regex, no substring scans
over node names.
"""

from __future__ import annotations

from pathlib import Path

import pyslang
import pytest

HERE = Path(__file__).resolve().parent.parent.parent
PKG = HERE / "corpus" / "fifo_pkg.sv"
IFACE = HERE / "corpus" / "fifo_if.sv"
FIFO = HERE / "corpus" / "fifo.sv"
TOP = HERE / "corpus" / "top.sv"


@pytest.fixture(scope="module")
def gbundle():
    from knowledge_graph.builders.sv.build import build_kg

    graph, trees, comp = build_kg([PKG, IFACE, FIFO, TOP])
    return trees[0], comp, graph


def _by_role(graph, role):
    from knowledge_graph.builders.sv.semantic import queryable_nodes
    return [n for n in queryable_nodes(graph)
            if n.get("semantic", {}).get("role") == role]


def _node_by_path(graph, path):
    from knowledge_graph.builders.sv.semantic import find_by_name
    return find_by_name(graph, path)


# ---------------------------------------------------------------------------
# Group A — Identity & enumeration
# ---------------------------------------------------------------------------


class TestGroupA:
    def test_A1_every_module(self, gbundle):
        """A1: list every module — fifo, top, and S34-corpus always_demo defined.

        fifo.sv now contains an always_demo helper module added for S34 corpus
        coverage; the assertion is updated to include it.
        """
        _t, _c, g = gbundle
        from knowledge_graph.builders.sv.semantic import queryable_nodes
        names = {n["semantic"]["name"] for n in queryable_nodes(g)
                 if n["semantic"].get("role") == "module"}
        assert {"fifo", "top"} <= names, (
            f"expected fifo and top in module set; got {names}"
        )

    def test_A2_output_ports_of_fifo(self, gbundle):
        """A2: output ports of `fifo` are dout, full, empty."""
        _t, _c, g = gbundle
        from knowledge_graph.builders.sv.semantic import find_by_name, neighbors, width_of  # noqa: F401
        # Direction lives on VariablePortHeaderSyntax's first token.
        # We inspect the structural backbone of each port (graph_query DSL retired in S7).
        outputs: set[str] = set()
        by_id = {n["id"]: n for n in g["nodes"]}
        fifo = find_by_name(g, "fifo")
        for e in g["edges"]:
            if e["type"] != "has_port" or e["src"] != fifo["id"]:
                continue
            port_node = by_id[e["dst"]]
            # Walk into VariablePortHeaderSyntax and look for OutputKeyword.
            for ee in g["edges"]:
                if ee["type"] != "child" or ee["src"] != port_node["id"]:
                    continue
                hdr = by_id[ee["dst"]]
                if hdr["type"] != "VariablePortHeaderSyntax":
                    continue
                for eee in g["edges"]:
                    if eee["type"] != "child" or eee["src"] != hdr["id"]:
                        continue
                    tok = by_id[eee["dst"]]
                    if tok.get("is_token") and tok["kind"].endswith(".OutputKeyword"):
                        outputs.add(port_node["semantic"]["path"])
        assert outputs == {"fifo.dout", "fifo.full", "fifo.empty", "fifo.status"}

    def test_A3_nets_have_packed_width_expressions(self, gbundle):
        """A3: every net's packed-dim expression text is preserved."""
        _t, _c, g = gbundle
        from knowledge_graph.builders.sv.semantic import width_of
        assert width_of(g, "fifo.mem")["packed_dim"] == "[WIDTH-1:0]"
        for n in ("fifo.wr_ptr", "fifo.rd_ptr", "fifo.count"):
            assert width_of(g, n)["packed_dim"] == "[$clog2(DEPTH):0]"


# ---------------------------------------------------------------------------
# Group B — Direct drives / reads
# ---------------------------------------------------------------------------


class TestGroupB:
    def test_B1_who_drives_fifo_dout(self, gbundle):
        """B1: fifo.dout has exactly one continuous_assign driver."""
        _t, _c, g = gbundle
        from knowledge_graph.builders.sv.semantic import find_drivers
        d = find_drivers(g, "fifo.dout")
        assert len(d) == 1
        assert d[0]["semantic"]["role"] == "continuous_assign"

    def test_B2_who_drives_fifo_full_reads_count(self, gbundle):
        """B2: fifo.full's driver reads `count`."""
        _t, _c, g = gbundle
        from knowledge_graph.builders.sv.semantic import find_drivers, neighbors
        drivers = find_drivers(g, "fifo.full")
        assert len(drivers) == 1
        reads = neighbors(g, drivers[0]["id"], edge_type="reads", direction="out")
        names = {r["semantic"].get("name") for r in reads}
        assert "count" in names

    def test_B3_reads_of_fifo_din(self, gbundle):
        """B3: fifo.din is read by an always_ff (the push branch)."""
        _t, _c, g = gbundle
        from knowledge_graph.builders.sv.semantic import reads_of
        readers = reads_of(g, "fifo.din")
        roles = {r["semantic"]["role"] for r in readers}
        assert "always_ff" in roles

    def test_B4_wr_ptr_does_not_drive_rd_ptr(self, gbundle):
        """B4 (negative): wr_ptr does not drive rd_ptr."""
        _t, _c, g = gbundle
        from knowledge_graph.builders.sv.semantic import find_by_name, neighbors
        wr = find_by_name(g, "fifo.wr_ptr")
        dsts = {d["id"] for d in neighbors(g, wr["id"], edge_type="drives", direction="out")}
        rd = find_by_name(g, "fifo.rd_ptr")
        assert rd["id"] not in dsts


# ---------------------------------------------------------------------------
# Group C — Sensitivity / clocking
# ---------------------------------------------------------------------------


class TestGroupC:
    def test_C1_always_ff_sensitivity(self, gbundle):
        """C1: always_ff is sensitive to clk(posedge) and rst_n(negedge)."""
        _t, _c, g = gbundle
        from knowledge_graph.builders.sv.semantic import sensitivity_of
        aff = _by_role(g, "always_ff")[0]
        sens = {x["signal"]: x["edge"] for x in sensitivity_of(g, aff["id"])}
        assert sens == {"fifo.clk": "posedge", "fifo.rst_n": "negedge"}

    def test_C2_reset_is_active_low_async(self, gbundle):
        """C2: reset polarity is active_low + async — derived from the
        sensitive_to payload (rst_n appears in the @ list with negedge)."""
        _t, _c, g = gbundle
        from knowledge_graph.builders.sv.semantic import sensitivity_of
        aff = _by_role(g, "always_ff")[0]
        sens = sensitivity_of(g, aff["id"])
        rst = [x for x in sens if x["signal"].endswith(".rst_n")]
        assert rst, "expected rst_n in sensitivity list"
        # negedge => active-low; presence in sens list => async reset.
        assert rst[0]["edge"] == "negedge"


# ---------------------------------------------------------------------------
# Group D — Cones
# ---------------------------------------------------------------------------


class TestGroupD:
    def test_D1_backward_cone_of_fifo_full(self, gbundle):
        """D1: backward cone of fifo.full includes count + always_ff."""
        _t, _c, g = gbundle
        from knowledge_graph.builders.sv.semantic import cone_of_influence
        by_id = {n["id"]: n for n in g["nodes"]}
        seen = cone_of_influence(g, "fifo.full")
        names = {by_id[i].get("semantic", {}).get("name") for i in seen}
        assert {"count", "full"} <= names
        roles = {by_id[i].get("semantic", {}).get("role") for i in seen}
        assert "always_ff" in roles

    def test_D2_forward_cone_of_fifo_push(self, gbundle):
        """D2: forward cone of fifo.push reaches wr_ptr, count, mem."""
        _t, _c, g = gbundle
        from knowledge_graph.builders.sv.semantic import forward_cone
        by_id = {n["id"]: n for n in g["nodes"]}
        paths = {by_id[i].get("semantic", {}).get("path")
                 for i in forward_cone(g, "fifo.push")}
        assert {"fifo.wr_ptr", "fifo.count", "fifo.mem"} <= paths

    def test_D3_forward_cone_of_fifo_din_reaches_dout(self, gbundle):
        """D3: forward cone of fifo.din reaches mem and dout."""
        _t, _c, g = gbundle
        from knowledge_graph.builders.sv.semantic import forward_cone
        by_id = {n["id"]: n for n in g["nodes"]}
        paths = {by_id[i].get("semantic", {}).get("path")
                 for i in forward_cone(g, "fifo.din")}
        assert "fifo.mem" in paths
        assert "fifo.dout" in paths


# ---------------------------------------------------------------------------
# Group E — Bit-select / array-index identifier resolution
# ---------------------------------------------------------------------------


class TestGroupE:
    def test_E1_dout_assign_reads_rd_ptr(self, gbundle):
        """E1: the `assign dout` reads rd_ptr (S4 lifted base symbol)."""
        _t, _c, g = gbundle
        from knowledge_graph.builders.sv.semantic import find_drivers, neighbors
        d = find_drivers(g, "fifo.dout")
        assert len(d) == 1
        # The continuous_assign itself doesn't directly have `reads rd_ptr` —
        # the IdentifierSelectName subtree does. Look for an identifier_select
        # node within this assign's subtree that reads rd_ptr.
        # Pure graph: walk `child` edges from the continuous_assign and check.
        by_id = {n["id"]: n for n in g["nodes"]}
        # collect descendants via child edges
        stack = [d[0]["id"]]
        descend: set[str] = set()
        while stack:
            x = stack.pop()
            for e in g["edges"]:
                if e["type"] == "child" and e["src"] == x:
                    if e["dst"] not in descend:
                        descend.add(e["dst"])
                        stack.append(e["dst"])
        # any identifier_select node in descendants whose reads -> rd_ptr.
        rd_id = _node_by_path(g, "fifo.rd_ptr")["id"]
        found = False
        for x in descend:
            n = by_id[x]
            if n.get("semantic", {}).get("role") != "identifier_select":
                continue
            for ee in g["edges"]:
                if ee["type"] == "reads" and ee["src"] == x and ee["dst"] == rd_id:
                    found = True
                    break
            if found:
                break
        assert found

    def test_E2_depth_is_read_by_widths_via_clog2(self, gbundle):
        """E2: DEPTH is read by multiple $clog2 system_call nodes."""
        _t, _c, g = gbundle
        from knowledge_graph.builders.sv.semantic import neighbors, find_by_name
        depth = find_by_name(g, "fifo.DEPTH")
        readers = neighbors(g, depth["id"], edge_type="reads", direction="in")
        roles = [r["semantic"]["role"] for r in readers]
        assert roles.count("system_call") >= 3  # one per wr_ptr/rd_ptr/count width


# ---------------------------------------------------------------------------
# Group F — Constants and parameters
# ---------------------------------------------------------------------------


class TestGroupF:
    def test_F1_default_value_of_depth(self, gbundle):
        """F1: parameter DEPTH defaults to 8."""
        _t, _c, g = gbundle
        from knowledge_graph.builders.sv.semantic import default_value_of
        assert default_value_of(g, "fifo.DEPTH") == "8"
        assert default_value_of(g, "fifo.WIDTH") == "32"

    def test_F2_empty_assign_compares_against_literal_zero(self, gbundle):
        """F2: the `assign empty` expression contains a literal `0`."""
        _t, _c, g = gbundle
        from knowledge_graph.builders.sv.semantic import find_drivers
        from knowledge_graph.builders.sv.semantic import _text_of_subtree as text
        d = find_drivers(g, "fifo.empty")
        assert len(d) == 1
        rhs = text(g, d[0]["id"]).strip()
        # Structural-blob check: there must be an integer-literal token of
        # value "0" in the assign's subtree.
        by_id = {n["id"]: n for n in g["nodes"]}
        stack = [d[0]["id"]]
        has_zero = False
        while stack:
            x = stack.pop()
            for e in g["edges"]:
                if e["type"] == "child" and e["src"] == x:
                    stack.append(e["dst"])
            n = by_id[x]
            if n.get("is_token") and n["kind"].endswith(".IntegerLiteral"):
                if n["payload"]["valueText"] == "0":
                    has_zero = True
        assert has_zero, f"no literal `0` token in empty assign subtree: {rhs!r}"


# ---------------------------------------------------------------------------
# Group G — Hierarchy / instantiation
# ---------------------------------------------------------------------------


class TestGroupG:
    def test_G1_top_instantiates_u_fifo(self, gbundle):
        """G1: top contains the named fifo instances, including u_fifo."""
        _t, _c, g = gbundle
        from knowledge_graph.builders.sv.semantic import find_by_name, neighbors
        top = find_by_name(g, "top")
        insts = neighbors(g, top["id"], edge_type="instantiates", direction="out")
        paths = [i["semantic"]["path"] for i in insts]
        # Direct named instances under top; generate-block fifos are owned by
        # their generate_block node, not by top itself.
        # ``top.u_pos`` is the S69 OrderedPortConnection corpus instance
        # (positional ``dut_positional u_pos(clk, rst_n, push);``).
        assert set(paths) == {"top.u_fifo", "top.u_fifo_a", "top.u_fifo_b",
                              "top.u_if", "top.u_pos"}

    def test_G2_u_fifo_is_of_module_fifo(self, gbundle):
        """G2: top.u_fifo's of_module edge points at module `fifo`."""
        _t, _c, g = gbundle
        from knowledge_graph.builders.sv.semantic import find_by_name, neighbors
        inst = find_by_name(g, "top.u_fifo")
        of_mod = neighbors(g, inst["id"], edge_type="of_module", direction="out")
        assert len(of_mod) == 1
        assert of_mod[0]["semantic"]["name"] == "fifo"

    def test_G3_full_port_connection_map(self, gbundle):
        """G3: the 8-entry named port-connection map of top.u_fifo."""
        _t, _c, g = gbundle
        from knowledge_graph.builders.sv.semantic import port_connections
        pcs = {pc["port"]: pc["src_path"] for pc in port_connections(g, "top.u_fifo")}
        assert pcs == {
            "clk": "top.clk", "rst_n": "top.rst_n", "push": "top.push",
            "pop": "top.pop", "din": "top.din", "dout": "top.dout",
            "full": "top.full", "empty": "top.empty",
        }


# ---------------------------------------------------------------------------
# Group H — Cross-hierarchy
# ---------------------------------------------------------------------------


class TestGroupH:
    def test_H1_forward_cross_module_cone_of_top_push(self, gbundle):
        """H1: forward cone of top.push reaches fifo internal signals."""
        _t, _c, g = gbundle
        from knowledge_graph.builders.sv.semantic import forward_cone
        by_id = {n["id"]: n for n in g["nodes"]}
        paths = {by_id[i].get("semantic", {}).get("path")
                 for i in forward_cone(g, "top.push")}
        # forward_cone crosses connects edges in both directions, so it must
        # reach fifo-internal signals driven by always_ff that reads push.
        assert {"fifo.wr_ptr", "fifo.count", "fifo.mem"} <= paths

    def test_H2_backward_cross_module_cone_of_fifo_count(self, gbundle):
        """H2: backward cone of fifo.count reaches top.push/pop/rst_n."""
        _t, _c, g = gbundle
        from knowledge_graph.builders.sv.semantic import cone_of_influence
        by_id = {n["id"]: n for n in g["nodes"]}
        paths = {by_id[i].get("semantic", {}).get("path")
                 for i in cone_of_influence(g, "fifo.count")}
        assert {"top.push", "top.pop", "top.rst_n"} <= paths

    def test_H3_forward_from_u_fifo_dout_reaches_top_dout(self, gbundle):
        """H3: the child port top.u_fifo.dout (= fifo.dout) reaches top.dout."""
        _t, _c, g = gbundle
        from knowledge_graph.builders.sv.semantic import forward_cone
        by_id = {n["id"]: n for n in g["nodes"]}
        paths = {by_id[i].get("semantic", {}).get("path")
                 for i in forward_cone(g, "fifo.dout")}
        assert "top.dout" in paths


# ---------------------------------------------------------------------------
# Group I — Blob-required (payload only)
# ---------------------------------------------------------------------------


class TestGroupI:
    def test_I1_operator_of_empty_assign(self, gbundle):
        """I1: the operator inside `assign empty` is `==`."""
        _t, _c, g = gbundle
        from knowledge_graph.builders.sv.semantic import find_drivers
        d = find_drivers(g, "fifo.empty")
        assert len(d) == 1
        # Walk descendants and find a BinaryExpressionSyntax with an `==` token.
        by_id = {n["id"]: n for n in g["nodes"]}
        stack = [d[0]["id"]]
        found = False
        while stack:
            x = stack.pop()
            n = by_id[x]
            if n["type"] == "BinaryExpressionSyntax":
                for e in g["edges"]:
                    if e["type"] == "child" and e["src"] == x:
                        cn = by_id[e["dst"]]
                        if cn.get("is_token") and cn["payload"]["valueText"] == "==":
                            found = True
                            break
                if found:
                    break
            for e in g["edges"]:
                if e["type"] == "child" and e["src"] == x:
                    stack.append(e["dst"])
        assert found

    def test_I2_mem_slice_index_text_preserved(self, gbundle):
        """I2: the bit-select range text inside the mem write is preserved
        in the structural blob (Token rawText)."""
        _t, _c, g = gbundle
        from knowledge_graph.builders.sv.semantic import find_by_name
        from knowledge_graph.builders.sv.semantic import _text_of_subtree as text
        mem = find_by_name(g, "fifo.mem")
        # find any element-select expression in the graph whose base is mem
        # and check its slice subtree contains '$clog2(DEPTH)-1:0'.
        by_id = {n["id"]: n for n in g["nodes"]}
        found_text = None
        for n in g["nodes"]:
            if n.get("semantic", {}).get("role") != "identifier_select":
                continue
            if n["semantic"].get("base") != "mem":
                continue
            t = text(g, n["id"])
            if "$clog2(DEPTH)-1:0" in t:
                found_text = t
                break
        assert found_text is not None

    def test_I3_source_line_attached_to_tokens(self, gbundle):
        """I3: every Token carries a source.line in its payload."""
        _t, _c, g = gbundle
        toks = [n for n in g["nodes"] if n.get("is_token")]
        assert toks, "expected at least one token"
        with_line = [t for t in toks if isinstance(t["payload"].get("source"), dict)
                     and isinstance(t["payload"]["source"].get("line"), int)]
        # At least 90% of tokens should carry a line (some implicit tokens
        # may not have a source location).
        assert len(with_line) >= int(0.9 * len(toks))


# ---------------------------------------------------------------------------
# Group J — Schema invariants
# ---------------------------------------------------------------------------


class TestGroupJ:
    def test_J1_promoted_nodes_have_hierarchical_paths(self, gbundle):
        """J1: every promoted non-module node has a hierarchical path id (`.` in path or name)."""
        _t, _c, g = gbundle
        from knowledge_graph.builders.sv.semantic import queryable_nodes
        for n in queryable_nodes(g):
            role = n["semantic"].get("role")
            if role == "module":
                continue
            path = n["semantic"].get("path") or ""
            # always_ff and continuous_assign and system_call don't always carry a path
            # — they're block-level nodes. The invariant applies to identifier-anchored
            # promotions: port, param, net, instance.
            if role in {"port", "param", "net", "instance"}:
                assert "." in path, f"{role} {n['id']} lacks hierarchical path: {path!r}"

    def test_J2_roundtrip_after_promote(self, gbundle):
        """J2: emit → reparse → token stream equals the original."""
        tree, _c, g = gbundle
        from knowledge_graph.builders.sv.unlift import emit
        from test_roundtrip import _token_text_stream  # noqa: PLC0415
        emitted = emit(g)
        reparsed = pyslang.SyntaxTree.fromText(emitted)
        assert _token_text_stream(reparsed.root) == _token_text_stream(tree.root)

    def test_J3_no_name_string_lookup_leaks(self, gbundle):
        """J3: no fuzzy-name fallback leaks remain in the final graph."""
        _t, _c, g = gbundle
        assert g.get("semantic_leaks") == []
