"""S86 — ``InterfacePortHeader`` attribute-augmentation on ANSI ports.

``SyntaxKind.InterfacePortHeader`` is the header form on an ANSI port
declaration that uses an interface type as the port's data type — for
example ``module m(bus_if.master b);``. pyslang shapes it as
``InterfacePortHeaderSyntax(nameOrKeyword=<Identifier|InterfaceKeyword>,
modport=DotMemberClauseSyntax|None)``.

Per ``CLAUDE.md`` lesson 5 (attribute-augmentation flavour), S86 is
wired inline in the S1 ``ImplicitAnsiPortSyntax`` dispatch branch
rather than as a separate top-level dispatch — when the port's header
is an InterfacePortHeader the port promotes with
``role="interface_port"`` (instead of the default ``role="port"``)
and the ``interface_type`` and optional ``modport`` attributes are
lifted from the header onto the port semantic node. The port name
still comes from the sibling DeclaratorSyntax and the ``has_port``
edge / path key are unchanged from S1.

Corpus: ``corpus/iface_port_corpus.sv`` exercises three header
shapes — ``fifo_if.dut a`` (modport-qualified), ``fifo_if.consumer
b`` (modport-qualified), ``interface c`` (keyword form, no modport).

Tests:

* S86 is registered in ``dispatch._ACTIVE_RULE_IDS``.
* The metadata stub registered for ``SyntaxKind.InterfacePortHeader``
  pins ``__rule_id__ == 'S86'`` and there is exactly one such
  registration.
* ``SyntaxKind.InterfacePortHeader`` resolves through the composed
  ``RULE_TABLE`` to the S86 stub.
* The three interface-typed ports in
  ``corpus/iface_port_corpus.sv`` promote with
  ``role == 'interface_port'`` and the expected
  ``interface_type`` / ``modport`` attributes.
* Existing ``role == 'port'`` promotions in ``corpus/fifo.sv`` are
  unchanged (S86 must not affect plain variable-typed ports — no
  regression of S1).
* Round-trip on ``corpus/iface_port_corpus.sv`` is byte-equal.
"""

from __future__ import annotations

from pathlib import Path

import pyslang
import pytest

HERE = Path(__file__).resolve().parent.parent.parent
IFACE_PORT = HERE / "corpus" / "iface_port_corpus.sv"
FIFO = HERE / "corpus" / "fifo.sv"


def _build(src: Path):
    text = src.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    comp = pyslang.Compilation()
    comp.addSyntaxTree(tree)
    from knowledge_graph.builders.sv.lift import lift
    from knowledge_graph.builders.sv.semantic import promote

    graph = lift(tree)
    promote(graph, tree, comp)
    return graph, text


@pytest.fixture(scope="module")
def s86_bundle():
    graph, _ = _build(IFACE_PORT)
    return graph


@pytest.fixture(scope="module")
def fifo_bundle():
    graph, _ = _build(FIFO)
    return graph


def test_s86_in_active_rule_ids():
    """S86 must be listed in ``_ACTIVE_RULE_IDS`` so the bucket1 checklist
    regenerator treats the stub as a live owner."""
    from knowledge_graph.builders.sv.semantic.dispatch import _ACTIVE_RULE_IDS
    assert "S86" in _ACTIVE_RULE_IDS


def test_s86_stub_owns_interface_port_header():
    """The metadata stub registered for ``SyntaxKind.InterfacePortHeader``
    must pin ``__rule_id__ == 'S86'`` and there must be exactly one
    registration for the kind."""
    from knowledge_graph.builders.sv.semantic.rules import structure
    matches = [
        fn for (kind, fn) in structure.RULES
        if kind == pyslang.SyntaxKind.InterfacePortHeader
    ]
    assert len(matches) == 1, (
        f"expected exactly one stub for InterfacePortHeader, "
        f"got {len(matches)}"
    )
    assert getattr(matches[0], "__rule_id__", None) == "S86"


def test_s86_dispatches_through_rule_table():
    """``SyntaxKind.InterfacePortHeader`` must resolve through the composed
    ``RULE_TABLE`` to the S86 stub."""
    from knowledge_graph.builders.sv.semantic.rules import RULE_TABLE
    fn = RULE_TABLE.get(pyslang.SyntaxKind.InterfacePortHeader)
    assert fn is not None, (
        "InterfacePortHeader missing from RULE_TABLE — structure.RULES "
        "did not register the S86 stub"
    )
    assert getattr(fn, "__rule_id__", None) == "S86"


