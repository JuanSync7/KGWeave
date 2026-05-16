"""S77 — ``AssertionItemPort`` promotion.

An ``AssertionItemPort`` is one entry in a parameterised property /
sequence / let signature::

    property p_with_ports(logic sig, int n);
        @(posedge clk) sig |-> ##n !sig;
    endproperty

Each ``logic sig`` / ``int n`` parses as ``SyntaxKind.AssertionItemPort``
under an ``AssertionItemPortListSyntax`` wrapper. S77 promotes the port
as a queryable node attached to the enclosing property / sequence / let
scope on ``sva_decl_stack``. Direction, data_type, name, and the
``local`` qualifier are surfaced as attributes; ``defaultValue`` (when
present) is captured as ``has_default``.

Corpus coverage (``corpus/fifo_asserts.sv``, module ``fifo_asserts`` and
``let_decl_demo``):

* ``fifo_asserts.p_with_ports``     — 2 ports: ``sig``, ``n``
* ``fifo_asserts.s_with_ports``     — 2 ports: ``a``, ``b``
* ``fifo_asserts.p_dir_ports``      — 2 ports: ``local input logic sig``,
  ``logic gate``
* ``let_decl_demo.nonzero``         — 1 port: ``x``
* ``let_decl_demo.in_range``        — 2 ports: ``a``, ``b``
* ``let_decl_demo.always_true``     — 0 ports
* ``let_decl_demo.bounded``         — 2 ports: ``int x``, ``int hi = 8``

Total: 11 AssertionItemPort promotions.
"""

from __future__ import annotations

from pathlib import Path

import pyslang
import pytest

HERE = Path(__file__).resolve().parent.parent.parent
CORPUS_DIR = HERE / "corpus"
ASSERTS = CORPUS_DIR / "fifo_asserts.sv"


@pytest.fixture(scope="module")
def asserts_graph():
    text = ASSERTS.read_text()
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


# ---------------------------------------------------------------------------
# Registration / metadata
# ---------------------------------------------------------------------------

def test_s77_ownership_stub_attributed():
    """``AssertionItemPort`` in the assertions RULES table carries ``S77``."""
    from research.ast_experiment.src.semantic.rules.assertions import RULES

    matches = [(k, fn) for (k, fn) in RULES
               if k == pyslang.SyntaxKind.AssertionItemPort]
    assert len(matches) == 1
    _, fn = matches[0]
    assert getattr(fn, "__rule_id__", None) == "S77"


def test_s77_active_rule_registered():
    """S77 is in ``_ACTIVE_RULE_IDS``."""
    from research.ast_experiment.src.semantic.dispatch import _ACTIVE_RULE_IDS

    assert "S77" in _ACTIVE_RULE_IDS


def test_s77_kind_in_rule_table():
    """Composed RULE_TABLE dispatches ``AssertionItemPort`` to the S77 stub."""
    from research.ast_experiment.src.semantic.rules import RULE_TABLE

    fn = RULE_TABLE.get(pyslang.SyntaxKind.AssertionItemPort)
    assert fn is not None
    assert getattr(fn, "__rule_id__", None) == "S77"


# ---------------------------------------------------------------------------
# Promotion against fifo_asserts.sv
# ---------------------------------------------------------------------------

def test_s77_property_ports_promoted(asserts_graph):
    """``p_with_ports(logic sig, int n)`` — both ports promote under
    ``fifo_asserts.p_with_ports``."""
    ports = _by_role(asserts_graph, "assertion_item_port")
    paths = {p["semantic"]["path"] for p in ports}
    assert "fifo_asserts.p_with_ports.sig" in paths
    assert "fifo_asserts.p_with_ports.n" in paths


def test_s77_sequence_ports_promoted(asserts_graph):
    """``s_with_ports(logic a, logic b)`` — both ports promote under
    ``fifo_asserts.s_with_ports``."""
    ports = _by_role(asserts_graph, "assertion_item_port")
    paths = {p["semantic"]["path"] for p in ports}
    assert "fifo_asserts.s_with_ports.a" in paths
    assert "fifo_asserts.s_with_ports.b" in paths


