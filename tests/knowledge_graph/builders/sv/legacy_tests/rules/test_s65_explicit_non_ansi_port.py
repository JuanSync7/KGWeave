"""Tests for S65 — ExplicitNonAnsiPort promotion.

Exercises ``legacy_explicit_demo`` (corpus/fifo.sv). Each ``.name(expr)`` in
the **non-ANSI** port list — the legacy Verilog-2001 form where the header
carries names only and directions arrive via separate ``input``/``output``
statements in the body — parses as SyntaxKind.ExplicitNonAnsiPort (sibling
of S1 ImplicitAnsiPort and S64 ExplicitAnsiPort). The empty-connect
``.b()`` form is also ExplicitNonAnsiPort (PortReference child absent). S65
promotes each header entry as role="port" attached to the enclosing module
via ``has_port``. Direction lives on the body PortDeclaration (S55), not
the header.
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


def _explicit_non_ansi_port_nodes(graph):
    """Return port nodes promoted off ExplicitNonAnsiPortSyntax kind."""
    out = []
    for n in _by_role(graph, "port"):
        if n.get("kind", "").endswith("ExplicitNonAnsiPort"):
            out.append(n)
    return out


def test_s65_explicit_non_ansi_ports_promoted(fixture_bundle):
    """Every ExplicitNonAnsiPort in legacy_explicit_demo surfaces as role=port."""
    _t, _c, graph = fixture_bundle
    ports = _explicit_non_ansi_port_nodes(graph)
    names = {p["semantic"]["name"] for p in ports}
    assert names == {"a", "b"}, (
        f"explicit non-ANSI header port names mismatch: {names}"
    )


def test_s65_has_port_edges_from_enclosing_module(fixture_bundle):
    """Each ExplicitNonAnsiPort node has a has_port edge from
    legacy_explicit_demo as its source."""
    _t, _c, graph = fixture_bundle
    mods = {m["semantic"]["name"]: m for m in _by_role(graph, "module")}
    mod_id = mods["legacy_explicit_demo"]["id"]
    ports = _explicit_non_ansi_port_nodes(graph)
    assert len(ports) == 2
    for p in ports:
        incoming = [e for e in graph["edges"]
                    if e["type"] == "has_port" and e["dst"] == p["id"]]
        assert any(e["src"] == mod_id for e in incoming), (
            f"{p['semantic']['path']}: no has_port from legacy_explicit_demo"
        )


def test_s65_path_keys_correct(fixture_bundle):
    """Header port path keys follow the <module>.<port_name> convention."""
    _t, _c, graph = fixture_bundle
    paths = {p["semantic"]["path"] for p in _explicit_non_ansi_port_nodes(graph)}
    assert paths == {
        "legacy_explicit_demo.a",
        "legacy_explicit_demo.b",
    }


def test_s65_empty_connect_form_promotes(fixture_bundle):
    """The empty-connect ``.b()`` header form (no PortReference child) must
    promote cleanly — pyslang still hands us an ExplicitNonAnsiPort node."""
    _t, _c, graph = fixture_bundle
    bare = [p for p in _explicit_non_ansi_port_nodes(graph)
            if p["semantic"]["name"] == "b"]
    assert len(bare) == 1, f"expected exactly one header .b, got {len(bare)}"


def test_s65_roundtrip(fixture_bundle):
    """Promotion must not perturb the token stream — emit() reproduces source."""
    _t, _c, graph = fixture_bundle
    from research.ast_experiment.src.unlift import emit
    assert emit(graph) == SRC.read_text()


def test_s65_does_not_regress_sibling_port_rules(fixture_bundle):
    """S1 (fifo ANSI), S55 (nonansi_demo body), and S64 (ansi_explicit_demo)
    port sets all remain intact after S65 ships."""
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
