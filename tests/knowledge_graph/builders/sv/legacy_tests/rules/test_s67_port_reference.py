"""Tests for S67 — PortReference promotion.

PortReferenceSyntax is the sub-expression inside non-ANSI port lists naming a
referenced port. It appears in two distinct contexts in the corpus:

1. As the ``expr`` child of an ``ImplicitNonAnsiPort`` (legacy bare-name
   header form: ``module legacy_implicit_demo(a, b, ...)``). S66 already
   promotes the enclosing ImplicitNonAnsiPort node as role=port keyed by the
   PortReference's name token — for those cases S67 dedupes on the same
   ``<module>.<port_name>`` path (no second port node is emitted) but the
   PortReference SyntaxKind itself still gets ``role=port_reference`` so it
   is queryable and queries on PortReference-shaped sub-nodes work.

2. As the connect expression inside an ``ExplicitNonAnsiPort`` (legacy
   ``.name(expr)`` form: ``module legacy_explicit_demo(.a(p), .b());``).
   The PortReference here names the *internal* signal (``p``), not the
   external port name. S67 emits ``role=port_reference`` for it with path
   ``<module>.port_reference.<name>`` — distinct from S65's
   ``<module>.<external_port_name>`` so the two coexist.

3. As an item of a ``PortConcatenation`` (S68 future). Same shape as case 2:
   role=port_reference, path ``<module>.port_reference.<name>``. Exercised
   by ``{x, y}`` in ``legacy_implicit_demo``.

The PortConcatenation case exercises sub-context (no surrounding promoted
port at the same name). The ImplicitNonAnsiPort case exercises the
augment-with-twin pattern (lesson 5 flavored — port already promoted by S66,
PortReference also gets its own role attached).
"""

from __future__ import annotations

from pathlib import Path

import pyslang
import pytest

HERE = Path(__file__).resolve().parent.parent.parent
SRC = HERE / "corpus" / "fifo.sv"


@pytest.fixture(scope="module")
def fixture_bundle():
    text = SRC.read_text()
    tree = pyslang.SyntaxTree.fromText(text)
    comp = pyslang.Compilation()
    comp.addSyntaxTree(tree)
    from knowledge_graph.builders.sv.lift import lift
    from knowledge_graph.builders.sv.semantic import promote

    graph = lift(tree)
    promote(graph, tree, comp)
    return tree, comp, graph


def _by_role(graph, role):
    from knowledge_graph.builders.sv.semantic import queryable_nodes

    return [n for n in queryable_nodes(graph)
            if n.get("semantic", {}).get("role") == role]


def _port_ref_nodes(graph):
    return [n for n in _by_role(graph, "port_reference")
            if n.get("kind", "").endswith("PortReference")]


def test_s67_port_reference_role_registered(fixture_bundle):
    """Every PortReferenceSyntax instance in the corpus surfaces as
    role=port_reference (PromotedKind=PortReference)."""
    _t, _c, graph = fixture_bundle
    refs = _port_ref_nodes(graph)
    # Corpus has 11 PortReferenceSyntax instances total — see comment block
    # at top of this file for the breakdown.
    assert len(refs) >= 11, f"expected >=11 PortReference nodes, got {len(refs)}"


def test_s67_legacy_implicit_demo_names(fixture_bundle):
    """The bare-name entries (a, b) and concatenation items (x, y) under
    legacy_implicit_demo all surface as port_reference role."""
    _t, _c, graph = fixture_bundle
    refs = _port_ref_nodes(graph)
    names = {r["semantic"]["name"] for r in refs
             if r["semantic"].get("path", "").startswith(
                 "legacy_implicit_demo.")}
    assert {"a", "b", "x", "y"} <= names, (
        f"legacy_implicit_demo PortReferences missing: got {names}"
    )


def test_s67_legacy_explicit_demo_internal_name(fixture_bundle):
    """The ``.a(p)`` form in legacy_explicit_demo carries a PortReference
    naming the internal signal ``p``. S67 surfaces it with a distinct
    path key (``<module>.port_reference.p``) so it doesn't collide with
    S65's external-port node at ``<module>.a``."""
    _t, _c, graph = fixture_bundle
    refs = _port_ref_nodes(graph)
    paths = {r["semantic"]["path"] for r in refs
             if r["semantic"].get("path", "").startswith(
                 "legacy_explicit_demo.")}
    # The PortReference for ``p`` lives under a distinct sub-namespace.
    assert "legacy_explicit_demo.port_reference.p" in paths, (
        f"explicit-form PortReference path missing: {paths}"
    )