def test_s77_let_ports_promoted(asserts_graph):
    """``nonzero(x)`` / ``in_range(a, b)`` / ``bounded(input int x, int hi=8)``
    — all let ports promote under their let scope."""
    ports = _by_role(asserts_graph, "assertion_item_port")
    paths = {p["semantic"]["path"] for p in ports}
    assert "let_decl_demo.nonzero.x" in paths
    assert "let_decl_demo.in_range.a" in paths
    assert "let_decl_demo.in_range.b" in paths
    assert "let_decl_demo.bounded.x" in paths
    assert "let_decl_demo.bounded.hi" in paths


def test_s77_total_count(asserts_graph):
    """11 AssertionItemPort promotions in the corpus."""
    ports = _by_role(asserts_graph, "assertion_item_port")
    assert len(ports) == 11, [p["semantic"]["path"] for p in ports]


def test_s77_attrs_data_type_and_name(asserts_graph):
    """data_type / name attrs are preserved on the promoted node."""
    by_path = {p["semantic"]["path"]: p
               for p in _by_role(asserts_graph, "assertion_item_port")}
    sig = by_path["fifo_asserts.p_with_ports.sig"]
    attrs = sig["semantic"].get("attributes", {})
    assert attrs.get("name") == "sig"
    assert "logic" in (attrs.get("data_type") or "")
    n_port = by_path["fifo_asserts.p_with_ports.n"]
    assert "int" in (n_port["semantic"]["attributes"].get("data_type") or "")


def test_s77_direction_attribute(asserts_graph):
    """``p_dir_ports(local input logic sig, logic gate)`` — ``input`` is
    preserved on sig; gate has empty direction. ``let`` ports never carry
    a direction (LRM forbids it)."""
    by_path = {p["semantic"]["path"]: p
               for p in _by_role(asserts_graph, "assertion_item_port")}
    sig = by_path["fifo_asserts.p_dir_ports.sig"]
    assert sig["semantic"]["attributes"].get("direction") == "input"
    gate = by_path["fifo_asserts.p_dir_ports.gate"]
    assert gate["semantic"]["attributes"].get("direction") in ("", None)
    # bounded — both let ports must report empty direction.
    x = by_path["let_decl_demo.bounded.x"]
    assert x["semantic"]["attributes"].get("direction") in ("", None)


def test_s77_default_value_flag(asserts_graph):
    """``int hi = 8`` — has_default flag is True; ports without default
    surface ``has_default=False``."""
    by_path = {p["semantic"]["path"]: p
               for p in _by_role(asserts_graph, "assertion_item_port")}
    hi = by_path["let_decl_demo.bounded.hi"]
    assert hi["semantic"]["attributes"].get("has_default") is True
    x = by_path["let_decl_demo.bounded.x"]
    assert x["semantic"]["attributes"].get("has_default") is False


def test_s77_local_attribute(asserts_graph):
    """``p_dir_ports.sig`` is declared ``local input`` — its local attr
    must be True; the remaining ports report ``local=False``."""
    by_path = {p["semantic"]["path"]: p
               for p in _by_role(asserts_graph, "assertion_item_port")}
    sig = by_path["fifo_asserts.p_dir_ports.sig"]
    assert sig["semantic"]["attributes"].get("local") is True
    for path, p in by_path.items():
        if path == "fifo_asserts.p_dir_ports.sig":
            continue
        assert p["semantic"]["attributes"].get("local") is False, path


def test_s77_has_assertion_item_port_edges(asserts_graph):
    """Each promoted port has exactly one inbound has_assertion_item_port
    edge from its enclosing property/sequence/let."""
    ports = _by_role(asserts_graph, "assertion_item_port")
    edges = [e for e in asserts_graph["edges"]
             if e.get("type") == "has_assertion_item_port"]
    assert len(edges) == len(ports)
    for p in ports:
        inbound = [e for e in edges if e["dst"] == p["id"]]
        assert len(inbound) == 1, (
            f"{p['semantic']['path']}: expected 1 has_assertion_item_port "
            f"edge, got {len(inbound)}"
        )


def test_s77_roundtrip(asserts_graph):
    """Promotion does not perturb the token stream — emit() == source."""
    from research.ast_experiment.src.unlift import emit
    assert emit(asserts_graph) == ASSERTS.read_text()
