"""S84 — UserDefinedNetDeclaration promotion.

The S84 rule promotes ``pyslang.SyntaxKind.UserDefinedNetDeclaration`` as a
queryable ``user_defined_net_decl`` group node carrying the user-defined
nettype identifier as the ``net_type`` attribute, and ensures per-net
Declarators inside it surface as role="net" nodes (mirroring S54's
NetDeclarationSyntax convention).  See ``user_net_demo`` in
corpus/fifo.sv.
"""

from __future__ import annotations

from pathlib import Path

import pyslang
import pytest

HERE = Path(__file__).resolve().parent.parent.parent
SRC = HERE / "corpus" / "fifo.sv"


@pytest.fixture(scope="module")
def s84_bundle():
    """Lift + promote corpus/fifo.sv (which contains user_net_demo)."""
    text = SRC.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    comp = pyslang.Compilation()
    comp.addSyntaxTree(tree)
    from knowledge_graph.builders.sv.lift import lift
    from knowledge_graph.builders.sv.semantic import promote

    graph = lift(tree)
    promote(graph, tree, comp)
    return graph


def _user_net_demo_nodes(graph, role):
    return [n for n in graph["nodes"]
            if n.get("semantic", {}).get("role") == role
            and n["semantic"].get("path", "").startswith("user_net_demo.")]


def test_s84_user_defined_net_decl_group_nodes_promoted(s84_bundle):
    """S84: each UserDefinedNetDeclaration in user_net_demo becomes a
    role=user_defined_net_decl node.

    user_net_demo has 2 UserDefinedNetDeclarations
    (``wreal #1 wu1;``  and ``wreal #(2) wu2, wu3;``).
    """
    nodes = _user_net_demo_nodes(s84_bundle, "user_defined_net_decl")
    assert len(nodes) == 2, (
        f"expected 2 user_defined_net_decl nodes in user_net_demo, got "
        f"{len(nodes)}: {[n['semantic'] for n in nodes]}"
    )


def test_s84_net_type_attribute_is_user_nettype(s84_bundle):
    """S84: net_type attribute carries the user-defined nettype identifier
    (``wreal``), not a built-in keyword like ``wire``."""
    nodes = _user_net_demo_nodes(s84_bundle, "user_defined_net_decl")
    types_seen = {n["semantic"]["attributes"]["net_type"] for n in nodes}
    assert types_seen == {"wreal"}, (
        f"unexpected user net_type set: {types_seen}"
    )


def test_s84_child_declarators_promoted_as_nets(s84_bundle):
    """S84 reuses S1/S54's net promotion: the three declarator names
    (wu1, wu2, wu3) all become role=net queryable nodes under
    user_net_demo."""
    nets = _user_net_demo_nodes(s84_bundle, "net")
    names = {n["semantic"]["name"] for n in nets}
    assert names == {"wu1", "wu2", "wu3"}, (
        f"user-defined net declarator promotion lost names; got {names}"
    )


def test_s84_has_user_defined_net_decl_edges(s84_bundle):
    """S84: each user_defined_net_decl node receives a
    has_user_defined_net_decl edge from its enclosing module."""
    grp_ids = {n["id"] for n in _user_net_demo_nodes(
        s84_bundle, "user_defined_net_decl")}
    edges = [e for e in s84_bundle["edges"]
             if e["type"] == "has_user_defined_net_decl"
             and e["dst"] in grp_ids]
    assert len(edges) == 2, (
        f"expected 2 has_user_defined_net_decl edges, got {len(edges)}"
    )


def test_s84_groups_net_edges(s84_bundle):
    """S84: each user_defined_net_decl group emits groups_net edges to its
    child role=net Declarator nodes — 1 + 2 = 3 nets total."""
    net_ids = {n["id"] for n in _user_net_demo_nodes(s84_bundle, "net")}
    edges = [e for e in s84_bundle["edges"]
             if e["type"] == "groups_net" and e["dst"] in net_ids]
    assert len(edges) == 3, (
        f"expected 3 groups_net edges from user_defined_net_decl→net, "
        f"got {len(edges)}"
    )


def test_s84_no_double_count_has_net(s84_bundle):
    """S84 must not double-count: each net Declarator should have exactly
    one has_net edge from the module (S1's standard convention)."""
    net_ids = {n["id"] for n in _user_net_demo_nodes(s84_bundle, "net")}
    has_net = [e for e in s84_bundle["edges"]
               if e["type"] == "has_net" and e["dst"] in net_ids]
    assert len(has_net) == 3, (
        f"expected 3 has_net edges in user_net_demo, got {len(has_net)}"
    )


def test_s84_roundtrip_after_promote():
    """S84 must not mutate token payloads — emit() reproduces fifo.sv
    byte-for-byte after user_net_demo is promoted."""
    text = SRC.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    comp = pyslang.Compilation()
    comp.addSyntaxTree(tree)
    from knowledge_graph.builders.sv.lift import lift
    from knowledge_graph.builders.sv.semantic import promote
    from knowledge_graph.builders.sv.unlift import emit

    graph = lift(tree)
    promote(graph, tree, comp)
    out = emit(graph)
    assert out == text, "round-trip mismatch after S84 promotion"
