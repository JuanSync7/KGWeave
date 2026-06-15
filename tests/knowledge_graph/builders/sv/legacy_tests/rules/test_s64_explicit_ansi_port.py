"""Tests for S64 — ExplicitAnsiPort promotion.

Exercises ``ansi_explicit_demo`` (corpus/fifo.sv). Each ``.name(expr)`` in the
ANSI port list, prefixed by a direction keyword, parses as
SyntaxKind.ExplicitAnsiPort (sibling of S1 ImplicitAnsiPort). S64 promotes
each as role="port" with direction lifted from the leading direction token.
The empty-connect form ``.pd()`` is exercised to verify the rule does not
crash when ``.expr`` is None.
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


def test_s64_explicit_ansi_ports_promoted(fixture_bundle):
    """Every ExplicitAnsiPort in ansi_explicit_demo surfaces as role=port."""
    _t, _c, graph = fixture_bundle
    ports = _by_role(graph, "port")
    names = {p["semantic"]["name"] for p in ports
             if p["semantic"]["path"].startswith("ansi_explicit_demo.")}
    assert names == {"pa", "pb", "pc", "pd"}, (
        f"explicit ANSI port names mismatch: {names}"
    )


def test_s64_direction_attrs(fixture_bundle):
    """Each ExplicitAnsiPort carries the direction keyword as an attribute."""
    _t, _c, graph = fixture_bundle
    ports = {p["semantic"]["name"]: p for p in _by_role(graph, "port")
             if p["semantic"]["path"].startswith("ansi_explicit_demo.")}
    expected = {"pa": "input", "pb": "output", "pc": "inout", "pd": "input"}
    for name, want in expected.items():
        attrs = ports[name]["semantic"].get("attributes", {})
        assert attrs.get("direction") == want, (
            f"{name}: expected direction={want}, got {attrs}"
        )


def test_s64_has_port_edges_from_enclosing_module(fixture_bundle):
    """Each explicit ANSI port has exactly one inbound has_port edge from the
    enclosing ansi_explicit_demo module."""
    _t, _c, graph = fixture_bundle
    mods = {m["semantic"]["name"]: m for m in _by_role(graph, "module")}
    mod_id = mods["ansi_explicit_demo"]["id"]
    ports = [p for p in _by_role(graph, "port")
             if p["semantic"]["path"].startswith("ansi_explicit_demo.")]
    assert len(ports) == 4
    for p in ports:
        incoming = [e for e in graph["edges"]
                    if e["type"] == "has_port" and e["dst"] == p["id"]]
        assert len(incoming) == 1, (
            f"{p['semantic']['path']}: has_port incoming = {len(incoming)}"
        )
        assert incoming[0]["src"] == mod_id, (
            f"{p['semantic']['path']}: has_port src is not ansi_explicit_demo"
        )


def test_s64_path_keys_correct(fixture_bundle):
    """Path keys use the <module>.<port_name> form, mirroring S1."""
    _t, _c, graph = fixture_bundle
    paths = {p["semantic"]["path"] for p in _by_role(graph, "port")
             if p["semantic"]["path"].startswith("ansi_explicit_demo.")}
    assert paths == {
        "ansi_explicit_demo.pa",
        "ansi_explicit_demo.pb",
        "ansi_explicit_demo.pc",
        "ansi_explicit_demo.pd",
    }


def test_s64_empty_connect_does_not_crash(fixture_bundle):
    """The empty-connect form ``.pd()`` (expr=None) must promote cleanly."""
    _t, _c, graph = fixture_bundle
    pd = [p for p in _by_role(graph, "port")
          if p["semantic"]["path"] == "ansi_explicit_demo.pd"]
    assert len(pd) == 1, f"expected exactly one pd port, got {len(pd)}"
    attrs = pd[0]["semantic"].get("attributes", {})
    assert attrs.get("direction") == "input"


def test_s64_roundtrip(fixture_bundle):
    """Promotion must not perturb the token stream — emit() reproduces source."""
    _t, _c, graph = fixture_bundle
    from knowledge_graph.builders.sv.unlift import emit
    assert emit(graph) == SRC.read_text()


def test_s64_does_not_regress_existing_ports(fixture_bundle):
    """fifo's S1 ANSI ports and nonansi_demo's S55 ports keep their full sets."""
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