def test_s67_does_not_duplicate_s66_port(fixture_bundle):
    """S66 already emits one role=port node per bare-name ImplicitNonAnsiPort
    in legacy_implicit_demo (a, b). S67 must NOT spawn extra role=port nodes
    at the same paths — the count of role=port nodes there stays at 2."""
    _t, _c, graph = fixture_bundle
    ports = [n for n in _by_role(graph, "port")
             if n["semantic"].get("path", "").startswith(
                 "legacy_implicit_demo.")
             and n.get("kind", "").endswith("ImplicitNonAnsiPort")]
    # S66 emits exactly 2 role=port (a, b); the {x,y} concat form is skipped
    # by S66 and stays uncovered as role=port.
    assert len(ports) == 2, (
        f"S67 unexpectedly duplicated S66 port nodes: {len(ports)} != 2"
    )


def test_s67_path_keys_under_implicit_non_ansi(fixture_bundle):
    """Inside ImplicitNonAnsiPort headers (case 1), the PortReference path
    matches the enclosing port — `<module>.<name>` — so callers can resolve
    bare references to the port directly."""
    _t, _c, graph = fixture_bundle
    refs = _port_ref_nodes(graph)
    paths = {r["semantic"]["path"] for r in refs}
    # The simple-form bare-name cases reuse the port path key.
    assert "legacy_implicit_demo.a" in paths
    assert "legacy_implicit_demo.b" in paths


def test_s67_nonansi_demo_port_references(fixture_bundle):
    """nonansi_demo(a, b, c, d, e, f) — every bare-name header entry has a
    PortReference child; all six surface as port_reference nodes too."""
    _t, _c, graph = fixture_bundle
    refs = _port_ref_nodes(graph)
    names = {r["semantic"]["name"] for r in refs
             if r["semantic"].get("path", "").startswith("nonansi_demo.")}
    assert {"a", "b", "c", "d", "e", "f"} <= names, (
        f"nonansi_demo PortReferences missing: got {names}"
    )


def test_s67_roundtrip(fixture_bundle):
    """Promotion must not perturb the token stream — emit() reproduces source."""
    _t, _c, graph = fixture_bundle
    from knowledge_graph.builders.sv.unlift import emit
    assert emit(graph) == SRC.read_text()


def test_s67_does_not_regress_sibling_port_rules(fixture_bundle):
    """S1, S55, S64, S65, S66 port sets stay intact after S67 ships."""
    _t, _c, graph = fixture_bundle
    fifo_ports = {p["semantic"]["name"] for p in _by_role(graph, "port")
                  if p["semantic"]["path"].startswith("fifo.")}
    assert fifo_ports == {
        "clk", "rst_n", "push", "pop", "din", "dout",
        "full", "empty", "status",
    }
    nonansi_ports = {p["semantic"]["name"] for p in _by_role(graph, "port")
                     if p["semantic"]["path"].startswith("nonansi_demo.")}
    assert nonansi_ports == {"a", "b", "c", "d", "e", "f"}
    ansi_explicit = {p["semantic"]["name"] for p in _by_role(graph, "port")
                     if p["semantic"]["path"].startswith("ansi_explicit_demo.")}
    assert ansi_explicit == {"pa", "pb", "pc", "pd"}
    legacy_explicit = {p["semantic"]["name"] for p in _by_role(graph, "port")
                       if p["semantic"]["path"].startswith(
                           "legacy_explicit_demo.")}
    assert {"a", "b"} <= legacy_explicit
    # S66 — legacy_implicit_demo bare ports
    implicit_ports = {p["semantic"]["name"] for p in _by_role(graph, "port")
                      if p["semantic"]["path"].startswith(
                          "legacy_implicit_demo.")
                      and p.get("kind", "").endswith("ImplicitNonAnsiPort")}
    assert implicit_ports == {"a", "b"}
