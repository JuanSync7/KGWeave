"""Tests for S66 — ImplicitNonAnsiPort promotion.

Exercises ``legacy_implicit_demo`` (corpus/fifo.sv). Each bare-name entry in
the **non-ANSI** port list — the legacy Verilog-2001 form where the header
carries only identifiers and directions arrive via separate
``input``/``output`` statements in the body — parses as
SyntaxKind.ImplicitNonAnsiPort (sibling of S1 ImplicitAnsiPort, S64
ExplicitAnsiPort, S65 ExplicitNonAnsiPort). The expr child is a
PortReferenceSyntax carrying the identifier; the concatenation entry
``{x, y}`` parses as ImplicitNonAnsiPort wrapping a
PortConcatenationSyntax, which S66 intentionally skips (no single name to
key on). S66 promotes each plain entry as role="port" attached to the
enclosing module via ``has_port``. Direction lives on the body
PortDeclaration (S55), not the header.
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
    from research.ast_experiment.src.lift import lift
    from research.ast_experiment.src.semantic import promote

    graph = lift(tree)
    promote(graph, tree, comp)
    return tree, comp, graph


def _by_role(graph, role):
    from research.ast_experiment.src.semantic import queryable_nodes

    return [n for n in queryable_nodes(graph)
            if n.get("semantic", {}).get("role") == role]


def _implicit_non_ansi_port_nodes(graph):
    """Return port nodes promoted off ImplicitNonAnsiPortSyntax kind."""
    out = []
    for n in _by_role(graph, "port"):
        if n.get("kind", "").endswith("ImplicitNonAnsiPort"):
            out.append(n)
    return out


def test_s66_implicit_non_ansi_ports_promoted(fixture_bundle):
    """Every plain ImplicitNonAnsiPort in legacy_implicit_demo surfaces as
    role=port; the PortConcatenation entry is intentionally skipped."""
    _t, _c, graph = fixture_bundle
    ports = [p for p in _implicit_non_ansi_port_nodes(graph)
             if p["semantic"]["path"].startswith("legacy_implicit_demo.")]
    names = {p["semantic"]["name"] for p in ports}
    assert names == {"a", "b"}, (
        f"implicit non-ANSI header port names mismatch: {names}"
    )


def test_s66_has_port_edges_from_enclosing_module(fixture_bundle):
    """Each S66 port node has a has_port edge from legacy_implicit_demo."""
    _t, _c, graph = fixture_bundle
    mods = {m["semantic"]["name"]: m for m in _by_role(graph, "module")}
    mod_id = mods["legacy_implicit_demo"]["id"]
    ports = [p for p in _implicit_non_ansi_port_nodes(graph)
             if p["semantic"]["path"].startswith("legacy_implicit_demo.")]
    assert len(ports) == 2
    for p in ports:
        incoming = [e for e in graph["edges"]
                    if e["type"] == "has_port" and e["dst"] == p["id"]]
        assert any(e["src"] == mod_id for e in incoming), (
            f"{p['semantic']['path']}: no has_port from legacy_implicit_demo"
        )


def test_s66_path_keys_correct(fixture_bundle):
    """Header port path keys follow the <module>.<port_name> convention."""
    _t, _c, graph = fixture_bundle
    paths = {p["semantic"]["path"]
             for p in _implicit_non_ansi_port_nodes(graph)
             if p["semantic"]["path"].startswith("legacy_implicit_demo.")}
    assert paths == {
        "legacy_implicit_demo.a",
        "legacy_implicit_demo.b",
    }


def test_s66_concatenation_form_skipped(fixture_bundle):
    """The ``{x, y}`` PortConcatenation entry is intentionally NOT promoted
    by S66 — no single port name to key on. The corpus body still binds x
    and y via S55 PortDeclaration, so a future port-concatenation rule can
    layer over this without conflict."""
    _t, _c, graph = fixture_bundle
    # No promoted ImplicitNonAnsiPort node should have a concatenation name.
    inap_names = {p["semantic"]["name"]
                  for p in _implicit_non_ansi_port_nodes(graph)
                  if p["semantic"]["path"].startswith("legacy_implicit_demo.")}
    assert "{x, y}" not in inap_names
    assert "x" not in inap_names  # x/y come only from body S55, not header S66
    assert "y" not in inap_names


def test_s66_roundtrip(fixture_bundle):
    """Promotion must not perturb the token stream — emit() reproduces source."""
    _t, _c, graph = fixture_bundle
    from research.ast_experiment.src.unlift import emit
    assert emit(graph) == SRC.read_text()


def test_s66_does_not_regress_sibling_port_rules(fixture_bundle):
    """S1 (fifo ANSI), S55 (nonansi_demo body), S64 (ansi_explicit_demo) and
    S65 (legacy_explicit_demo) port sets remain intact after S66 ships."""
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
    # legacy_explicit_demo: header S65 promotes {a, b}; body S55 also binds
    # ``input p, b;`` so p surfaces too. The S65 sibling test filters by
    # kind; here we just confirm the header names remain visible.
    legacy_explicit = {p["semantic"]["name"] for p in _by_role(graph, "port")
                       if p["semantic"]["path"].startswith("legacy_explicit_demo.")}
    assert {"a", "b"} <= legacy_explicit
