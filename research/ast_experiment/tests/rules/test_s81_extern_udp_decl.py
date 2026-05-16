"""S81: ``ExternUdpDecl`` promotion — ``extern primitive`` UDP prototypes.

pyslang surfaces ``extern primitive <name> ( <ports> ) ;`` declarations as
the dedicated ``SyntaxKind.ExternUdpDecl`` (one class, one kind — no
sharing). The extern primitive prototype is the UDP analog of S29's
extern module/interface/program headers: a name + port-list contract
whose body lives in a separate ``primitive ... endprimitive`` block.

The UDP *body* is out-of-scope for promotion (closed leaf primitive,
truth-table semantics, not elaborated like an RTL module). The
prototype declaration itself is a first-class structural+semantic
entity and must surface as a queryable node so downstream consumers
can resolve instantiations against it.

S81 verifies:
  * the metadata stub registers ``ExternUdpDecl`` under ``__rule_id__=S81``
  * the rule id is listed in ``_ACTIVE_RULE_IDS``
  * each ``extern primitive`` in the corpus produces a
    ``role=extern_udp`` node with the declared ``name``, ``path``, and
    ``ports`` attribute, in both AnsiUdpPortList and NonAnsiUdpPortList
    variants.
"""

from __future__ import annotations

from pathlib import Path

import pyslang
import pytest

HERE = Path(__file__).resolve().parent.parent.parent
PRIM = HERE / "corpus" / "prim_corpus.sv"


@pytest.fixture(scope="module")
def prim_graph():
    text = PRIM.read_text()
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


def test_s81_in_active_rule_ids():
    """S81 must be listed in ``_ACTIVE_RULE_IDS`` so the bucket1 checklist
    regenerator treats the stub as a live owner of ExternUdpDecl."""
    from research.ast_experiment.src.semantic.dispatch import _ACTIVE_RULE_IDS
    assert "S81" in _ACTIVE_RULE_IDS


def test_s81_stub_owns_extern_udp_decl():
    """The metadata stub registered for ``SyntaxKind.ExternUdpDecl`` must
    pin ``__rule_id__ == 'S81'`` so the Bucket-1 checklist accounts the
    kind as PROMOTE_NOW."""
    from research.ast_experiment.src.semantic.rules import extern
    matches = [
        fn for (kind, fn) in extern.RULES
        if kind == pyslang.SyntaxKind.ExternUdpDecl
    ]
    assert len(matches) == 1, (
        f"expected exactly one stub for ExternUdpDecl, got {len(matches)}"
    )
    assert getattr(matches[0], "__rule_id__", None) == "S81"


def test_s81_extern_udp_nodes_exist(prim_graph):
    """Both extern primitive declarations in ``prim_corpus.sv`` must
    surface as ``role=extern_udp`` nodes — one per AnsiUdpPortList and
    NonAnsiUdpPortList variant."""
    nodes = _by_role(prim_graph, "extern_udp")
    names = sorted(n["semantic"]["name"] for n in nodes)
    assert names == ["my_ext_prim_ansi", "my_ext_prim_nonansi"], names


def test_s81_nonansi_ports(prim_graph):
    """The non-ansi form ``extern primitive my_ext_prim_nonansi
    (out_p, in_p1, in_p2);`` must populate ``ports`` with the three
    bare identifiers in order."""
    nodes = {n["semantic"]["name"]: n
             for n in _by_role(prim_graph, "extern_udp")}
    sem = nodes["my_ext_prim_nonansi"]["semantic"]
    assert sem["attributes"]["ports"] == ["out_p", "in_p1", "in_p2"]


def test_s81_ansi_ports(prim_graph):
    """The ansi form ``extern primitive my_ext_prim_ansi (output reg q,
    input d, input clk);`` must populate ``ports`` with the three
    declared port names in order — the output's identifier and the two
    input identifiers — independent of the surrounding direction /
    type keywords (which stay BLOB on the underlying UdpInputPortDecl /
    UdpOutputPortDecl nodes)."""
    nodes = {n["semantic"]["name"]: n
             for n in _by_role(prim_graph, "extern_udp")}
    sem = nodes["my_ext_prim_ansi"]["semantic"]
    assert sem["attributes"]["ports"] == ["q", "d", "clk"]


def test_s81_cu_scope_path_is_bare_name(prim_graph):
    """Both extern UDP declarations live at compilation-unit scope in
    the corpus; their ``path`` must therefore be the bare declared
    name (no parent prefix), mirroring how S24/S28/S29 handle cu-scope
    entities."""
    nodes = {n["semantic"]["name"]: n
             for n in _by_role(prim_graph, "extern_udp")}
    assert nodes["my_ext_prim_nonansi"]["semantic"]["path"] \
        == "my_ext_prim_nonansi"
    assert nodes["my_ext_prim_ansi"]["semantic"]["path"] \
        == "my_ext_prim_ansi"


def test_s81_cu_scope_no_containment_edge(prim_graph):
    """Compilation-unit-scoped extern UDP decls must NOT receive a
    ``has_extern_udp_decl`` containment edge — there is no enclosing
    module to attach them to."""
    edges = [e for e in prim_graph["edges"]
             if e.get("type") == "has_extern_udp_decl"]
    assert edges == [], (
        f"unexpected has_extern_udp_decl edges for cu-scope decls: {edges}"
    )
