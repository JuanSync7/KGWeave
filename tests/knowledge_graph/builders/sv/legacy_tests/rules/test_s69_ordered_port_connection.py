"""Tests for S69 — OrderedPortConnection promotion.

OrderedPortConnectionSyntax is the positional port-hookup form on an
instance: ``dut u1(clk, rst, data_in, data_out);`` — each item is one
connection, in declaration order. Sibling of the named ``.port(net)`` form
already handled by S6 (NamedPortConnection).

S69 emits one ``connects`` edge per OrderedPortConnection — direction
matches S6 NamedPortConnection (inv5 invariant: src=parent net,
dst=child port queryable node). The child port is resolved POSITIONALLY
from the of_module's declared port list (``has_port`` edges in graph
order). The payload carries ``position`` (0-based positional index)
and ``instance`` (the fully-qualified instance path).

Exercised by ``dut_positional u_pos (clk, rst_n, push);`` in
corpus/top.sv — the dut has 3 ports (clk, rst, q) and the instance hooks
them up positionally to (clk, rst_n, push).
"""

from __future__ import annotations

from pathlib import Path

import pyslang
import pytest

HERE = Path(__file__).resolve().parent.parent.parent
SRC = HERE / "corpus" / "top.sv"


@pytest.fixture(scope="module")
def fixture_bundle():
    text = SRC.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    comp = pyslang.Compilation()
    comp.addSyntaxTree(tree)
    from research.ast_experiment.src.lift import lift
    from research.ast_experiment.src.semantic import promote

    graph = lift(tree)
    promote(graph, tree, comp)
    return tree, comp, graph


def _by_role(graph, role):
    from research.ast_experiment.src.semantic import queryable_nodes

    return [n for n in queryable_nodes(graph)
            if n.get("semantic", {}).get("role") == role]


def _u_pos_gid(graph):
    """Find the HierarchicalInstance gid for u_pos."""
    insts = [n for n in _by_role(graph, "instance")
             if n["semantic"].get("name") == "u_pos"]
    assert len(insts) == 1, f"expected exactly 1 u_pos instance, got {len(insts)}"
    return insts[0]["id"]


def _ordered_connects_for_instance(graph, inst_path):
    """All ``connects`` edges whose payload tags them as belonging to
    ``inst_path`` and carries a ``position`` (= S69 ordered, not S6
    named)."""
    return [e for e in graph["edges"]
            if e.get("type") == "connects"
            and (e.get("payload") or {}).get("instance") == inst_path
            and "position" in (e.get("payload") or {})]


def test_s69_three_ordered_connects_emitted(fixture_bundle):
    """The u_pos instance hooks three ports positionally — exactly three
    connects edges with a ``position`` payload should be emitted for
    ``top.u_pos``."""
    _t, _c, graph = fixture_bundle
    edges = _ordered_connects_for_instance(graph, "top.u_pos")
    assert len(edges) == 3, (
        f"expected 3 ordered connects for top.u_pos, got {len(edges)}: {edges}"
    )


def test_s69_position_payloads_are_zero_indexed(fixture_bundle):
    """Position payloads must be 0, 1, 2 — exactly one of each, source
    order preserved."""
    _t, _c, graph = fixture_bundle
    edges = _ordered_connects_for_instance(graph, "top.u_pos")
    positions = sorted(e["payload"]["position"] for e in edges)
    assert positions == [0, 1, 2], (
        f"position payloads not [0,1,2]: {positions}"
    )


def test_s69_resolves_to_top_nets_as_src(fixture_bundle):
    """Direction mirrors S6: src=parent net (one of top.clk / top.rst_n /
    top.push). dst is the child port queryable node (under
    dut_positional). Neither endpoint should be _unresolved for this
    in-corpus instance."""
    from research.ast_experiment.src.semantic import find_by_name

    _t, _c, graph = fixture_bundle
    edges = _ordered_connects_for_instance(graph, "top.u_pos")
    expected_srcs = {find_by_name(graph, p)["id"]
                     for p in ("top.clk", "top.rst_n", "top.push")}
    src_ids = {e["src"] for e in edges}
    assert src_ids == expected_srcs, (
        f"connects sources mismatch: {src_ids} != {expected_srcs}"
    )
    for e in edges:
        assert not (e.get("payload") or {}).get("unresolved", False), (
            f"unexpected unresolved ordered connect: {e}"
        )
        assert not e["dst"].startswith("_unresolved."), (
            f"unexpected _unresolved dst: {e}"
        )


def test_s69_dst_is_child_port_under_dut_positional(fixture_bundle):
    """Each dst gid resolves to a queryable port whose path lives under
    ``dut_positional`` — the of_module type."""
    from research.ast_experiment.src.semantic import queryable_nodes

    _t, _c, graph = fixture_bundle
    by_id = {n["id"]: n for n in queryable_nodes(graph)}
    edges = _ordered_connects_for_instance(graph, "top.u_pos")
    for e in edges:
        dst = by_id.get(e["dst"])
        assert dst is not None, f"dst not queryable: {e['dst']}"
        path = dst.get("semantic", {}).get("path", "")
        assert path.startswith("dut_positional."), (
            f"dst not under dut_positional: {path}"
        )


def test_s69_named_port_connection_unaffected(fixture_bundle):
    """S6 NamedPortConnection still works — u_fifo's named hookups
    produce at least one connects edge with a ``port`` payload."""
    _t, _c, graph = fixture_bundle
    insts = [n for n in _by_role(graph, "instance")
             if n["semantic"].get("name") == "u_fifo"]
    assert len(insts) == 1
    # Named connects edges have payload["port"] set and no "position".
    named = [e for e in graph["edges"]
             if e.get("type") == "connects"
             and "port" in (e.get("payload") or {})
             and "position" not in (e.get("payload") or {})]
    assert len(named) >= 1, (
        "S6 NamedPortConnection regressed — no named connects edges found"
    )


def test_s69_roundtrip(fixture_bundle):
    """Promotion must not perturb the token stream — emit() reproduces source."""
    _t, _c, graph = fixture_bundle
    from research.ast_experiment.src.unlift import emit
    assert emit(graph) == SRC.read_text()