def test_s86_promotes_interface_ports(s86_bundle):
    """Each of the three ports in iface_port_corpus.sv must promote with
    ``role == 'interface_port'``. The port names are ``a``, ``b``, ``c``
    in declaration order."""
    iface_ports = [n for n in s86_bundle["nodes"]
                   if n.get("semantic", {}).get("role") == "interface_port"]
    names = sorted(n["semantic"]["name"] for n in iface_ports)
    assert names == ["a", "b", "c"], (
        f"expected interface_port names ['a','b','c'], got {names}"
    )


def test_s86_lifts_interface_type_and_modport(s86_bundle):
    """The two modport-qualified ports (``a`` / ``b``) must carry both
    ``interface_type`` and ``modport`` attributes; the keyword-form port
    (``c``) carries only ``interface_type='interface'`` (no modport)."""
    by_name = {
        n["semantic"]["name"]: n["semantic"].get("attributes", {})
        for n in s86_bundle["nodes"]
        if n.get("semantic", {}).get("role") == "interface_port"
    }
    assert by_name["a"].get("interface_type") == "fifo_if"
    assert by_name["a"].get("modport") == "dut"
    assert by_name["b"].get("interface_type") == "fifo_if"
    assert by_name["b"].get("modport") == "consumer"
    assert by_name["c"].get("interface_type") == "interface"
    assert "modport" not in by_name["c"], (
        f"keyword-form interface port must not carry a modport attr, "
        f"got {by_name['c']}"
    )


def test_s86_keeps_has_port_edge(s86_bundle):
    """S86 must keep the S1 ``has_port`` edge from the enclosing module
    to each interface_port node (downstream queries that traverse ports
    via ``has_port`` continue to find these)."""
    iface_port_gids = {
        n["id"] for n in s86_bundle["nodes"]
        if n.get("semantic", {}).get("role") == "interface_port"
    }
    has_port_dsts = {
        e["dst"] for e in s86_bundle["edges"]
        if e.get("type") == "has_port" and e["dst"] in iface_port_gids
    }
    assert has_port_dsts == iface_port_gids, (
        f"missing has_port edges for interface ports: "
        f"{iface_port_gids - has_port_dsts}"
    )


def test_s86_does_not_regress_s1_plain_ports(fifo_bundle):
    """``corpus/fifo.sv`` exercises only variable-typed ANSI ports (no
    interface ports). S86 must not flip any of those to
    ``role='interface_port'`` and must not emit unexpected
    ``interface_type`` / ``modport`` attributes on plain ports."""
    plain_ports = [n for n in fifo_bundle["nodes"]
                   if n.get("semantic", {}).get("role") == "port"]
    assert plain_ports, "fifo.sv should expose role=port nodes"
    rogue = [n for n in fifo_bundle["nodes"]
             if n.get("semantic", {}).get("role") == "interface_port"]
    assert rogue == [], (
        f"fifo.sv must not emit interface_port nodes, got {len(rogue)}"
    )
    for p in plain_ports:
        attrs = p["semantic"].get("attributes", {}) or {}
        assert "interface_type" not in attrs
        assert "modport" not in attrs


def test_s86_round_trip_token_stream():
    """Round-trip the iface_port_corpus.sv source through the lift + emit
    pipeline; the reparsed token text stream must match the original
    (same oracle the test_roundtrip suite uses)."""
    from knowledge_graph.builders.sv.lift import lift
    from knowledge_graph.builders.sv.unlift import emit

    def _token_text_stream(node, out=None):
        if out is None:
            out = []
        if type(node).__name__ == "Token":
            for tr in node.trivia:
                out.append(tr.getRawText())
            out.append(node.rawText)
            return out
        try:
            for c in node:
                _token_text_stream(c, out)
        except TypeError:
            pass
        return out

    text = IFACE_PORT.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    graph = lift(tree)
    out = emit(graph)
    reparsed = pyslang.SyntaxTree.fromText(out)
    assert _token_text_stream(reparsed.root) == _token_text_stream(tree.root)
