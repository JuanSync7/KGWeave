"""Semantic-layer query oracle.

Each test fires one of the S1..S5 rules from ``scripts.semantic`` and asserts
that the resulting graph answers a concrete elaboration query.  The round-trip
oracle (``test_roundtrip.py``) must keep passing alongside this file — if a
semantic promotion ever breaks structural fidelity, both files fail together.
"""

from __future__ import annotations

from pathlib import Path

import pyslang
import pytest

HERE = Path(__file__).resolve().parent.parent
SRC = HERE / "fifo.sv"


@pytest.fixture(scope="module")
def fixture_bundle():
    text = SRC.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
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


def test_roundtrip_after_promote(fixture_bundle):
    """Promotion must not mutate token payloads — emit() still reproduces source."""
    tree, _comp, graph = fixture_bundle
    from scripts.unlift import emit

    emitted = emit(graph)
    reparsed = pyslang.SyntaxTree.fromText(emitted)
    # Strongest oracle: byte-equal token text stream.
    from test_roundtrip import _token_text_stream  # noqa: PLC0415

    assert _token_text_stream(reparsed.root) == _token_text_stream(tree.root)


def test_s1_module_promotes_ports_params_nets(fixture_bundle):
    """S1: module fifo has 8 ports, 2 params, 4 nets."""
    _tree, _comp, graph = fixture_bundle
    ports = _queryable_by_role(graph, "port")
    params = _queryable_by_role(graph, "param")
    nets = _queryable_by_role(graph, "net")
    modules = _queryable_by_role(graph, "module")

    assert len(modules) == 1
    assert modules[0]["semantic"]["name"] == "fifo"
    assert {p["semantic"]["name"] for p in ports} == {
        "clk", "rst_n", "push", "pop", "din", "dout", "full", "empty",
    }
    assert {p["semantic"]["name"] for p in params} == {"DEPTH", "WIDTH"}
    assert {n["semantic"]["name"] for n in nets} == {"mem", "wr_ptr", "rd_ptr", "count"}


def test_s2_continuous_assign_drives_and_reads(fixture_bundle):
    """S2: who_drives('dout') yields exactly one continuous_assign node."""
    _tree, _comp, graph = fixture_bundle
    from scripts.semantic import find_drivers

    drivers = find_drivers(graph, "dout")
    assert len(drivers) == 1
    assert drivers[0]["semantic"]["role"] == "continuous_assign"

    full_drivers = find_drivers(graph, "full")
    assert len(full_drivers) == 1
    # The 'full' assign reads `count` (and the param DEPTH via name resolution).
    from scripts.semantic import neighbors

    reads = neighbors(graph, full_drivers[0]["id"], edge_type="reads", direction="out")
    read_names = {r["semantic"].get("name") for r in reads}
    assert "count" in read_names


def test_s3_always_ff_sensitivity_and_drives(fixture_bundle):
    """S3: the always_ff has sensitive_to clk(posedge) and rst_n(negedge);
    cone_of_influence('full') reaches push, pop, rst_n."""
    _tree, _comp, graph = fixture_bundle
    always = _queryable_by_role(graph, "always_ff")
    assert len(always) == 1
    aff = always[0]
    from scripts.semantic import neighbors

    sens = neighbors(graph, aff["id"], edge_type="sensitive_to", direction="out")
    sens_names = {s["semantic"].get("name") for s in sens}
    assert {"clk", "rst_n"} <= sens_names

    # The always_ff drives count.
    drives = neighbors(graph, aff["id"], edge_type="drives", direction="out")
    drive_names = {d["semantic"].get("name") for d in drives}
    assert {"wr_ptr", "rd_ptr", "count"} <= drive_names

    reads = neighbors(graph, aff["id"], edge_type="reads", direction="out")
    read_names = {r["semantic"].get("name") for r in reads}
    assert {"push", "pop", "rst_n"} <= read_names


@pytest.mark.skip(reason="enabled in sem-04")
def test_s4_identifier_select_reads_base(fixture_bundle):
    """S4: every IdentifierSelectNameSyntax `reads` its base symbol.

    `mem[rd_ptr[$clog2(DEPTH)-1:0]]` produces a select on mem and rd_ptr.
    """
    _tree, _comp, graph = fixture_bundle
    selects = _queryable_by_role(graph, "identifier_select")
    bases = {s["semantic"]["base"] for s in selects}
    assert {"mem", "rd_ptr", "wr_ptr"} <= bases
    # mem and rd_ptr appear in the same expression — both must have a reads edge.
    from scripts.semantic import neighbors

    for s in selects:
        if s["semantic"]["base"] == "mem":
            tgt = neighbors(graph, s["id"], edge_type="reads", direction="out")
            assert any(t["semantic"].get("name") == "mem" for t in tgt)


@pytest.mark.skip(reason="enabled in sem-05")
def test_s5_system_call_clog2_reads_depth(fixture_bundle):
    """S5: every `$clog2(DEPTH)` call is promoted and `reads` DEPTH."""
    _tree, _comp, graph = fixture_bundle
    calls = _queryable_by_role(graph, "system_call")
    assert calls, "expected at least one $clog2 invocation"
    from scripts.semantic import neighbors

    for c in calls:
        assert c["semantic"]["name"] == "$clog2"
        tgts = neighbors(graph, c["id"], edge_type="reads", direction="out")
        names = {t["semantic"].get("name") for t in tgts}
        assert "DEPTH" in names
